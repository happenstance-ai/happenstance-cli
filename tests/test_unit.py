"""Unit tests — pure logic, no HTTP."""

import json
import os
import time
from unittest.mock import MagicMock, patch


from hpn_cli import __version__
from hpn_cli.cli import (
    DEFAULT_BASE_URL,
    HpnClient,
    check_for_updates as _real_check_for_updates,
    load_config,
    resolve_config,
)

from .utils import run_cli


# ── Config ──────────────────────────────────────────────────────────────────


class TestLoadConfig:
    def test_missing_file(self, tmp_config_dir):
        assert load_config() == {}

    def test_empty_file(self, tmp_config_dir):
        os.makedirs(tmp_config_dir, exist_ok=True)
        with open(os.path.join(tmp_config_dir, "config.json"), "w") as f:
            json.dump({}, f)
        assert load_config() == {}

    def test_valid_file(self, tmp_config_dir):
        os.makedirs(tmp_config_dir, exist_ok=True)
        with open(os.path.join(tmp_config_dir, "config.json"), "w") as f:
            json.dump({"api_key": "my-key"}, f)
        assert load_config() == {"api_key": "my-key"}


class TestResolveConfig:
    def test_flag_overrides_all(self, tmp_config_dir, monkeypatch):
        os.makedirs(tmp_config_dir, exist_ok=True)
        with open(os.path.join(tmp_config_dir, "config.json"), "w") as f:
            json.dump({"api_key": "file-key"}, f)
        monkeypatch.setenv("HPN_API_KEY", "env-key")

        args = MagicMock(api_key="flag-key")
        api_key, base_url = resolve_config(args)
        assert api_key == "flag-key"
        assert base_url == DEFAULT_BASE_URL

    def test_env_overrides_file(self, tmp_config_dir, monkeypatch):
        os.makedirs(tmp_config_dir, exist_ok=True)
        with open(os.path.join(tmp_config_dir, "config.json"), "w") as f:
            json.dump({"api_key": "file-key"}, f)
        monkeypatch.setenv("HPN_API_KEY", "env-key")

        args = MagicMock(api_key=None)
        api_key, _ = resolve_config(args)
        assert api_key == "env-key"

    def test_file_fallback(self, tmp_config_dir):
        os.makedirs(tmp_config_dir, exist_ok=True)
        with open(os.path.join(tmp_config_dir, "config.json"), "w") as f:
            json.dump({"api_key": "file-key"}, f)

        args = MagicMock(api_key=None)
        api_key, _ = resolve_config(args)
        assert api_key == "file-key"

    def test_no_key_returns_none(self, tmp_config_dir):
        args = MagicMock(api_key=None)
        api_key, _ = resolve_config(args)
        assert api_key is None

    def test_env_base_url(self, tmp_config_dir, monkeypatch):
        monkeypatch.setenv("HPN_API_URL", "https://custom.api.example.com")
        args = MagicMock(api_key=None)
        _, base_url = resolve_config(args)
        assert base_url == "https://custom.api.example.com"


# ── Argument parsing ──────────────────────────────────────────────────────


class TestArgParsing:
    def test_version_flag(self, tmp_config_dir):
        code, out, err = run_cli("--version")
        assert __version__ in (out + err)

    def test_help_flag(self, tmp_config_dir):
        code, out, err = run_cli("--help")
        assert "Happenstance CLI" in out

    def test_no_args_shows_help(self, tmp_config_dir):
        code, out, err = run_cli()
        assert "Commands" in out

    def test_search_help(self, tmp_config_dir):
        code, out, err = run_cli("search", "--help")
        assert "Search across your connections" in out
        assert "Credits:" in out
        assert "402" in out

    def test_research_help(self, tmp_config_dir):
        code, out, err = run_cli("research", "--help")
        assert "Research a specific person" in out
        assert "Credits:" in out
        assert "Tips:" in out

    def test_groups_help(self, tmp_config_dir):
        code, out, err = run_cli("groups", "--help")
        assert "hpn search --groups" in out

    def test_usage_help(self, tmp_config_dir):
        code, out, err = run_cli("usage", "--help")
        assert "credit balance" in out

    def test_friends_help(self, tmp_config_dir):
        code, out, err = run_cli("friends", "--help")
        assert "@<Full Name>" in out


