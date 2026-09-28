from datetime import datetime, timezone
import json
import re
from pathlib import Path
from uuid import uuid4
from src.artifact_schema import validate_artifact


_MASK_SCREENSHOT_SCRIPT = """
const token = arguments[0];
const className = "run-recorder-redacted-" + token;
const styleId = "run-recorder-redaction-style-" + token;
const style = document.createElement("style");
style.id = styleId;
style.textContent = `.${className} {
    color: transparent !important;
    text-shadow: none !important;
    filter: blur(8px) !important;
    background-color: #222 !important;
    background-image: none !important;
}`;
const sensitiveHint = /account|balance|amount|member|customer|payment|card|routing|iban|swift|ssn|tax.?id|credential|password|secret|token/i;
const financialValue = /(?:\\$\\s*\\d[\\d,]*(?:\\.\\d{2})?|(?<!\\w)\\d{5,}(?!\\w)|\\b[A-Z]{2,}\\d{4,}\\b)/i;
const changed = [];

try {
    document.head.appendChild(style);
    const elements = Array.from(document.querySelectorAll("body *"));
    for (const element of elements) {
        const tag = element.tagName.toLowerCase();
        const editable = ["input", "textarea", "select"].includes(tag)
            || element.isContentEditable;
        const hints = [
            element.id,
            element.getAttribute("name"),
            element.getAttribute("aria-label"),
            element.getAttribute("autocomplete"),
            element.getAttribute("placeholder"),
            element.getAttribute("data-testid"),
            element.className,
        ].map(value => typeof value === "string" ? value : "").join(" ");
        const leafText = element.children.length === 0
            ? (element.innerText || element.textContent || "").trim()
            : "";
        const shouldMask = editable
            || sensitiveHint.test(hints)
            || (leafText && financialValue.test(leafText));

        if (!shouldMask || element.classList.contains(className)) {
            continue;
        }

        changed.push([element, element.getAttribute("class")]);
        element.classList.add(className);
    }

    window[token] = { changed, styleId };
    return changed.length;
} catch (error) {
    for (const [element, originalClass] of changed) {
        if (originalClass === null) {
            element.removeAttribute("class");
        } else {
            element.setAttribute("class", originalClass);
        }
    }
    style.remove();
    delete window[token];
    throw error;
}
"""

_RESTORE_SCREENSHOT_SCRIPT = """
const token = arguments[0];
const state = window[token];
if (state) {
    const className = "run-recorder-redacted-" + token;
    for (const [element, originalClass] of state.changed) {
        if (originalClass === null) {
            element.removeAttribute("class");
        } else {
            element.setAttribute("class", originalClass);
        }
    }
    const style = document.getElementById(state.styleId);
    if (style) {
        style.remove();
    }
    delete window[token];
}
"""


