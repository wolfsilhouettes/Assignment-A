from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from types import SimpleNamespace

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

from src.DiscoveryAgent import DiscoveryAgent
from src.ReplayEngine import ReplayEngine
from src.RunRecorder import report_generator
from src.SafetyPolicy import SafetyPolicy


EVIDENCE_DIR = PROJECT_ROOT / "evidence"
DEMO_AMOUNT = 25
DEMO_FROM_ACCOUNT = "SIM00001"
DEMO_TO_ACCOUNT = "SIM00002"
UNKNOWN_ACCOUNT = "SIM99999"


class FakeResponses:
    def __init__(self, proposals):
        self.proposals = iter(proposals)

    def create(self, **kwargs):
        return SimpleNamespace(output_text=json.dumps(next(self.proposals)))


class FakeClient:
    def __init__(self, proposals):
        self.responses = FakeResponses(proposals)


class FakeSurface:
    def __init__(self):
        self.url = "https://parabank.parasoft.com/parabank/index.htm"
        self.title = "ParaBank | Welcome"
        self.visible_text = "Simulated ParaBank homepage"
        self.values = {}

    def verify(self, strategy, value, action):
        return True

    def observe(self):
        return {
            "url": self.url,
            "title": self.title,
            "visible_text": self.visible_text,
        }

    def navigate_to(self, url):
        self.url = url
        self.title = "Transfer Funds"
        self.visible_text = "Simulated transfer form"
        return True

    def input(self, target, value):
        self.values["amount"] = value

    def click(self, target):
        purpose = target.get("purpose", "").casefold()
        selector = target.get("selector", "").casefold()
        if "transfer.htm" in selector:
            self.navigate_to(
                "https://parabank.parasoft.com/parabank/transfer.htm"
            )
        elif "submit" in purpose or "submit" in selector:
            if self.values.get("to_account") == UNKNOWN_ACCOUNT:
                self.visible_text = "No such account"
            else:
                self.visible_text = "Transfer Complete!"

    def select(self, target, value):
        purpose = target.get("purpose", "").casefold()
        if "from" in purpose or "source" in purpose:
            self.values["from_account"] = value
        elif "to" in purpose or "destination" in purpose:
            self.values["to_account"] = value

    def wait_for_text(self, expected, timeout=15):
        return expected in self.visible_text

    def read_text(self, target):
        return "demo-result"


class FakeChatbot:
    def wait_for_agent_control(self):
        return None

    def return_next_action(self, *args, **kwargs):
        return "complete"


class FakeReplayPolicy(SafetyPolicy):
    def validate_url(self, url):
        return None


def _discovery_proposals() -> list[dict]:
    return [
        {
            "action": "click",
            "target": {
                "selector": "a[href*='transfer.htm']",
                "purpose": "open the transfer funds page",
            },
        },
        {
            "action": "input",
            "target": {
                "selector": "input[name='amount']",
                "purpose": "enter the transfer amount",
            },
            "value": "{{amount}}",
        },
        {
            "action": "select",
            "target": {
                "selector": "select[name='fromAccountId']",
                "purpose": "select the source account",
            },
            "value": "{{from_account}}",
        },
        {
            "action": "select",
            "target": {
                "selector": "select[name='toAccountId']",
                "purpose": "select the destination account",
            },
            "value": "{{to_account}}",
        },
        {
            "action": "click",
            "target": {
                "selector": "input[type='submit'][value='Transfer']",
                "purpose": "submit the transfer",
            },
        },
    ]


def _artifact_parameters() -> dict:
    return {
        "workflow_id": "transfer",
        "input_definitions": {
            "transfer": {
                "variable": "{{amount}}",
                "expected_input_type": "int",
                "description": "Synthetic transfer amount for offline evidence.",
            },
            "from": {
                "variable": "{{from_account}}",
                "expected_input_type": "variant",
                "description": "Synthetic source account identifier.",
            },
            "to": {
                "variable": "{{to_account}}",
                "expected_input_type": "variant",
                "description": "Synthetic destination account identifier.",
            },
        },
        "required_fields": {
            "{{amount}}": DEMO_AMOUNT,
            "{{from_account}}": DEMO_FROM_ACCOUNT,
            "{{to_account}}": DEMO_TO_ACCOUNT,
        },
        "steps": [{
            "action": "success_check",
            "target": {"strategy": "text", "value": "Transfer Complete!"},
        }],
    }