# ── HpnClient ─────────────────────────────────────────────────────────────


class TestHpnClient:
    def test_should_retry_429(self):
        assert HpnClient._should_retry(429, 0) is True
        assert HpnClient._should_retry(429, 100) is True

    def test_should_retry_5xx(self):
        assert HpnClient._should_retry(502, 0) is True
        assert HpnClient._should_retry(503, 4) is True
        assert HpnClient._should_retry(504, 5) is False

    def test_should_not_retry_4xx(self):
        assert HpnClient._should_retry(400, 0) is False
        assert HpnClient._should_retry(401, 0) is False
        assert HpnClient._should_retry(404, 0) is False

    def test_retry_delay_with_retry_after(self):
        resp = MagicMock()
        resp.headers = {"Retry-After": "5"}
        delay = HpnClient._retry_delay(resp, 0)
        assert 5 <= delay <= 6  # 5 + random [0,1)

    def test_retry_delay_exponential_backoff(self):
        resp = MagicMock()
        resp.headers = {}
        delay = HpnClient._retry_delay(resp, 0)
        assert 1 <= delay <= 2  # 2^0 + random
        delay = HpnClient._retry_delay(resp, 3)
        assert 8 <= delay <= 9  # 2^3 + random

    def test_retry_delay_max_backoff(self):
        resp = MagicMock()
        resp.headers = {}
        delay = HpnClient._retry_delay(resp, 10)
        assert 32 <= delay <= 33  # min(2^10, 32) = 32

    def test_base_url_strips_trailing_slash(self):
        client = HpnClient("https://example.com/", "key")
        assert client.base_url == "https://example.com"

    def test_auth_header(self):
        client = HpnClient("https://example.com", "my-key")
        assert client.session.headers["Authorization"] == "Bearer my-key"


# ── Update check ──────────────────────────────────────────────────────────


class TestUpdateCheck:
    """Tests for the update check logic.

    These tests use _real_check_for_updates to call the original function
    since conftest patches check_for_updates to a no-op.
    """

    def test_cache_fresh_skips_fetch(self, tmp_config_dir, monkeypatch):
        """When cache is fresh and versions match, no fetch happens."""
        os.makedirs(tmp_config_dir, exist_ok=True)
        cache_file = os.path.join(tmp_config_dir, "update_check.json")
        with open(cache_file, "w") as f:
            json.dump({"timestamp": time.time(), "latest_version": __version__}, f)

        with patch("hpn_cli.cli.requests") as mock_requests:
            _real_check_for_updates()
            mock_requests.get.assert_not_called()

    def test_cache_stale_fetches(self, tmp_config_dir, monkeypatch):
        """When cache is old, fetch from PyPI."""
        os.makedirs(tmp_config_dir, exist_ok=True)
        cache_file = os.path.join(tmp_config_dir, "update_check.json")
        with open(cache_file, "w") as f:
            json.dump({"timestamp": 0, "latest_version": __version__}, f)

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"info": {"version": __version__}}

        with patch("hpn_cli.cli.requests") as mock_requests:
            mock_requests.get.return_value = mock_resp
            _real_check_for_updates()
            mock_requests.get.assert_called_once()

    def test_missing_cache_fetches(self, tmp_config_dir, monkeypatch):
        """When no cache exists, fetch from PyPI."""
        os.makedirs(tmp_config_dir, exist_ok=True)

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"info": {"version": __version__}}

        with patch("hpn_cli.cli.requests") as mock_requests:
            mock_requests.get.return_value = mock_resp
            _real_check_for_updates()
            mock_requests.get.assert_called_once()

    def test_network_failure_silently_skips(self, tmp_config_dir, monkeypatch):
        """Network errors are silently swallowed."""
        os.makedirs(tmp_config_dir, exist_ok=True)

        with patch("hpn_cli.cli.requests") as mock_requests:
            mock_requests.get.side_effect = Exception("network error")
            _real_check_for_updates()  # should not raise
