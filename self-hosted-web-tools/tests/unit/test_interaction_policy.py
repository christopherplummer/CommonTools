import pytest

from web_tools.common.errors import ToolError
from web_tools.security.interaction_policy import InteractionPolicy


def test_separate_credential_and_single_use_exact_grants(settings):
    policy = InteractionPolicy(settings)
    with pytest.raises(ToolError):
        policy.approve(settings.api_key.get_secret_value(), "browser_type", "s", "r", "text")
    token = policy.approve(
        settings.human_approval_key.get_secret_value(), "browser_type", "s", "r", "text"
    )["approval_token"]
    policy.require(token, "browser_type", "s", "r", "text")
    with pytest.raises(ToolError):
        policy.require(token, "browser_type", "s", "r", "text")
    token = policy.approve(
        settings.human_approval_key.get_secret_value(), "browser_type", "s", "r", "text"
    )["approval_token"]
    with pytest.raises(ToolError):
        policy.require(token, "browser_type", "s", "r", "different text")
