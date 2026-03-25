"""Shared fixtures for hpn_cli tests."""

import os

import pytest
import responses


@pytest.fixture
def tmp_config_dir(tmp_path, monkeypatch):
    """Temp directory for ~/.hpn/config.json — patches CONFIG_DIR/CONFIG_FILE."""
    config_dir = str(tmp_path / ".hpn")
    config_file = os.path.join(config_dir, "config.json")
    update_check_file = os.path.join(config_dir, "update_check.json")
    monkeypatch.setattr("hpn_cli.cli.CONFIG_DIR", config_dir)
    monkeypatch.setattr("hpn_cli.cli.CONFIG_FILE", config_file)
    monkeypatch.setattr("hpn_cli.cli.UPDATE_CHECK_FILE", update_check_file)
    # Also suppress update checks in tests
    monkeypatch.setattr("hpn_cli.cli.check_for_updates", lambda: None)
    # Clear env vars that could leak into tests
    monkeypatch.delenv("HPN_API_KEY", raising=False)
    monkeypatch.delenv("HPN_API_URL", raising=False)
    return config_dir


@pytest.fixture
def mock_api():
    """responses library fixture that intercepts HTTP to api.happenstance.ai."""
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        yield rsps


@pytest.fixture
def sample_api_key():
    """A test API key string."""
    return "hpn_test_key_abcdef1234567890"
