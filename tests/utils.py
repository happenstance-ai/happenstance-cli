"""Test helpers for hpn_cli tests."""

import json
import os
import sys
from io import StringIO
from unittest.mock import patch


def run_cli(*args):
    """Invoke CLI main() with given args, return (exit_code, stdout, stderr)."""
    from hpn_cli.cli import main

    captured_out = StringIO()
    captured_err = StringIO()
    exit_code = 0

    with (
        patch.object(sys, "argv", ["hpn"] + list(args)),
        patch.object(sys, "stdout", captured_out),
        patch.object(sys, "stderr", captured_err),
    ):
        try:
            main()
        except SystemExit as e:
            exit_code = e.code if e.code is not None else 0

    return exit_code, captured_out.getvalue(), captured_err.getvalue()


def create_config_file(config_dir, api_key="test-api-key-1234567890", base_url=None):
    """Write a test config file to the given directory."""
    config = {"api_key": api_key}
    if base_url:
        config["base_url"] = base_url
    config_file = os.path.join(config_dir, "config.json")
    os.makedirs(config_dir, exist_ok=True)
    with open(config_file, "w") as f:
        json.dump(config, f)
    return config_file


def mock_search_response(
    search_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee", status="COMPLETED"
):
    """Factory for a search API response."""
    return {
        "id": search_id,
        "status": status,
        "results": [
            {
                "name": "Jane Smith",
                "title": "CTO",
                "company": "Acme Corp",
                "mutuals": [0],
            }
        ],
        "mutuals": [{"name": "Bob Jones", "affinity_score": 0.95}],
        "has_more": False,
    }


def mock_research_response(
    research_id="11111111-2222-3333-4444-555555555555", status="COMPLETED"
):
    """Factory for a research API response."""
    return {
        "id": research_id,
        "status": status,
        "profile": {
            "name": "Jane Smith",
            "title": "CTO",
            "company": "Acme Corp",
            "linkedin_url": "https://linkedin.com/in/janesmith",
        },
    }


def mock_groups_response():
    """Factory for a groups API response."""
    return {
        "groups": [
            {"id": "group-id-1", "name": "My Group", "member_count": 5},
            {"id": "group-id-2", "name": "Another Group", "member_count": 3},
        ]
    }


def mock_group_detail_response(group_id="group-id-1"):
    """Factory for a group detail API response."""
    return {
        "id": group_id,
        "name": "My Group",
        "member_count": 2,
        "members": [
            {"name": "Alice", "profile_image": None},
            {"name": "Bob", "profile_image": None},
        ],
    }


def mock_usage_response():
    """Factory for a usage API response."""
    return {
        "balance": 42,
        "purchases": [],
        "usage": [],
        "auto_reload": None,
    }


def mock_user_response():
    """Factory for a user/me API response."""
    return {
        "email": "test@example.com",
        "name": "Test User",
        "friends": [
            {"name": "Alice"},
            {"name": "Bob"},
        ],
    }
