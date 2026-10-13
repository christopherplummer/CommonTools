import hmac
import secrets
import time

from web_tools.common.errors import ToolError


class InteractionPolicy:
    """Single-use, short-lived grants issued through a separate human-only credential."""

    def __init__(self, settings):
        self.human_key = settings.human_approval_key
        self.grants: dict[str, tuple] = {}

    def approve(self, human_key: str, action: str, session_id: str, ref: str, text: str | None):
        if not self.human_key or not hmac.compare_digest(
            human_key, self.human_key.get_secret_value()
        ):
            raise ToolError(
                "unauthorized_approval", "Human approval credential required", status=403
            )
        self.grants = {
            key: grant for key, grant in self.grants.items() if grant[-1] > time.monotonic()
        }
        if len(self.grants) >= 100:
            raise ToolError("approval_limit", "Too many pending approvals")
        token = secrets.token_urlsafe(32)
        self.grants[token] = (action, session_id, ref, text, time.monotonic() + 60)
        return {
            "approval_token": token,
            "expires_in_seconds": 60,
            "action": action,
            "session_id": session_id,
            "ref": ref,
        }

    def require(
        self, token: str | None, action: str, session_id: str, ref: str, text: str | None = None
    ):
        grant = self.grants.pop(token or "", None)
        if (
            not grant
            or grant[:4] != (action, session_id, ref, text)
            or grant[-1] < time.monotonic()
        ):
            raise ToolError(
                "approval_required",
                "A human must approve this exact action at "
                "POST /api/approvals. Obtain a fresh snapshot first.",
                next_operation="browser_snapshot",
                status=403,
            )