class report_generator:
    def __init__(self, report_dir="reports", run_id=None):
        report_path = Path(report_dir)
        report_path.mkdir(parents=True, exist_ok=True)

        self.run_id = run_id or uuid4().hex
        self.path = report_path / f"run_{self.run_id}.jsonl"
        self.artifact_path = report_path / f"run_{self.run_id}.artifact.json"
        self.record_event("run_started")

    def write_artifact(self, artifact: dict) -> Path:
        """Persist the reusable workflow separately from the model transcript."""
        if not isinstance(artifact, dict):
            raise TypeError("artifact must be a dictionary")
        if artifact.get("version") != "1.1":
            raise ValueError("New workflow artifacts must use the complete 1.1 contract")
        validate_artifact(artifact)

        redacted_artifact = self.redact(artifact)
        redacted_artifact["inputs"] = {
            name: self.redact(declaration)
            for name, declaration in artifact.get("inputs", {}).items()
        }
        with self.artifact_path.open("w", encoding="utf-8") as file:
            json.dump(redacted_artifact, file, indent=2, ensure_ascii=True)
        self.record_event("artifact_saved", path=str(self.artifact_path))
        return self.artifact_path

    def record_event(self, event_type: str, **details) -> dict:
        event = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "run_id": self.run_id,
            "event": event_type,
            "details": self.redact(details),
        }

        with self.path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(event, ensure_ascii=True) + "\n")

        return event

    def write_to_report(self, message: str):
        try:
            parsed = json.loads(message)
        except (TypeError, json.JSONDecodeError):
            return self.record_event("message", message=message)

        if isinstance(parsed, dict) and "event" in parsed:
            event_type = parsed.pop("event")
            return self.record_event(event_type, **parsed)

        return self.record_event("message", message=parsed)

    def record_action(self, action: str, step_id=None, **details):
        return self.record_event(
            "action",
            action=action,
            step_id=step_id,
            **details,
        )

    def record_handoff(self, reason: str, step_id=None, **details):
        return self.record_event(
            "human_handoff",
            reason=reason,
            step_id=step_id,
            **details,
        )

    def record_result(self, status: str, **details):
        return self.record_event(
            "run_finished",
            status=status,
            **details,
        )

    def capture_screenshot(self, driver, name="failure"):
        screenshot_path = self.path.with_name(
            f"{self.path.stem}_{name}.png"
        )
        temporary_path = screenshot_path.with_name(
            f".{screenshot_path.stem}.{uuid4().hex}.tmp.png"
        )
        mask_token = f"__run_recorder_mask_{uuid4().hex}"
        masked_elements = driver.execute_script(
            _MASK_SCREENSHOT_SCRIPT,
            mask_token,
        )
        try:
            try:
                screenshot_saved = driver.save_screenshot(str(temporary_path))
                if screenshot_saved is False:
                    raise RuntimeError(
                        "WebDriver reported that screenshot capture failed"
                    )
            finally:
                driver.execute_script(_RESTORE_SCREENSHOT_SCRIPT, mask_token)
            temporary_path.replace(screenshot_path)
        except Exception:
            if temporary_path.exists():
                temporary_path.unlink()
            raise

        self.record_event(
            "evidence",
            evidence_type="screenshot",
            path=str(screenshot_path),
            redaction="dom_masked_before_capture",
            masked_element_count=masked_elements,
        )
        return screenshot_path

    @classmethod
    def redact(cls, value):
        sensitive_names = {
            "password",
            "token",
            "secret",
            "api_key",
            "authorization",
            "credentials",
            "account",
            "account_number",
            "from_account",
            "to_account",
            "member_id",
            "balance",
            "amount",
        }

        if isinstance(value, dict):
            redacted = {
                key: "[REDACTED]"
                if cls._is_sensitive_key(key, sensitive_names)
                else cls.redact(item)
                for key, item in value.items()
            }
            target_text = " ".join(
                str(value.get(key, "")).lower()
                for key in ("selector", "element_name", "purpose")
            )
            if (
                    "account" in target_text
                    or "fromaccount" in target_text
                    or "toaccount" in target_text
            ) and isinstance(value.get("value"), str):
                if re.fullmatch(r"\$?\d[\d,.-]*", value["value"].strip()):
                    redacted["value"] = "[REDACTED]"
            if (
                str(value.get("action", "")).lower() == "click"
                and isinstance(value.get("value"), str)
                and re.fullmatch(r"\$?\d[\d,.-]*", value["value"].strip())
            ):
                redacted["value"] = "[REDACTED]"
            if (
                str(value.get("action", "")).lower() in {"input", "select"}
                and isinstance(value.get("value"), str)
                and not value["value"].strip().startswith("{{")
            ):
                redacted["value"] = "[REDACTED]"
            return redacted

        if isinstance(value, list):
            return [cls.redact(item) for item in value]

        if isinstance(value, str):
            lowered = value.lower()
            if any(marker in lowered for marker in ("password=", "token=", "secret=")):
                return "[REDACTED]"

            # Remove regulated identifiers embedded in goals or locator descriptions.
            value = re.sub(
                r"(?i)(\b(?:account|member|balance|amount)\b(?:\s*(?:number|id))?\s*(?:of|is|=|:)?\s*|\b(?:from|to|transfer)(?:\s+of)?\s+)\$?\d[\d,.-]*",
                r"\1[REDACTED]",
                value,
            )

        return value

    @staticmethod
    def _is_sensitive_key(key, sensitive_names: set[str]) -> bool:
        normalized = str(key).lower().replace("-", "_")
        return normalized in sensitive_names or any(
            token in normalized
            for token in (
                "password",
                "credential",
                "account_number",
                "account_id",
                "member_id",
                "balance",
                "secret",
                "token",
                "authorization",
                "api_key",
            )
        )