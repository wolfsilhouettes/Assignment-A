from __future__ import annotations

import re
from typing import TypedDict


ALLOWED_ACTIONS = {
    "navigate",
    "navigate to",
    "click",
    "input",
    "select",
    "wait_for_element",
    "verify",
    "human_review",
}


class ArtifactValidationError(ValueError):
    """Raised when a reusable workflow artifact is malformed."""


class WorkflowTarget(TypedDict, total=False):
    selector: str
    element_name: str
    purpose: str
    strategy: str
    value: str
    timeout_seconds: int
    locator_strategy: str
    robustness: str


class WorkflowStep(TypedDict, total=False):
    action: str
    target: WorkflowTarget
    value: str
    reason: str
    timeout_seconds: int


class WorkflowArtifact(TypedDict, total=False):
    artifact_type: str
    version: str
    workflow_id: str
    goal: str
    required_parameters: list[str]
    inputs: dict
    steps: list[WorkflowStep]
    success_check: dict
    outputs: dict
    output_schema: dict
    business_outcomes: list[dict]


def validate_artifact(artifact: dict) -> None:
    if not isinstance(artifact, dict):
        raise ArtifactValidationError("Workflow artifact must be an object")
    if artifact.get("artifact_type") != "browser_workflow":
        raise ArtifactValidationError("Unsupported workflow artifact type")
    if not isinstance(artifact.get("version"), str) or not artifact["version"].strip():
        raise ArtifactValidationError("Workflow artifact version is required")
    if not isinstance(artifact.get("steps"), list) or not artifact["steps"]:
        raise ArtifactValidationError("Workflow artifact steps must be a non-empty list")
    if not isinstance(artifact.get("success_check"), dict):
        raise ArtifactValidationError("Workflow artifact success_check is required")
    is_complete_contract = artifact.get("version") == "1.1"

    inputs = artifact.get("inputs", {})
    if not isinstance(inputs, dict):
        raise ArtifactValidationError("Artifact inputs must be an object")
    for name, declaration in inputs.items():
        if not isinstance(name, str) or not isinstance(declaration, dict):
            raise ArtifactValidationError("Each input declaration must be an object")
        if declaration.get("type") not in {"string", "integer", "number", "boolean"}:
            raise ArtifactValidationError(
                f"Unsupported input type for {name}: {declaration.get('type')}"
            )
        if not isinstance(declaration.get("required", True), bool):
            raise ArtifactValidationError(f"Input required flag must be boolean: {name}")

    if is_complete_contract:
        required_parameters = artifact.get("required_parameters")
        if not isinstance(required_parameters, list) or any(
                not isinstance(name, str) for name in required_parameters
        ):
            raise ArtifactValidationError(
                "Version 1.1 artifacts require a list of required_parameters"
            )
        if len(required_parameters) != len(set(required_parameters)):
            raise ArtifactValidationError("required_parameters must not contain duplicates")
        required_input_names = {
            name for name, declaration in inputs.items()
            if declaration.get("required", True)
        }
        if set(required_parameters) != required_input_names:
            raise ArtifactValidationError(
                "required_parameters must match the required artifact inputs"
            )
        for name, declaration in inputs.items():
            if not isinstance(declaration.get("description"), str) or not declaration["description"].strip():
                raise ArtifactValidationError(
                    f"Version 1.1 input description is required: {name}"
                )
            if not isinstance(declaration.get("sensitive"), bool):
                raise ArtifactValidationError(
                    f"Version 1.1 input sensitivity must be boolean: {name}"
                )

    for index, step in enumerate(artifact["steps"]):
        _validate_step(step, index, require_target_rationale=is_complete_contract)
        if is_complete_contract and step.get("action") in {"input", "select"}:
            value = step.get("value")
            if isinstance(value, str) and value.startswith("{{"):
                match = re.fullmatch(r"\{\{\s*([A-Za-z_][\w]*)\s*\}\}", value)
                if not match or match.group(1) not in inputs:
                    raise ArtifactValidationError(
                        f"Step {index} references an undeclared input: {value}"
                    )

    success_check = artifact["success_check"]
    if success_check.get("strategy") != "text":
        raise ArtifactValidationError("Only text success checks are supported")
    if not isinstance(success_check.get("value"), str) or not success_check["value"].strip():
        raise ArtifactValidationError("success_check.value is required")

    outputs = artifact.get("outputs", {})
    if not isinstance(outputs, dict):
        raise ArtifactValidationError("Artifact outputs must be an object")
    for name, declaration in outputs.items():
        if not isinstance(name, str) or not isinstance(declaration, dict):
            raise ArtifactValidationError("Each output declaration must be an object")
        if declaration.get("strategy") not in {"text", "url", "title", "target_text", "success_check"}:
            raise ArtifactValidationError(
                f"Unsupported output strategy for {name}: {declaration.get('strategy')}"
            )
        if declaration.get("type") not in {"string", "integer", "number", "boolean"}:
            raise ArtifactValidationError(f"Unsupported output type for {name}")
        if not isinstance(declaration.get("required", True), bool):
            raise ArtifactValidationError(f"Output required flag must be boolean: {name}")
        if (
                declaration.get("strategy") == "text"
                and not isinstance(declaration.get("value"), str)
        ):
            raise ArtifactValidationError(
                f"Text output requires a matching value: {name}"
            )
        if declaration.get("strategy") == "target_text" and not isinstance(
                declaration.get("target"), dict
        ):
            raise ArtifactValidationError(
                f"Target-text output requires a target locator: {name}"
            )

    business_outcomes = artifact.get("business_outcomes", [])
    if not isinstance(business_outcomes, list):
        raise ArtifactValidationError("business_outcomes must be a list")
    for index, outcome in enumerate(business_outcomes):
        if not isinstance(outcome, dict):
            raise ArtifactValidationError(
                f"Business outcome {index} must be an object"
            )
        if not isinstance(outcome.get("code"), str) or not outcome["code"].strip():
            raise ArtifactValidationError(
                f"Business outcome {index} requires a code"
            )
        if outcome.get("strategy") != "text":
            raise ArtifactValidationError(
                f"Business outcome {index} only supports text matching"
            )
        if not isinstance(outcome.get("value"), str) or not outcome["value"].strip():
            raise ArtifactValidationError(
                f"Business outcome {index} requires a matching value"
            )
        if not isinstance(outcome.get("description"), str) or not outcome["description"].strip():
            raise ArtifactValidationError(
                f"Business outcome {index} requires a description"
            )

    if is_complete_contract:
        if not outputs:
            raise ArtifactValidationError("Version 1.1 artifacts require at least one output")
        output_schema = artifact.get("output_schema")
        if not isinstance(output_schema, dict) or output_schema.get("type") != "object":
            raise ArtifactValidationError(
                "Version 1.1 artifacts require an object output_schema"
            )
        if output_schema.get("additionalProperties") is not False:
            raise ArtifactValidationError(
                "output_schema.additionalProperties must be false"
            )
        properties = output_schema.get("properties")
        if not isinstance(properties, dict) or set(properties) != set(outputs):
            raise ArtifactValidationError(
                "output_schema.properties must match the declared outputs"
            )
        required_outputs = output_schema.get("required")
        if not isinstance(required_outputs, list) or any(
                name not in outputs for name in required_outputs
        ):
            raise ArtifactValidationError("output_schema.required must list declared outputs")
        if set(required_outputs) != {
                name for name, declaration in outputs.items()
                if declaration.get("required", True)
        }:
            raise ArtifactValidationError(
                "output_schema.required must match output declarations"
            )
        for name, declaration in outputs.items():
            if not isinstance(declaration.get("description"), str) or not declaration["description"].strip():
                raise ArtifactValidationError(
                    f"Version 1.1 output description is required: {name}"
                )
            if not isinstance(declaration.get("sensitive"), bool):
                raise ArtifactValidationError(
                    f"Version 1.1 output sensitivity must be boolean: {name}"
                )
            if properties[name] != {"type": declaration["type"]}:
                raise ArtifactValidationError(
                    f"Output shape does not match declared type for {name}"
                )


