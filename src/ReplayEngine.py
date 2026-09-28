from src.artifact_schema import validate_artifact
from src.exceptions import ElementNotFoundError
from typing import Optional
from selenium.common.exceptions import (
    InvalidSessionIdException,
    NoSuchWindowException,
    StaleElementReferenceException,
    TimeoutException,
    UnexpectedAlertPresentException,
    WebDriverException,
)

class ReplayEngine:
    def __init__(self, surface, policy, recorder, chatbot=None):
        self.surface = surface
        self.policy = policy
        self.chatbot = chatbot
        self.recorder = recorder

    def run(self, artifact: dict, parameters: dict):
        """Return success, business_outcome, or a diagnostic failure result."""
        parameters = parameters or {}
        artifact, restored_inputs = self._restore_redacted_input_declarations(
            artifact,
            parameters,
        )
        if restored_inputs and self.recorder is not None:
            self.recorder.record_event(
                "artifact_input_declarations_restored",
                input_names=sorted(restored_inputs),
                source="current_goal_input_definitions",
            )
        try:
            self._validate_artifact(artifact)
        except Exception as error:
            return self._finalize_result(self._failure_result(
                error,
                artifact if isinstance(artifact, dict) else {},
                code="invalid_artifact",
                category="artifact_validation",
                expected="A valid browser workflow artifact",
            ), artifact)

        try:
            self._validate_parameters(artifact, parameters)
        except Exception as error:
            return self._finalize_result(self._failure_result(
                error,
                artifact,
                code="invalid_parameters",
                category="input_validation",
                expected=artifact.get("inputs", {}),
            ), artifact)

        try:
            result = self._run_steps(artifact, parameters)
        except Exception as error:
            result = self._failure_result(
                error,
                artifact,
                code=self._error_code(error),
                category=self._error_category(error),
            )
        return self._finalize_result(result, artifact)

    def _run_steps(self, artifact: dict, parameters: dict):
        approved = False

        for step_number, step in enumerate(artifact["steps"], start=1):
            action = step["action"]
            target = step.get("target")
            expected = self._step_expectation(step)
            try:
                if self.chatbot is not None:
                    self.chatbot.wait_for_agent_control()
                self.policy.validate_step(step, human_approved=approved)
                if action in {"navigate", "navigate to"}:
                    self.policy.validate_url(target["value"])
                value = self.resolve_value(step.get("value"), parameters)
            except Exception as error:
                return self._failure_result(
                    error,
                    artifact,
                    step_number=step_number,
                    action=action,
                    expected=expected,
                )

            if action in {"navigate", "navigate to"}:
                operation = lambda: self.surface.navigate_to(target["value"])
            elif action == "click":
                operation = lambda: self.surface.click(target)
            elif action == "input":
                operation = lambda: self.surface.input(target, value)
            elif action == "select":
                operation = lambda: self.surface.select(target, value)
            elif action == "wait_for_element":
                operation = lambda: self.surface.wait_for_purpose(
                    target["purpose"], target.get("action", "inspect"),
                    step.get("timeout_seconds", 10),
                )
            elif action == "human_review":
                try:
                    result = self.request_human_review(step["reason"])
                except Exception as error:
                    return self._failure_result(
                        error,
                        artifact,
                        step_number=step_number,
                        action=action,
                        expected=step["reason"],
                    )
                if result is not None:
                    return self._failure_result(
                        RuntimeError("Human review was not approved."),
                        artifact,
                        step_number=step_number,
                        action=action,
                        expected=step["reason"],
                        code=result.get("code", "human_review_declined"),
                        category="human_intervention",
                    )
                approved = True
            elif action == "verify":
                strategy = target.get("strategy", "verify_login")
                try:
                    verified = self.surface.verify(
                        strategy,
                        value,
                        target.get("action", "inspect"),
                    )
                except Exception as error:
                    return self._failure_result(
                        error,
                        artifact,
                        step_number=step_number,
                        action=action,
                        expected=expected,
                    )
                if not verified:
                    try:
                        observed = self.surface.observe()
                    except Exception as error:
                        return self._failure_result(
                            error,
                            artifact,
                            step_number=step_number,
                            action=action,
                            expected=expected,
                        )
                    state_result = self._classify_observation(
                        artifact,
                        observed,
                        step_number,
                        action,
                        expected,
                    )
                    if state_result is not None:
                        return state_result
                    request = strategy.replace("_", " ")
                    try:
                        result = self.request_human_review(
                            f"Please complete {request}, then select complete."
                        )
                    except Exception as error:
                        return self._failure_result(
                            error,
                            artifact,
                            step_number=step_number,
                            action=action,
                            expected=expected,
                        )
                    if result is not None:
                        return self._failure_result(
                            RuntimeError("The required verification was not completed."),
                            artifact,
                            step_number=step_number,
                            action=action,
                            expected=expected,
                            code=result.get("code", "human_review_declined"),
                            category="human_intervention",
                        )
                    try:
                        verified = self.surface.verify(
                            strategy,
                            value,
                            target.get("action", "inspect"),
                        )
                    except Exception as error:
                        return self._failure_result(
                            error,
                            artifact,
                            step_number=step_number,
                            action=action,
                            expected=expected,
                        )
                    if not verified:
                        return self._failure_result(
                            RuntimeError("Verification remained false after human review."),
                            artifact,
                            step_number=step_number,
                            action=action,
                            expected=expected,
                            code="verification_not_confirmed",
                            category="checkpoint_failure",
                        )
            else:
                raise ValueError(f"Unsupported replay action: {action}")

            if action not in {"human_review", "verify"}:
                try:
                    operation_result = self._run_with_recovery(
                        operation,
                        action,
                        step,
                        step_number,
                    )
                except Exception as error:
                    return self._failure_result(
                        error,
                        artifact,
                        step_number=step_number,
                        action=action,
                        expected=expected,
                    )
                if action in {"navigate", "navigate to"} and operation_result is False:
                    return self._failure_result(
                        RuntimeError(f"Navigation failed for {target.get('value')}"),
                        artifact,
                        step_number=step_number,
                        action=action,
                        expected=expected,
                        code="navigation_failed",
                        category="load_failure",
                    )

            if self.recorder is not None:
                self.recorder.record_action(
                    action=action,
                    step_id=step_number,
                    target=target,
                    value=value,
                    result="completed",
                    reason=expected.get("condition"),
                )

            try:
                observed = self.surface.observe()
            except Exception as error:
                return self._failure_result(
                    error,
                    artifact,
                    step_number=step_number,
                    action=action,
                    expected=expected,
                )
            state_result = self._classify_observation(
                artifact,
                observed,
                step_number,
                action,
                expected,
            )
            if state_result is not None:
                return state_result

        return self.verify_success(artifact, step_number=len(artifact["steps"]))

    def _run_with_recovery(
            self,
            operation,
            action: str,
            step: dict,
            step_number: int,
    ):
        retryable_actions = {"navigate", "navigate to", "wait_for_element"}
        max_attempts = 2 if action in retryable_actions else 1

        for attempt in range(max_attempts):
            try:
                result = operation()
                if action in {"navigate", "navigate to"} and result is not False:
                    wait_for_page = getattr(self.surface, "wait_for_page_ready", None)
                    if callable(wait_for_page):
                        wait_for_page()
                if action in {"navigate", "navigate to"} and result is False:
                    if attempt + 1 < max_attempts:
                        self._record_recovery(step_number, step, "Navigation returned false; retrying once.")
                        wait_for_page = getattr(self.surface, "wait_for_page_ready", None)
                        if callable(wait_for_page):
                            try:
                                wait_for_page(timeout=5)
                            except TimeoutException:
                                pass
                        continue
                return result
            except (TimeoutException, StaleElementReferenceException) as error:
                if attempt + 1 >= max_attempts:
                    raise
                self._record_recovery(
                    step_number,
                    step,
                    f"{type(error).__name__}; retrying once after page readiness check.",
                )
                wait_for_page = getattr(self.surface, "wait_for_page_ready", None)
                if callable(wait_for_page):
                    try:
                        wait_for_page(timeout=5)
                    except TimeoutException:
                        pass

        return False

    def _record_recovery(self, step_number: int, step: dict, reason: str) -> None:
        if self.recorder is not None:
            self.recorder.record_event(
                "recovery_attempt",
                step_id=step_number,
                action=step.get("action"),
                reason=reason,
                target=step.get("target"),
            )

    def _classify_observation(
            self,
            artifact: dict,
            observed: dict,
            step_number: int,
            action: str,
            expected,
    ):
        visible_text = str(observed.get("visible_text", ""))
        normalized_text = visible_text.casefold()

        for outcome in artifact.get("business_outcomes", []):
            phrase = outcome["value"]
            if phrase.casefold() in normalized_text:
                return {
                    "status": "business_outcome",
                    "category": "business_outcome",
                    "code": outcome["code"],
                    "message": outcome["description"],
                    "step_number": step_number,
                    "action": action,
                    "expected": expected,
                    "observed": self._compact_observation(observed, phrase),
                    "outcome": {
                        "code": outcome["code"],
                        "description": outcome["description"],
                        "matched_text": phrase,
                    },
                }

        business_phrases = {
            "record_not_found": (
                "no such member", "member not found", "record not found",
                "no records found", "no results found", "no matching records",
            ),
            "account_not_found": ("account not found", "no such account"),
        }
        for code, phrases in business_phrases.items():
            phrase = next(
                (candidate for candidate in phrases if candidate in normalized_text),
                None,
            )
            if phrase:
                return {
                    "status": "business_outcome",
                    "category": "business_outcome",
                    "code": code,
                    "message": phrase.capitalize(),
                    "step_number": step_number,
                    "action": action,
                    "expected": expected,
                    "observed": self._compact_observation(observed, phrase),
                    "outcome": {"code": code, "matched_text": phrase},
                }

        failure_patterns = (
            ("session_timeout", "session_timeout", (
                "session expired", "session timed out", "session timeout",
                "please log in again",
            )),
            ("permission_denied", "permission_denied", (
                "permission denied", "access denied", "not authorized",
                "unauthorized", "forbidden",
            )),
            ("validation_error", "validation_error", (
                "validation error", "please correct the errors",
                "field is required", "required field", "invalid value",
            )),
            ("load_failure", "load_failure", (
                "failed to load", "service unavailable", "temporarily unavailable",
                "network error",
            )),
        )
        for category, code, phrases in failure_patterns:
            phrase = next(
                (candidate for candidate in phrases if candidate in normalized_text),
                None,
            )
            if phrase:
                return self._failure_result(
                    RuntimeError(f"Page reported: {phrase}"),
                    artifact,
                    step_number=step_number,
                    action=action,
                    expected=expected,
                    observed=observed,
                    code=code,
                    category=category,
                )
        return None

    @staticmethod
    def _step_expectation(step: dict) -> dict:
        action = step.get("action")
        target = step.get("target", {})
        return {
            "action": action,
            "target": target,
            "condition": (
                step.get("reason")
                or target.get("purpose")
                or target.get("value")
                or target.get("strategy")
            ),
        }

    def _failure_result(
            self,
            error: Exception,
            artifact: dict,
            step_number: Optional[int] = None,
            action: Optional[str] = None,
            expected=None,
            observed=None,
            code: Optional[str] = None,
            category: Optional[str] = None,
    ) -> dict:
        observed_state = self._compact_observation(observed)
        if not isinstance(observed_state, dict):
            try:
                observed_state = self._compact_observation(self.surface.observe()) or {}
            except Exception as observation_error:
                observed_state = {"observation_error": str(observation_error)}

        if isinstance(error, UnexpectedAlertPresentException):
            driver = getattr(self.surface, "driver", None)
            if driver is not None:
                try:
                    observed_state["alert_text"] = driver.switch_to.alert.text
                except Exception:
                    observed_state["alert_text"] = getattr(error, "msg", str(error))

        return {
            "status": "failure",
            "category": category or self._error_category(error),
            "code": code or self._error_code(error),
            "message": str(error),
            "step_number": step_number,
            "action": action,
            "expected": expected,
            "observed": observed_state,
            "error": {
                "type": type(error).__name__,
                "message": str(error),
            },
        }

    def _finalize_result(self, result: dict, artifact) -> dict:
        status = result.get("status", "failure")
        if status == "blocked":
            result["status"] = "failure"
            result.setdefault("category", "human_intervention")
            status = "failure"
        elif status == "success":
            result.setdefault("category", "success")
            result.setdefault("code", "completed")
            result.setdefault("outputs", {})
        elif status == "business_outcome":
            result.setdefault("category", "business_outcome")
        else:
            result["status"] = "failure"
            result.setdefault("category", "hard_failure")
            result.setdefault("code", "replay_failed")
            status = "failure"

        if result["status"] == "failure":
            if (
                    self.chatbot is not None
                    and result.get("step_number") is not None
                    and result.get("category") in {
                        "target_resolution",
                        "load_failure",
                        "validation_error",
                        "permission_denied",
                        "checkpoint_failure",
                        "output_contract",
                    }
            ):
                try:
                    response = self._request_intervention(
                        artifact,
                        {
                            "action": result.get("action"),
                            "target": (
                                result.get("expected", {}).get("target")
                                if isinstance(result.get("expected"), dict)
                                else None
                            ),
                        },
                        result["step_number"],
                        result.get("message", "Replay stopped."),
                    )
                    intervention_status = "acknowledged"
                    if isinstance(response, dict):
                        intervention_status = (
                            "unavailable"
                            if response.get("code") == "human_review_unavailable"
                            else "declined"
                        )
                    elif response is not None:
                        intervention_status = "declined"
                    result["intervention"] = {
                        "status": intervention_status,
                        "response": response,
                    }
                except Exception as error:
                    result["intervention"] = {
                        "status": "unavailable",
                        "error": str(error),
                    }
            result.setdefault("evidence", self._capture_failure_evidence(result))
            if self.recorder is not None and result.get("step_number") is not None:
                self.recorder.record_event(
                    "step_failure",
                    step_id=result["step_number"],
                    action=result.get("action"),
                    code=result.get("code"),
                    expected=result.get("expected"),
                    observed=result.get("observed"),
                    error=result.get("error"),
                )

        if self.recorder is not None:
            details = {
                key: result.get(key)
                for key in (
                    "category", "code", "message", "step_number", "action",
                    "expected", "observed", "outcome", "outputs", "evidence", "error",
                    "intervention",
                )
                if key in result
            }
            self.recorder.record_result(result["status"], **details)
        return result

    def _capture_failure_evidence(self, result: dict) -> dict:
        evidence = {"page_state": result.get("observed")}
        driver = getattr(self.surface, "driver", None)
        if self.recorder is not None and driver is not None:
            try:
                screenshot = self.recorder.capture_screenshot(
                    driver,
                    name=f"step_{result.get('step_number') or 'run'}_failure",
                )
                evidence["screenshot"] = str(screenshot)
            except Exception as error:
                evidence["screenshot_error"] = str(error)
        return evidence

    @staticmethod
    def _compact_observation(observed, matched_text: Optional[str] = None):
        if not isinstance(observed, dict):
            return None
        visible_text = str(observed.get("visible_text", ""))
        if matched_text and visible_text:
            match_index = visible_text.casefold().find(matched_text.casefold())
            if match_index >= 0:
                start = max(0, match_index - 100)
                visible_text = visible_text[start:match_index + len(matched_text) + 200]
        else:
            visible_text = visible_text[:500]
        return {
            "url": observed.get("url"),
            "title": observed.get("title"),
            "visible_text_excerpt": visible_text,
        }

    @staticmethod
    def _error_code(error: Exception) -> str:
        if isinstance(error, UnexpectedAlertPresentException):
            return "unexpected_dialog"
        if isinstance(error, (InvalidSessionIdException, NoSuchWindowException)):
            return "session_unavailable"
        if isinstance(error, PermissionError):
            return "permission_denied"
        if isinstance(error, ElementNotFoundError):
            return "target_not_found"
        if isinstance(error, TimeoutException):
            return "load_timeout"
        if isinstance(error, WebDriverException):
            message = str(error).casefold()
            if any(marker in message for marker in ("session", "window closed", "chrome not reachable")):
                return "session_unavailable"
            if any(marker in message for marker in ("net::err_", "connection refused", "unreachable", "page load")):
                return "load_failure"
        if isinstance(error, (ValueError, TypeError)):
            return "validation_error"
        return "action_failed"

    @staticmethod
    def _error_category(error: Exception) -> str:
        if isinstance(error, UnexpectedAlertPresentException):
            return "unexpected_dialog"
        if isinstance(error, (InvalidSessionIdException, NoSuchWindowException)):
            return "session_timeout"
        if isinstance(error, PermissionError):
            return "permission_denied"
        if isinstance(error, ElementNotFoundError):
            return "target_resolution"
        if isinstance(error, TimeoutException):
            return "load_failure"
        if isinstance(error, WebDriverException):
            message = str(error).casefold()
            if any(marker in message for marker in ("session", "window closed", "chrome not reachable")):
                return "session_timeout"
            if any(marker in message for marker in ("net::err_", "connection refused", "unreachable", "page load")):
                return "load_failure"
        if isinstance(error, (ValueError, TypeError)):
            return "validation_error"
        return "hard_failure"

    def ask_for_redacted_info(self, value: str):
        pass

    @staticmethod
    def _validate_artifact(artifact: dict) -> None:
        validate_artifact(artifact)

    @staticmethod
    def _restore_redacted_input_declarations(
            artifact,
            parameters: dict,
    ) -> tuple[dict, list[str]]:
        if not isinstance(artifact, dict):
            return artifact, []

        artifact_inputs = artifact.get("inputs")
        definitions = parameters.get("input_definitions", {})
        if not isinstance(artifact_inputs, dict) or not isinstance(definitions, dict):
            return artifact, []

        type_aliases = {
            "int": "integer",
            "integer": "integer",
            "float": "number",
            "number": "number",
            "bool": "boolean",
            "boolean": "boolean",
            "str": "string",
            "string": "string",
            "variant": "string",
        }
        definitions_by_name = {}
        for field_name, definition in definitions.items():
            if not isinstance(definition, dict):
                continue
            variable = str(definition.get("variable", field_name))
            name = variable.strip().strip("{}").strip()
            expected_type = str(
                definition.get("expected_input_type", "")
            ).casefold()
            artifact_type = type_aliases.get(expected_type)
            if name and artifact_type:
                definitions_by_name[name] = (definition, artifact_type)

        restored = dict(artifact_inputs)
        restored_names = []
        for raw_name, declaration in artifact_inputs.items():
            if isinstance(declaration, dict):
                continue
            name = str(raw_name).strip().strip("{}").strip()
            definition_pair = definitions_by_name.get(name)
            if definition_pair is None:
                continue
            definition, artifact_type = definition_pair
            restored[name] = {
                "type": artifact_type,
                "description": definition.get(
                    "description",
                    f"Invocation value for {name.replace('_', ' ')}.",
                ),
                "required": definition.get("required", True),
                "sensitive": definition.get("sensitive", True),
            }
            restored_names.append(name)

        if not restored_names:
            return artifact, []
        repaired_artifact = dict(artifact)
        repaired_artifact["inputs"] = restored
        return repaired_artifact, restored_names

    @staticmethod
    def _validate_parameters(artifact: dict, parameters: dict) -> None:
        supplied = parameters.get("required_fields", parameters)
        for name, declaration in artifact.get("inputs", {}).items():
            supplied_name = name if name in supplied else "{{" + name + "}}"
            if declaration.get("required", True) and supplied_name not in supplied:
                raise ValueError(f"Missing required artifact input: {name}")
            if supplied_name not in supplied:
                continue

            value = supplied[supplied_name]
            expected_type = declaration["type"]
            valid = (
                expected_type == "string" and isinstance(value, str)
                or expected_type == "integer" and (
                    isinstance(value, int) and not isinstance(value, bool) or (
                        isinstance(value, str) and value.strip().lstrip("-").isdigit()
                    )
                )
                or expected_type == "number" and (
                    isinstance(value, (int, float)) and not isinstance(value, bool)
                )
                or expected_type == "boolean" and isinstance(value, bool)
            )
            if not valid:
                raise ValueError(
                    f"Invalid type for artifact input {name}: expected {expected_type}"
                )

    def resolve_value(self, value, parameters):

        if value is None:
            return None

        if isinstance(value, str) and value.startswith("{{"):
            #name = value[2:-2].strip()
            name = value

            if name in parameters:
                return parameters[name]

            required_fields = parameters.get("required_fields", {})
            #print(f"the required fields are: {required_fields}")

            if name in required_fields:
                return required_fields[name]

            if name not in parameters:
                raise ValueError(
                    f"Missing required parameter: {name}"
                )

        return value

    def verify_success(self, artifact: dict, step_number: Optional[int] = None) -> dict:
        check = artifact["success_check"]
        try:
            observed = self.surface.observe()
        except Exception as error:
            return self._failure_result(
                error,
                artifact,
                step_number=step_number,
                action="success_check",
                expected=check,
                code="checkpoint_observation_failed",
                category="checkpoint_failure",
            )

        state_result = self._classify_observation(
            artifact,
            observed,
            step_number or len(artifact.get("steps", [])),
            "success_check",
            check,
        )
        if state_result is not None:
            return state_result

        if check["strategy"] == "text":
            expected = check["value"]

            if expected in observed.get("visible_text", ""):
                try:
                    outputs = self.extract_outputs(artifact)
                except Exception as error:
                    return self._failure_result(
                        error,
                        artifact,
                        step_number=step_number or len(artifact.get("steps", [])),
                        action="extract_outputs",
                        expected=artifact.get("output_schema", {}),
                        observed=observed,
                        code="output_extraction_failed",
                        category="output_contract",
                    )
                return {
                    "status": "success",
                    "category": "success",
                    "code": "completed",
                    "message": "The success checkpoint was observed.",
                    "outputs": outputs,
                    "step_number": step_number or len(artifact.get("steps", [])),
                    "action": "success_check",
                    "expected": check,
                    "observed": self._compact_observation(observed),
                }

        return self._failure_result(
            RuntimeError("The success checkpoint was not observed."),
            artifact,
            step_number=step_number or len(artifact.get("steps", [])),
            action="success_check",
            expected=check,
            observed=observed,
            code="success_condition_not_met",
            category="checkpoint_failure",
        )

    def extract_outputs(self, artifact: dict) -> dict:
        """Extract declared outputs from the current surface state.

        Output declarations are metadata in the artifact. They may use the
        full page text, the current URL/title, or a target locator supplied by
        the surface adapter. Sensitive values should not be declared here.
        """
        outputs = {}

        for name, declaration in artifact.get("outputs", {}).items():
            strategy = declaration.get("strategy")

            if strategy == "text":
                observed = self.surface.observe()
                value = self._extract_text_value(
                    observed.get("visible_text", ""),
                    declaration,
                )
            elif strategy in {"url", "title"}:
                observed = self.surface.observe()
                value = observed.get(strategy)
            elif strategy == "success_check":
                value = artifact["success_check"]["value"]
            elif strategy == "target_text":
                value = self.surface.read_text(
                    declaration["target"]
                )
            else:
                raise ValueError(
                    f"Unsupported output strategy: {strategy}"
                )
            outputs[name] = self._coerce_output_value(
                name,
                value,
                declaration,
            )

        return outputs

    @staticmethod
    def _coerce_output_value(name: str, value, declaration: dict):
        if value is None:
            if declaration.get("required", True):
                raise ValueError(f"Required output was not extracted: {name}")
            return None

        expected_type = declaration["type"]
        try:
            if expected_type == "string":
                return str(value)
            if expected_type == "integer":
                if isinstance(value, bool):
                    raise ValueError("boolean is not an integer output")
                return int(str(value).strip().replace(",", ""))
            if expected_type == "number":
                if isinstance(value, bool):
                    raise ValueError("boolean is not a number output")
                return float(str(value).strip().replace(",", ""))
            if expected_type == "boolean":
                if isinstance(value, bool):
                    return value
                normalized = str(value).strip().casefold()
                if normalized in {"true", "yes", "1"}:
                    return True
                if normalized in {"false", "no", "0"}:
                    return False
                raise ValueError("value is not a boolean")
        except (TypeError, ValueError) as error:
            raise ValueError(
                f"Could not extract output {name!r} as {expected_type}: {value!r}"
            ) from error

        raise ValueError(f"Unsupported output type for {name}: {expected_type}")

    @staticmethod
    def _extract_text_value(visible_text: str, declaration: dict):
        expected = declaration.get("value")
        if expected and expected in visible_text:
            return expected

        if declaration.get("required", True):
            raise ValueError(
                f"Expected output text was not observed: {expected}"
            )

        return None

    def request_human_review(self, reason: str):
        if self.chatbot is None:
            print("chatbot is none")
            return {
                "status": "blocked",
                "code": "human_review_unavailable",
            }

        response = self.chatbot.return_next_action(
            reason,
            human_review_mode=True,
            requires_input=False,
        )

        decision = str(response).strip().lower()

        if decision in {"complete", "proceed", "approved"}:
            return None

        return {
            "status": "blocked",
            "code": "human_review_declined",
            "response": decision,
        }

    def _request_intervention(
            self,
            artifact: dict,
            step: dict,
            step_number: int,
            reason: str,
    ):
        try:
            observed = self.surface.observe()
            current_state = {
                "url": observed.get("url"),
                "title": observed.get("title"),
            }
        except Exception as error:
            current_state = {"observation_error": str(error)}

        context = {
            "capability_or_goal": artifact.get("goal", artifact.get("workflow_id")),
            "current_step_number": step_number,
            "current_step": step,
            "current_state": current_state,
            "why_stopped": reason,
        }
        if self.chatbot is None:
            if self.recorder is not None:
                self.recorder.record_handoff(reason=reason, **context)
            return {
                "status": "blocked",
                "code": "human_review_unavailable",
                "reason": reason,
                "context": context,
            }

        response = self.chatbot.request_intervention(reason, context)
        decision = str(response).strip().lower()
        if decision in {"complete", "proceed", "approved"}:
            return None

        return {
            "status": "blocked",
            "code": "human_review_declined",
            "response": decision,
            "reason": reason,
            "context": context,
        }

    