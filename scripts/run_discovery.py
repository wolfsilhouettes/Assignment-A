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
from src.DiscoveryAgent import DiscoveryAgent
from src.RunRecorder import report_generator
from src.SafetyPolicy import SafetyPolicy
from src.SurfaceAdapter import SurfaceAdapter
from src.browser_factory import create_driver


STARTUP_URL = "https://parabank.parasoft.com/parabank/index.htm"


def _read_workflows() -> dict:
    path = PROJECT_ROOT / "config" / "inputs.json"
    with path.open(encoding="utf-8") as file:
        configured = json.load(file).get("goals", {})
    if isinstance(configured, dict) and "workflow_id" in configured:
        return {configured["workflow_id"]: configured}
    return configured


def _parse_value(raw_value: str, declaration: dict):
    input_type = declaration.get("expected_input_type", "variant").lower()
    if input_type in {"int", "integer"}:
        cleaned = raw_value.strip().replace("$", "").replace(",", "")
        return int(cleaned)
    if input_type in {"number", "float"}:
        return float(raw_value.strip().replace(",", ""))
    if input_type in {"bool", "boolean"}:
        normalized = raw_value.strip().casefold()
        if normalized not in {"true", "false", "yes", "no"}:
            raise ValueError("Enter true/false or yes/no.")
        return normalized in {"true", "yes"}
    return raw_value.strip()


def _collect_inputs(definitions: dict) -> dict:
    supplied = {}
    for field_name, declaration in definitions.items():
        variable = declaration["variable"]
        label = field_name.replace("_", " ")
        while True:
            raw_value = getpass.getpass(f"{label} ({variable}): ")
            try:
                supplied[variable] = _parse_value(raw_value, declaration)
                break
            except ValueError as error:
                print(f"Invalid value: {error}")
    return supplied


def _goal_from_inputs(workflow_id: str, supplied: dict) -> str:
    if workflow_id == "transfer":
        amount = supplied["{{amount}}"]
        source = supplied["{{from_account}}"]
        destination = supplied["{{to_account}}"]
        return (
            f"transfer ${amount} from account {source} "
            f"to account {destination}"
        )
    return workflow_id + " " + " ".join(str(value) for value in supplied.values())


def main() -> int:
    workflows = _read_workflows()
    parser = argparse.ArgumentParser(
        description="Discover a configured browser workflow and save its artifact."
    )
    parser.add_argument(
        "--workflow",
        choices=sorted(workflows),
        default="transfer",
        help="Workflow key from config/inputs.json (default: transfer).",
    )
    parser.add_argument(
        "--run-id",
        default="demo-transfer",
        help="Artifact/report identifier. Use a new value for each run.",
    )
    args = parser.parse_args()

    if not os.environ.get("OPENAI_API_KEY"):
        parser.error("Set OPENAI_API_KEY in the current shell before discovery.")

    workflow = dict(workflows[args.workflow])
    definitions = workflow["required_fields"]
    supplied = _collect_inputs(definitions)
    workflow["input_definitions"] = definitions
    workflow["required_fields"] = supplied
    goal = _goal_from_inputs(args.workflow, supplied)

    recorder = report_generator(run_id=args.run_id)
    paths = json.loads(
        (PROJECT_ROOT / "config" / "paths.json").read_text(encoding="utf-8")
    )
    driver = create_driver(paths["registry_path"])
    try:
        try:
            driver.get(STARTUP_URL)
        except WebDriverException as error:
            recorder.record_event(
                "startup_navigation_failed",
                url=STARTUP_URL,
                error_type=type(error).__name__,
                error=str(error),
            )
            recorder.record_result(
                "failure",
                category="load_failure",
                code="startup_navigation_failed",
                expected=STARTUP_URL,
                error=str(error),
            )
            print(json.dumps({
                "status": "failure",
                "code": "startup_navigation_failed",
                "report_path": str(recorder.path),
            }, indent=2))
            return 1
        chatbot = ChatBot(driver=driver, report=recorder)
        chatbot.show_runtime_controls()
        agent = DiscoveryAgent(
            surface=SurfaceAdapter(driver),
            policy=SafetyPolicy(),
            recorder=recorder,
            chatbot=chatbot,
        )
        result = agent.run(goal=goal, parameters=workflow)
        artifact_path = (
            str(recorder.artifact_path)
            if recorder.artifact_path.exists()
            else None
        )
        print(json.dumps({
            "status": result.get("status"),
            "code": result.get("code"),
            "artifact_path": artifact_path,
            "report_path": str(recorder.path),
        }, indent=2))
        return 0 if result.get("status") == "success" else 1
    finally:
        try:
            driver.quit()
        except WebDriverException:
            pass


if __name__ == "__main__":
    raise SystemExit(main())