def _run_discovery(run_id: str) -> tuple[dict, report_generator]:
    recorder = report_generator(report_dir=str(EVIDENCE_DIR), run_id=run_id)
    agent = DiscoveryAgent(
        surface=FakeSurface(),
        policy=SafetyPolicy(),
        recorder=recorder,
        chatbot=FakeChatbot(),
        client=FakeClient(_discovery_proposals()),
    )
    result = agent.run(
        goal="transfer a synthetic amount between synthetic accounts",
        parameters=_artifact_parameters(),
    )
    if result.get("status") != "success":
        raise RuntimeError(f"Simulated discovery did not succeed: {result}")
    return result["artifact"], recorder


def _run_replay(
        artifact: dict,
        run_id: str,
        destination_account: str,
) -> tuple[dict, report_generator]:
    recorder = report_generator(report_dir=str(EVIDENCE_DIR), run_id=run_id)
    surface = FakeSurface()
    engine = ReplayEngine(
        surface=surface,
        policy=FakeReplayPolicy(),
        recorder=recorder,
        chatbot=FakeChatbot(),
    )
    result = engine.run(
        artifact,
        {"required_fields": {
            "{{amount}}": DEMO_AMOUNT,
            "{{from_account}}": DEMO_FROM_ACCOUNT,
            "{{to_account}}": destination_account,
        }},
    )
    return result, recorder


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate simulated transfer discovery and replay evidence without live services."
    )
    parser.add_argument(
        "--run-prefix",
        default="transfer-demo",
        help="Prefix for generated evidence files; must be unused.",
    )
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_-]+", args.run_prefix):
        parser.error("run-prefix may contain only letters, numbers, hyphens, and underscores")

    run_ids = {
        "discovery": f"{args.run_prefix}-discovery",
        "replay_success": f"{args.run_prefix}-replay-success",
        "replay_bad_account": f"{args.run_prefix}-replay-bad-account",
    }
    occupied = [
        EVIDENCE_DIR / f"run_{run_id}{suffix}"
        for run_id in run_ids.values()
        for suffix in (".jsonl", ".artifact.json")
        if (EVIDENCE_DIR / f"run_{run_id}{suffix}").exists()
    ]
    if occupied:
        parser.error(
            "Evidence run IDs already exist; choose another --run-prefix. "
            f"Existing output: {occupied[0].name}"
        )

    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    artifact, discovery_recorder = _run_discovery(run_ids["discovery"])
    success_result, success_recorder = _run_replay(
        artifact,
        run_ids["replay_success"],
        DEMO_TO_ACCOUNT,
    )
    bad_account_result, bad_account_recorder = _run_replay(
        artifact,
        run_ids["replay_bad_account"],
        UNKNOWN_ACCOUNT,
    )
    if success_result.get("status") != "success":
        raise RuntimeError(f"Simulated success replay did not succeed: {success_result}")
    if (
            bad_account_result.get("status") != "business_outcome"
            or bad_account_result.get("code") != "account_not_found"
    ):
        raise RuntimeError(
            f"Simulated invalid-account replay was not classified: {bad_account_result}"
        )

    print(json.dumps({
        "simulated": True,
        "artifact": str(discovery_recorder.artifact_path),
        "discovery_log": str(discovery_recorder.path),
        "success_replay_log": str(success_recorder.path),
        "bad_account_replay_log": str(bad_account_recorder.path),
        "success_replay": success_result["status"],
        "bad_account_replay": {
            "status": bad_account_result["status"],
            "code": bad_account_result["code"],
        },
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())