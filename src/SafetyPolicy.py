from __future__ import annotations
from urllib.parse import parse_qs, urlparse


class SafetyPolicy:
    def __init__(self):
        self.allowed_actions = {
            "navigate to",
            "click",
            "input",
            "select",
            "wait_for_element",
            "verify",
            "human_review",
            "success_check"
        }

        self.risky_actions = {
            "submit_transfer",
            "delete",
            "create account"
        }

        self.allowed_hosts = {
            "parabank.parasoft.com"
        }

    def validate_action(
            self,
            step: dict,
            human_approved: bool = False,
    ) -> None:
        action = step.get("action")

        if action not in self.allowed_actions:
            raise PermissionError(
                f"Action is not allowed: {action}"
            )

        if action in self.risky_actions and not human_approved:
            raise PermissionError(
                f"Human approval is required for {action}"
            )

    def validate_step(self, step: dict, human_approved: bool = False) -> None:
        """Validate a replay step using the same allowlist as discovery."""
        action = step.get("action")
        self.validate_action(step, human_approved=human_approved)

        if self._is_administrator_target(step.get("target", {})):
            raise PermissionError("Administrator navigation is not allowed")

        if self._is_submission_target(step.get("target", {})) and not human_approved:
            raise PermissionError("Human approval is required before submission")

        if action in {"input", "select"} and self._is_sensitive_target(step.get("target", {})):
            raise PermissionError("Credential or secret input is not permitted")

    @staticmethod
    def _is_administrator_target(target: dict) -> bool:
        target_text = " ".join(
            str(target.get(key, "")).lower()
            for key in ("selector", "purpose", "value", "element_text")
        )
        return any(
            phrase in target_text
            for phrase in ("administrator", "admin panel", "admin-panel", "/admin")
        )

    @staticmethod
    def _is_submission_target(target: dict) -> bool:
        target_text = " ".join(
            str(target.get(key, "")).lower()
            for key in ("selector", "purpose", "value", "element_text")
        )
        return any(
            phrase in target_text
            for phrase in ("submit", "confirm transfer", "complete the transfer")
        )

    @staticmethod
    def _is_sensitive_target(target: dict) -> bool:
        target_text = " ".join(
            str(target.get(key, "")).lower()
            for key in ("selector", "element_name", "purpose", "value")
        )
        return any(
            phrase in target_text
            for phrase in ("password", "passcode", "token", "secret", "api key", "credential")
        )

    def validate_url(self, url: str) -> None:
        parsed = urlparse(url)

        if parsed.scheme != "https":
            raise PermissionError("Only HTTPS URLs are allowed")

        if parsed.hostname not in self.allowed_hosts:
            raise PermissionError(
                f"Host is not allowed: {parsed.hostname}"
            )

        query_keys = {key.lower() for key in parse_qs(parsed.query)}
        if query_keys.intersection({"password", "token", "secret", "api_key", "authorization"}):
            raise PermissionError("Sensitive data is not allowed in navigation URLs")