def _validate_step(
    step: dict,
    index: int,
    require_target_rationale: bool = False,
) -> None:
    if not isinstance(step, dict):
        raise ArtifactValidationError(f"Step {index} must be an object")

    action = step.get("action")
    if action not in ALLOWED_ACTIONS:
        raise ArtifactValidationError(f"Step {index} has unsupported action: {action}")

    if action == "human_review":
        if not isinstance(step.get("reason"), str) or not step["reason"].strip():
            raise ArtifactValidationError(f"Step {index} human_review.reason is required")
        return

    target = step.get("target")
    if not isinstance(target, dict):
        raise ArtifactValidationError(f"Step {index} target is required")
    is_navigation = action in {"navigate", "navigate to"}
    has_locator = any(
        target.get(key)
        for key in ("selector", "element_name", "purpose", "strategy")
    )
    if not has_locator and not (is_navigation and target.get("value")):
        raise ArtifactValidationError(f"Step {index} target has no usable locator")
    if require_target_rationale:
        if not isinstance(target.get("locator_strategy"), str) or not target["locator_strategy"].strip():
            raise ArtifactValidationError(
                f"Step {index} target.locator_strategy is required"
            )
        if not isinstance(target.get("robustness"), str) or not target["robustness"].strip():
            raise ArtifactValidationError(
                f"Step {index} target.robustness is required"
            )
        if action in {"click", "input", "select", "wait_for_element"} and not any(
                target.get(key) for key in ("selector", "element_name", "purpose")
        ):
            raise ArtifactValidationError(
                f"Step {index} requires a selector, element_name, or semantic purpose"
            )
        if action == "verify" and not target.get("strategy"):
            raise ArtifactValidationError(
                f"Step {index} verify action requires a verification strategy"
            )

    if action in {"input", "select"} and "value" not in step:
        raise ArtifactValidationError(f"Step {index} {action} action requires a value")

    if action in {"navigate", "navigate to"}:
        url = target.get("value")
        if not isinstance(url, str) or not url.startswith("https://"):
            raise ArtifactValidationError(f"Step {index} navigation target must be HTTPS")
