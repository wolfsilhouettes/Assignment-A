import os
import json
from typing import Optional

from openai import OpenAI
from selenium.common.exceptions import (
    InvalidSessionIdException,
    NoSuchWindowException,
)

class DiscoveryAgent:
    def __init__(
            self,
            surface,
            policy,
            recorder,
            chatbot=None,
            client=None,
            model=None,
    ):
        self.surface = surface
        self.policy = policy
        self.recorder = recorder
        self.chatbot = chatbot
        self.model = model or os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
        self.client = client or OpenAI(
            api_key=os.environ["OPENAI_API_KEY"]
        )

    def ask_for_action(self, goal, observation, completed_steps):
        response = self.client.responses.create(
            model=self.model,
            input=[
                {
                    "role": "system",
                    "content": (
                        "Return exactly one browser action as JSON. "
                        "Never provide credentials. "
                        "Only use the allowed actions. "
                        "Return exactly one JSON object. "
                        'The action must be one of: "navigate to", "click", "input", '
                        '"select", "wait_for_element", "verify", "human_review", or "done". '
                        'For "navigate to", target must be '
                        '{"value":"https://parabank.parasoft.com"}. '
                        'Only navigate when observation.url is different from target.value. '
                        'If observation.url already matches the target, choose the next action. '
                        'For click/input/select, target must include a "purpose" string. '
                        'If login, credentials, or an unsafe action is required, return '
                        '{"action":"human_review", "reason":"..."}. '
                        'Never return input actions for usernames, passwords, tokens, or credentials. '
                        "Never use action names such as fill_form, submit_form, or login. "
                        "For a form, return separate input or select actions, one at a time."
                        "Source and destination account fields are dropdowns; use action \"select\", not \"input\". "
                        "After the user selects ""complete"", record the human_review as completed and continue with the next step. "
                        "Do not request the same human_review again when completed_steps contains result ""human_review_completed""."
                        "Normalize any inputs for symbolic characters."
                        "After navigation, use action \"verify\" with target.strategy \"verify_login\". "
                        "When returning done, include a text success_check and an outputs object. "
                        "Each output declaration must include type, strategy, and description; "
                        "use only text, url, title, target_text, or success_check strategies. "
                        "Text outputs must include an exact value to find, and target_text outputs must include a target locator. "
                        "When the workflow has legitimate non-success business results, include business_outcomes as entries with code, description, strategy='text', and exact value; otherwise return an empty list. "
                    )
                },
                {
                    "role": "user",
                    "content": json.dumps({
                        "goal": goal,
                        "observation": observation,
                        "completed_steps": completed_steps
                    })
                }
            ]
        )

        return json.loads(response.output_text)

    def run(
            self,
            goal: str,
            parameters: dict,
            max_steps: int = 20,
    ) -> dict:
        """Discover a workflow by asking the model for one action at a time."""
        #parameters = parameters or {}

        recorded_steps = []
        completed_steps = []
        configured_success_check = self._configured_success_check(parameters)

        if not self.surface.verify("verify_login", "whether logged in", "inspect"):
            review_result = self.request_human_review({
                "reason": "Please log in to ParaBank manually, then select complete so the transfer can continue.",
            })
            if review_result is not None:
                return review_result
            if not self.surface.verify("verify_login", "whether logged in", "inspect"):
                return {
                    "status": "blocked",
                    "code": "login_not_verified",
                    "message": "Login was not detected after human review.",
                }

        recorded_steps.append(self._recordable_step({
            "action": "verify",
            "target": {
                "strategy": "verify_login",
                "value": "whether logged in",
                "purpose": "confirm the user is logged in",
            },
        }, parameters))

        for step_number in range(1, max_steps + 1):
            if self.chatbot is not None:
                self.chatbot.wait_for_agent_control()
            observation = self.surface.observe()
            proposal = self.ask_for_action(
                goal,
                observation,
                completed_steps,
            )

            if proposal.get("done") is True:
                success_check = proposal.get("success_check") or configured_success_check
                if not success_check:
                    self._record_outcome("failure", code="missing_success_check")
                    return {
                        "status": "failure",
                        "code": "missing_success_check",
                    }

                if not self._verify_success_check(success_check):
                    self._record_outcome(
                        "failure",
                        code="success_condition_not_met",
                        expected=success_check.get("value"),
                    )
                    return {
                        "status": "failure",
                        "code": "success_condition_not_met",
                    }

                self._record_outcome("success", success_check=success_check)
                artifact_outputs = self._artifact_outputs(
                    proposal.get("outputs", {})
                )
                return {
                    "status": "success",
                    "artifact": self._finish_artifact({
                        "artifact_type": "browser_workflow",
                        "version": "1.1",
                        "workflow_id": proposal.get(
                            "workflow_id",
                            "discovered_workflow",
                        ),
                        "goal": goal,
                        "required_parameters": self._required_parameter_names(
                            parameters
                        ),
                        "inputs": self._artifact_inputs(parameters),
                        "steps": recorded_steps,
                        "success_check": success_check,
                        "outputs": artifact_outputs,
                        "output_schema": self._output_schema(artifact_outputs),
                        "business_outcomes": self._artifact_business_outcomes(
                            proposal.get("business_outcomes", [])
                        ),
                    }),
                }

            action = proposal.get("action")
            if action == "done":
                proposal["done"] = True
            if not action:
                return {
                    "status": "failure",
                    "code": "model_returned_no_action",
                }

            proposal = self._hydrate_action_value(proposal, parameters)
            self.policy.validate_action(proposal)
            try:
                action_result = self._execute_action(proposal)
            except (InvalidSessionIdException, NoSuchWindowException):
                raise
            except Exception as error:
                reason = f"{type(error).__name__}: {error}"
                intervention_result = self._request_intervention(
                    goal,
                    proposal,
                    step_number,
                    reason,
                    completed_steps,
                )
                if intervention_result is not None:
                    self._record_outcome(
                        "blocked",
                        code=intervention_result["code"],
                        reason=reason,
                    )
                    return intervention_result

                completed_steps.append({
                    "action": action,
                    "target": proposal.get("target"),
                    "result": "human_intervened_after_error",
                })
                continue
            if action_result is not None:
                if action_result.get("code") in {
                        "navigation_loop",
                        "administrator_navigation_rejected",
                }:
                    completed_steps.append({
                        "action": proposal.get("action"),
                        "target": proposal.get("target"),
                        "result": action_result.get("code"),
                    })
                    continue
                if action_result.get("status") in {"failure", "blocked"}:
                    reason = action_result.get(
                        "message",
                        action_result.get("code", "Action could not continue."),
                    )
                    intervention_result = self._request_intervention(
                        goal,
                        proposal,
                        step_number,
                        reason,
                        completed_steps,
                    )
                    if intervention_result is None:
                        completed_steps.append({
                            "action": action,
                            "target": proposal.get("target"),
                            "result": "human_intervened_after_block",
                        })
                        continue
                    self._record_outcome(
                        "blocked",
                        code=intervention_result["code"],
                        reason=reason,
                    )
                    return intervention_result
                return action_result

            if (
                    action == "click"
                    and self._is_transfer_submission_target(
                        proposal.get("target", {})
                    )
            ):
                success_check = configured_success_check or {
                    "strategy": "text",
                    "value": "Transfer Complete!",
                }
                if not self._verify_success_check(success_check):
                    self._record_outcome(
                        "failure",
                        code="success_condition_not_met",
                        expected=success_check.get("value"),
                    )
                    return {
                        "status": "failure",
                        "code": "success_condition_not_met",
                    }

                recorded_steps.append({
                    "action": "human_review",
                    "reason": "Please confirm the completed transfer details before submitting the transfer.",
                })
                recorded_step = self._recordable_step(proposal, parameters)
                recorded_steps.append(recorded_step)
                self._record_event(recorded_step)
                self._record_outcome("success", success_check=success_check)
                artifact_outputs = self._artifact_outputs({})
                return {
                    "status": "success",
                    "artifact": self._finish_artifact({
                        "artifact_type": "browser_workflow",
                        "version": "1.1",
                        "workflow_id": "transfer",
                        "goal": goal,
                        "required_parameters": self._required_parameter_names(
                            parameters
                        ),
                        "inputs": self._artifact_inputs(parameters),
                        "steps": recorded_steps,
                        "success_check": success_check,
                        "outputs": artifact_outputs,
                        "output_schema": self._output_schema(artifact_outputs),
                        "business_outcomes": [],
                    }),
                }

            recorded_step = self._recordable_step(proposal, parameters)
            recorded_steps.append(recorded_step)
            completed_steps.append({
                "action": action,
                "target": proposal.get("target"),
                "result": (
                    "human_review_completed"
                    if action == "human_review"
                    else "completed"
                ),
            })
            self._record_event(recorded_step)

        reason = f"Discovery stopped after reaching the {max_steps}-step limit."
        intervention_result = self._request_intervention(
            goal,
            {"action": "step_limit", "target": {}},
            max_steps,
            reason,
            completed_steps,
        )
        if intervention_result is not None:
            self._record_outcome(
                "blocked",
                code=intervention_result["code"],
                reason=reason,
            )
            return intervention_result

        self._record_outcome(
            "blocked",
            code="discovery_step_limit_exceeded",
            reason=reason,
        )
        return {
            "status": "failure",
            "code": "discovery_step_limit_exceeded",
            "steps_completed": len(recorded_steps),
        }

    def _request_intervention(
            self,
            goal: str,
            proposal: dict,
            step_number: int,
            reason: str,
            completed_steps: list,
    ) -> Optional[dict]:
        try:
            observed = self.surface.observe()
            current_state = {
                "url": observed.get("url"),
                "title": observed.get("title"),
            }
        except Exception as error:
            current_state = {"observation_error": str(error)}

        context = {
            "capability_or_goal": goal,
            "current_step_number": step_number,
            "current_step": {
                "action": proposal.get("action"),
                "target": proposal.get("target"),
            },
            "current_state": current_state,
            "completed_steps": len(completed_steps),
            "why_stopped": reason,
        }
        if self.chatbot is None:
            if self.recorder is not None:
                self.recorder.record_handoff(
                    reason=reason,
                    **context,
                )
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

    @staticmethod
    def _configured_success_check(parameters: dict) -> Optional[dict]:
        for step in parameters.get("steps", []):
            if step.get("action") == "success_check":
                target = step.get("target", {})
                return {
                    "strategy": target.get("strategy", "text"),
                    "value": target.get("value"),
                }
        return None

    @staticmethod
    def _artifact_inputs(parameters: dict) -> dict:
        declarations = {}
        definitions = parameters.get("input_definitions", {})
        supplied = parameters.get("required_fields", {})
        source_fields = definitions or supplied
        for name, field in source_fields.items():
            declaration = field if isinstance(field, dict) else {}
            parameter_name = str(declaration.get("variable", name))
            parameter_name = parameter_name.strip("{}").strip()
            supplied_value = supplied.get(
                declaration.get("variable", name),
                supplied.get(name),
            )
            expected_type = str(declaration.get("expected_input_type", "")).lower()
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
            input_type = type_aliases.get(expected_type)
            if input_type is None:
                if isinstance(supplied_value, bool):
                    input_type = "boolean"
                elif isinstance(supplied_value, int):
                    input_type = "integer"
                elif isinstance(supplied_value, float):
                    input_type = "number"
                else:
                    input_type = "string"
            declarations[parameter_name] = {
                "type": input_type,
                "description": declaration.get(
                    "description",
                    f"Invocation value for {parameter_name.replace('_', ' ')}.",
                ),
                "required": declaration.get("required", True),
                "sensitive": declaration.get("sensitive", True),
            }
        return declarations

    @classmethod
    def _required_parameter_names(cls, parameters: dict) -> list[str]:
        return sorted(
            name
            for name, declaration in cls._artifact_inputs(parameters).items()
            if declaration.get("required", True)
        )

    @staticmethod
    def _artifact_outputs(outputs: dict) -> dict:
        declared = dict(outputs or {})
        if not declared:
            declared["transfer_status"] = {
                "type": "string",
                "strategy": "success_check",
                "description": "Confirmation that the transfer completed.",
                "sensitive": False,
            }
        for name, source_declaration in list(declared.items()):
            if not isinstance(source_declaration, dict):
                raise ValueError(f"Output declaration must be an object: {name}")
            declaration = dict(source_declaration)
            declared[name] = declaration
            declaration.setdefault("type", "string")
            declaration.setdefault("strategy", "success_check")
            declaration.setdefault(
                "description",
                f"Extracted {str(name).replace('_', ' ')} from the completed workflow.",
            )
            declaration.setdefault("required", True)
            declaration.setdefault("sensitive", False)
        return declared

    @staticmethod
    def _output_schema(outputs: dict) -> dict:
        return {
            "type": "object",
            "properties": {
                name: {"type": declaration["type"]}
                for name, declaration in outputs.items()
            },
            "required": [
                name
                for name, declaration in outputs.items()
                if declaration.get("required", True)
            ],
            "additionalProperties": False,
        }

    @staticmethod
    def _artifact_business_outcomes(outcomes: list) -> list[dict]:
        if not isinstance(outcomes, list):
            raise ValueError("Business outcomes must be a list")
        return [
            {
                "code": outcome["code"],
                "description": outcome["description"],
                "strategy": outcome.get("strategy", "text"),
                "value": outcome["value"],
            }
            for outcome in outcomes
        ]

    def _verify_success_check(self, success_check: dict) -> bool:
        if success_check.get("strategy") != "text":
            return False
        return self.surface.wait_for_text(success_check.get("value", ""))

    def _record_outcome(self, status: str, **details) -> None:
        if self.recorder is not None:
            self.recorder.record_result(status, **details)

    @staticmethod
    def _hydrate_action_value(proposal: dict, parameters: dict) -> dict:
        target = proposal.get("target", {})
        selector = " ".join(
            str(target.get(key, "")).lower()
            for key in ("selector", "element_name")
        )
        purpose = str(target.get("purpose", "")).lower()
        if (
                "fromaccount" in selector
                or "from account" in purpose
                or "source account" in purpose
        ):
            parameter_name = "{{from_account}}"
        elif (
                "toaccount" in selector
                or "to account" in purpose
                or "destination account" in purpose
        ):
            parameter_name = "{{to_account}}"
        elif "amount" in selector or "amount" in purpose:
            parameter_name = "{{amount}}"
        else:
            if proposal.get("value") is not None or target.get("value") is not None:
                return proposal
            return proposal

        required_fields = parameters.get("required_fields", {})
        parameter_value = required_fields.get(parameter_name)
        if parameter_value is None:
            return proposal

        hydrated = dict(proposal)
        hydrated["value"] = parameter_value
        return hydrated

    def _execute_action(self, proposal: dict) -> Optional[dict]:
        action = proposal["action"]
        target = proposal.get("target", {})
        value = proposal.get("value")
        if value is None:
            value = target.get("value")

        if action in {"navigate", "navigate to"}:
            url = target.get("value")
            if not isinstance(url, str) or not url:
                raise ValueError(
                    "Invalid model action: navigation target must contain "
                    f"a URL in target.value; received {target!r}"
                )
            current_url = self.surface.observe().get("url", "")
            if current_url.rstrip("/") == url.rstrip("/"):
                return {
                    "status": "failure",
                    "code": "navigation_loop",
                    "message": f"Already at navigation target: {url}",
                }
            self.policy.validate_url(url)
            if self._is_administrator_target({"value": url}):
                return {
                    "status": "failure",
                    "code": "administrator_navigation_rejected",
                    "message": "Administrator navigation is not part of the requested workflow.",
                }
            if self.surface.navigate_to(url) is False:
                return {
                    "status": "failure",
                    "code": "navigation_failed",
                    "message": f"Could not navigate to: {url}",
                }
        elif action == "click":
            if self._is_administrator_target(target):
                return {
                    "status": "failure",
                    "code": "administrator_navigation_rejected",
                    "message": "Administrator navigation is not part of the requested workflow.",
                }
            if self._is_transfer_submission_target(target):
                review_result = self.request_human_review({
                    "reason": "Please confirm the completed transfer details before submitting the transfer.",
                })
                if review_result is not None:
                    return review_result
                self.surface.click(target)
            elif self._is_transfer_target(target):
                transfer_url = "https://parabank.parasoft.com/parabank/transfer.htm"
                current_url = self.surface.observe().get("url", "")
                if current_url.rstrip("/") != transfer_url.rstrip("/"):
                    self.policy.validate_url(transfer_url)
                    if self.surface.navigate_to(transfer_url) is False:
                        return {
                            "status": "failure",
                            "code": "navigation_failed",
                            "message": f"Could not navigate to: {transfer_url}",
                        }
            else:
                self.surface.click(target)
        elif action == "input":
            if self._is_account_target(target):
                self.surface.select(target, value)
            else:
                self.surface.input(target, value)
        elif action == "select":
            self.surface.select(target, value)
        elif action == "wait_for_element":
            self.surface.wait_for_purpose(
                target["purpose"],
                target.get("action", "inspect"),
                proposal.get("timeout_seconds", 10),
            )
        elif action == "verify":
            strategy = target.get("strategy", "verify_login")
            verified = self.surface.verify(
                strategy,
                value,
                target.get("action", "inspect"),
            )
            if strategy == "verify_login" and not verified:
                return self.request_human_review({
                    "reason": "Login is required before continuing. Please log in manually, then select complete.",
                })
        elif action == "human_review":
            result = self.request_human_review(proposal)
            if result is not None:
                return result
        else:
            raise ValueError(f"Unsupported discovery action: {action}")

        return None

    @staticmethod
    def _is_account_target(target: dict) -> bool:
        selector = str(target.get("selector", "")).lower()
        purpose = str(target.get("purpose", "")).lower()
        return (
            selector.startswith("select")
            or "from account" in purpose
            or "source account" in purpose
            or "to account" in purpose
            or "destination account" in purpose
        )

    @staticmethod
    def _is_administrator_target(target: dict) -> bool:
        target_text = " ".join(
            str(target.get(key, "")).lower()
            for key in ("selector", "purpose", "value")
        )
        return any(
            phrase in target_text
            for phrase in (
                "administrator",
                "admin panel",
                "admin-panel",
                "/admin",
            )
        )

    @staticmethod
    def _is_transfer_target(target: dict) -> bool:
        target_text = " ".join(
            str(target.get(key, "")).lower()
            for key in ("selector", "purpose", "value", "element_text")
        )
        return "transfer" in target_text

    @staticmethod
    def _is_transfer_submission_target(target: dict) -> bool:
        target_text = " ".join(
            str(target.get(key, "")).lower()
            for key in ("selector", "purpose", "value", "element_text")
        )
        return (
            "submit" in target_text
            or "complete the transfer" in target_text
            or "confirm transfer" in target_text
        )

    def request_human_review(self, proposal: dict):
        reason = proposal.get(
            "reason",
            "Manual intervention is required before discovery can continue.",
        )

        if self.chatbot is None:
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

    def _recordable_step(self, proposal: dict, parameters: dict) -> dict:
        step = {"action": proposal["action"]}

        if proposal.get("target") is not None:
            target = dict(proposal["target"])
            step["target"] = target
            if proposal["action"] in {"navigate", "navigate to"}:
                target["locator_strategy"] = "url"
                target["robustness"] = (
                    "The explicit HTTPS URL is stable and is validated against the host allowlist."
                )
            elif proposal["action"] == "verify":
                target["locator_strategy"] = "verification_strategy"
                target["robustness"] = (
                    "The named verification checks page state rather than relying on a single control locator."
                )
            elif target.get("selector") and target.get("purpose"):
                target["locator_strategy"] = "css_then_semantic"
                target["robustness"] = (
                    "Try the specific CSS selector first, then use the semantic purpose as a fallback if the selector is stale."
                )
            elif target.get("selector"):
                target["locator_strategy"] = "css"
                target["robustness"] = (
                    "Use the explicit CSS selector; without a semantic purpose, recovery from markup changes is limited."
                )
            elif target.get("element_name"):
                target["locator_strategy"] = "element_name_then_semantic"
                target["robustness"] = (
                    "Resolve the stable element id/name first and fall back to semantic matching when that lookup times out."
                )
            else:
                target["locator_strategy"] = "semantic"
                target["robustness"] = (
                    "Match the human-readable purpose so the target can survive selector and layout changes; ambiguous purposes may need refinement."
                )

        if (
            proposal.get("value") is not None
            and proposal.get("action") in {"input", "select", "navigate to", "navigate"}
        ):
            step["value"] = self._artifact_value(proposal, parameters)

        if proposal.get("timeout_seconds") is not None:
            step["timeout_seconds"] = proposal["timeout_seconds"]

        return step

    @staticmethod
    def _artifact_value(proposal: dict, parameters: dict):
        if proposal.get("action") not in {"input", "select"}:
            return proposal["value"]

        value = proposal.get("value")
        if isinstance(value, str) and value.startswith("{{"):
            return value

        target_text = " ".join(
            str(proposal.get("target", {}).get(key, "")).lower()
            for key in ("selector", "element_name", "purpose")
        )
        parameter_names = (
            ("from_account", "from account", "source account"),
            ("to_account", "to account", "destination account"),
            ("amount", "amount"),
        )
        available = parameters.get("required_fields", parameters)
        for parameter_name, *markers in parameter_names:
            if any(marker in target_text for marker in markers):
                if parameter_name in available or "{{" + parameter_name + "}}" in available:
                    return "{{" + parameter_name + "}}"

        definitions = parameters.get("input_definitions", {})
        normalized_target = target_text.replace("_", " ").casefold()
        for field_name, declaration in definitions.items():
            if not isinstance(declaration, dict):
                continue
            variable = str(declaration.get("variable", field_name))
            parameter_name = variable.strip("{}").strip()
            aliases = (str(field_name).replace("_", " "), parameter_name.replace("_", " "))
            if any(alias and alias.casefold() in normalized_target for alias in aliases):
                placeholder = "{{" + parameter_name + "}}"
                if placeholder in available or parameter_name in available:
                    return placeholder
        return proposal["value"]

    def _finish_artifact(self, artifact: dict) -> dict:
        if self.recorder is not None:
            self.recorder.write_artifact(artifact)
        return artifact

    def _record_event(self, step: dict) -> None:
        if self.recorder is not None:
            self.recorder.record_action(
                action=step["action"],
                target=step.get("target"),
                value=step.get("value"),
                timeout_seconds=step.get("timeout_seconds"),
            )