from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
from pathlib import Path
from selenium.common.exceptions import WebDriverException

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

from src.Chatbot import ChatBot
from src.ReplayEngine import ReplayEngine
from src.RunRecorder import report_generator
from src.SafetyPolicy import SafetyPolicy
from src.SurfaceAdapter import SurfaceAdapter
from src.artifact_schema import validate_artifact
from src.browser_factory import create_driver


STARTUP_URL = "https://parabank.parasoft.com/parabank/index.htm"


def _read_artifact(path: Path) -> dict:
    with path.open(encoding="utf-8") as file:
        artifact = json.load(file)
    validate_artifact(artifact)
    return artifact


def _parse_value(raw_value: str, declaration: dict):
    expected_type = declaration.get("type", "string")
    if expected_type == "integer":
        return int(raw_value.strip().replace(",", ""))
    if expected_type == "number":
        return float(raw_value.strip().replace(",", ""))
    if expected_type == "boolean":
        normalized = raw_value.strip().casefold()
        if normalized not in {"true", "false", "yes", "no"}:
            raise ValueError("Enter true/false or yes/no.")
        return normalized in {"true", "yes"}
    return raw_value.strip()


def _input_definitions_for(artifact: dict) -> dict:
    with (PROJECT_ROOT / "config" / "inputs.json").open(encoding="utf-8") as file:
        configured = json.load(file).get("goals", {})
    workflows = (
        [configured]
        if isinstance(configured, dict) and "workflow_id" in configured
        else list(configured.values())
    )
    workflow = next(
        (
            item for item in workflows
            if item.get("workflow_id") == artifact.get("workflow_id")
        ),
        {},
    )
    return workflow.get("required_fields", {})


def _collect_parameters(artifact: dict) -> dict:
    declarations = dict(artifact.get("inputs", {}))
    input_definitions = _input_definitions_for(artifact)
    for name, declaration in list(declarations.items()):
        if isinstance(declaration, dict):
            continue
        definition = next(
            (
                item for item in input_definitions.values()
                if isinstance(item, dict)
                and str(item.get("variable", "")).strip().strip("{}").strip() == name
            ),
            None,
        )
        if definition is None:
            raise ValueError(
                f"Artifact input declaration for {name!r} is redacted and "
                "cannot be restored from config/inputs.json. Regenerate the artifact."
            )
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
        input_type = type_aliases.get(
            str(definition.get("expected_input_type", "")).casefold()
        )
        if input_type is None:
            raise ValueError(f"No supported input type is configured for {name!r}.")
        declarations[name] = {
            "type": input_type,
            "description": definition.get("description", name.replace("_", " ")),
            "required": definition.get("required", True),
            "sensitive": True,
        }

    for name in artifact.get("required_parameters", []):
        declarations.setdefault(name, {
            "type": "integer" if "amount" in name.casefold() else "string",
            "description": name.replace("_", " "),
            "required": True,
            "sensitive": True,
        })

    supplied = {}
    for name, declaration in declarations.items():
        display_name = name.strip("{}").replace("_", " ")
        while True:
            prompt = f"{display_name} ({declaration['type']}): "
            raw_value = getpass.getpass(prompt)
            if not raw_value and not declaration.get("required", True):
                break
            try:
                input_name = name.strip("{}").strip()
                supplied["{{" + input_name + "}}"] = _parse_value(
                    raw_value,
                    declaration,
                )
                break
            except ValueError as error:
                print(f"Invalid value: {error}")
    return {
        "required_fields": supplied,
        "input_definitions": input_definitions,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Replay a saved browser workflow artifact."
    )
    parser.add_argument("artifact", type=Path, help="Path to a .artifact.json file.")
    args = parser.parse_args()
    artifact_path = args.artifact.resolve()
    artifact = _read_artifact(artifact_path)
    parameters = _collect_parameters(artifact)

    paths = json.loads(
        (PROJECT_ROOT / "config" / "paths.json").read_text(encoding="utf-8")
    )
    recorder = report_generator()
    driver = create_driver(paths["registry_path"])
    try:
        try:
            driver.get(STARTUP_URL)
        except WebDriverException as error:
            evidence = {}
            try:
                evidence["screenshot"] = str(
                    recorder.capture_screenshot(driver, name="startup_failure")
                )
            except Exception as screenshot_error:
                evidence["screenshot_error"] = str(screenshot_error)
            result = {
                "status": "failure",
                "category": "load_failure",
                "code": "startup_navigation_failed",
                "message": str(error),
                "expected": STARTUP_URL,
                "observed": {"url": driver.current_url},
                "evidence": evidence,
            }
            recorder.record_result(
                result["status"],
                **{key: value for key, value in result.items() if key != "status"},
            )
            print(json.dumps(result, indent=2, ensure_ascii=True, default=str))
            return 1
        chatbot = ChatBot(driver=driver, report=recorder)
        chatbot.show_runtime_controls()
        engine = ReplayEngine(
            surface=SurfaceAdapter(driver),
            policy=SafetyPolicy(),
            recorder=recorder,
            chatbot=chatbot,
        )
        result = engine.run(artifact, parameters)
        print(json.dumps(result, indent=2, ensure_ascii=True, default=str))
        if result.get("status") == "success":
            return 0
        if result.get("status") == "business_outcome":
            return 2
        return 1
    finally:
        try:
            driver.quit()
        except WebDriverException:
            pass


if __name__ == "__main__":
    raise SystemExit(main())