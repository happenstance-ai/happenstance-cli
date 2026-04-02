"""Integration tests — full CLI flows with mocked HTTP."""

import json
import os

import responses

from .utils import (
    create_config_file,
    mock_group_detail_response,
    mock_groups_response,
    mock_research_response,
    mock_search_response,
    mock_usage_response,
    mock_user_response,
    run_cli,
)

BASE_URL = "https://api.happenstance.ai"


# ── Config ──────────────────────────────────────────────────────────────────


class TestConfigSet:
    def test_set_api_key(self, tmp_config_dir):
        code, out, err = run_cli("config", "set", "--api-key", "my-secret-key")
        assert code == 0
        data = json.loads(out)
        assert data["status"] == "ok"

        # Verify file was written
        with open(os.path.join(tmp_config_dir, "config.json")) as f:
            config = json.load(f)
        assert config["api_key"] == "my-secret-key"

    def test_set_no_key_errors(self, tmp_config_dir):
        code, out, err = run_cli("config", "set")
        assert code == 1
        assert "Nothing to set" in err


class TestConfigShow:
    def test_show_no_config(self, tmp_config_dir):
        code, out, err = run_cli("config", "show")
        assert code == 0
        data = json.loads(out)
        assert data == {}

    def test_show_masks_key(self, tmp_config_dir):
        create_config_file(tmp_config_dir, api_key="abcdefgh12345678xxxx")
        code, out, err = run_cli("config", "show")
        assert code == 0
        data = json.loads(out)
        assert data["api_key"].startswith("abcdefgh")
        assert data["api_key"].endswith("xxxx")
        assert "..." in data["api_key"]


# ── Search ──────────────────────────────────────────────────────────────────


class TestSearch:
    @responses.activate
    def test_search_polls_and_returns(self, tmp_config_dir, monkeypatch):
        create_config_file(tmp_config_dir)
        search_id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"

        responses.add(
            responses.POST,
            f"{BASE_URL}/v1/search",
            json={"id": search_id},
            status=200,
        )
        responses.add(
            responses.GET,
            f"{BASE_URL}/v1/search/{search_id}",
            json=mock_search_response(search_id, status="RUNNING"),
            status=200,
        )
        responses.add(
            responses.GET,
            f"{BASE_URL}/v1/search/{search_id}",
            json=mock_search_response(search_id, status="COMPLETED"),
            status=200,
        )

        # Speed up polling
        monkeypatch.setattr("hpn_cli.cli.time.sleep", lambda _: None)

        code, out, err = run_cli("search", "test query")
        assert code == 0
        data = json.loads(out)
        assert data["status"] == "COMPLETED"

    @responses.activate
    def test_search_no_wait(self, tmp_config_dir):
        create_config_file(tmp_config_dir)
        search_id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"

        responses.add(
            responses.POST,
            f"{BASE_URL}/v1/search",
            json={"id": search_id, "status": "RUNNING"},
            status=200,
        )

        code, out, err = run_cli("search", "--no-wait", "test query")
        assert code == 0
        data = json.loads(out)
        assert data["id"] == search_id

    @responses.activate
    def test_search_with_groups(self, tmp_config_dir, monkeypatch):
        create_config_file(tmp_config_dir)
        search_id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"

        responses.add(
            responses.GET,
            f"{BASE_URL}/v1/groups",
            json=mock_groups_response(),
            status=200,
        )
        responses.add(
            responses.POST,
            f"{BASE_URL}/v1/search",
            json={"id": search_id},
            status=200,
        )
        responses.add(
            responses.GET,
            f"{BASE_URL}/v1/search/{search_id}",
            json=mock_search_response(search_id),
            status=200,
        )

        monkeypatch.setattr("hpn_cli.cli.time.sleep", lambda _: None)

        code, out, err = run_cli("search", "query", "--groups", "My Group")
        assert code == 0

    @responses.activate
    def test_search_default_scope_searches_everything(self, tmp_config_dir):
        """No scope flags → include_friends_connections=True, include_my_connections=True."""
        create_config_file(tmp_config_dir)
        search_id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"

        responses.add(
            responses.POST,
            f"{BASE_URL}/v1/search",
            json={"id": search_id, "status": "RUNNING"},
            status=200,
        )

        run_cli("search", "--no-wait", "engineers")
        body = json.loads(responses.calls[0].request.body)
        assert body["include_friends_connections"] is True
        assert body["include_my_connections"] is True
        assert "group_ids" not in body

    @responses.activate
    def test_search_only_my_connections(self, tmp_config_dir):
        """--my-connections alone → friends excluded."""
        create_config_file(tmp_config_dir)

        responses.add(
            responses.POST,
            f"{BASE_URL}/v1/search",
            json={"id": "id", "status": "RUNNING"},
            status=200,
        )

        run_cli("search", "--no-wait", "--my-connections", "engineers")
        body = json.loads(responses.calls[0].request.body)
        assert body["include_my_connections"] is True
        assert body["include_friends_connections"] is False

    @responses.activate
    def test_search_only_friends(self, tmp_config_dir):
        """--friends alone → my connections excluded."""
        create_config_file(tmp_config_dir)

        responses.add(
            responses.POST,
            f"{BASE_URL}/v1/search",
            json={"id": "id", "status": "RUNNING"},
            status=200,
        )

        run_cli("search", "--no-wait", "--friends", "engineers")
        body = json.loads(responses.calls[0].request.body)
        assert body["include_friends_connections"] is True
        assert body["include_my_connections"] is False

    @responses.activate
    def test_search_group_only_no_friends_no_connections(self, tmp_config_dir):
        """--groups alone → friends and my connections excluded."""
        create_config_file(tmp_config_dir)

        responses.add(
            responses.GET,
            f"{BASE_URL}/v1/groups",
            json=mock_groups_response(),
            status=200,
        )
        responses.add(
            responses.POST,
            f"{BASE_URL}/v1/search",
            json={"id": "id", "status": "RUNNING"},
            status=200,
        )

        run_cli("search", "--no-wait", "engineers", "--groups", "My Group")
        body = json.loads(responses.calls[1].request.body)
        assert body["include_friends_connections"] is False
        assert body["include_my_connections"] is False
        assert body["group_ids"] == ["group-id-1"]

    @responses.activate
    def test_search_group_plus_my_connections(self, tmp_config_dir):
        """--groups + --my-connections → friends excluded, group + connections searched."""
        create_config_file(tmp_config_dir)

        responses.add(
            responses.GET,
            f"{BASE_URL}/v1/groups",
            json=mock_groups_response(),
            status=200,
        )
        responses.add(
            responses.POST,
            f"{BASE_URL}/v1/search",
            json={"id": "id", "status": "RUNNING"},
            status=200,
        )

        run_cli(
            "search",
            "--no-wait",
            "engineers",
            "--groups",
            "My Group",
            "--my-connections",
        )
        body = json.loads(responses.calls[1].request.body)
        assert body["include_my_connections"] is True
        assert body["include_friends_connections"] is False
        assert body["group_ids"] == ["group-id-1"]

    @responses.activate
    def test_search_friends_plus_my_connections(self, tmp_config_dir):
        """--friends + --my-connections → both included, no groups."""
        create_config_file(tmp_config_dir)

        responses.add(
            responses.POST,
            f"{BASE_URL}/v1/search",
            json={"id": "id", "status": "RUNNING"},
            status=200,
        )

        run_cli("search", "--no-wait", "--friends", "--my-connections", "engineers")
        body = json.loads(responses.calls[0].request.body)
        assert body["include_friends_connections"] is True
        assert body["include_my_connections"] is True
        assert "group_ids" not in body

    def test_search_no_api_key(self, tmp_config_dir):
        code, out, err = run_cli("search", "test")
        assert code == 1
        assert "No API key" in err


class TestSearchGet:
    @responses.activate
    def test_get_search_results(self, tmp_config_dir):
        create_config_file(tmp_config_dir)
        search_id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"

        responses.add(
            responses.GET,
            f"{BASE_URL}/v1/search/{search_id}",
            json=mock_search_response(search_id),
            status=200,
        )

        code, out, err = run_cli("search", "get", search_id)
        assert code == 0
        data = json.loads(out)
        assert data["status"] == "COMPLETED"

    @responses.activate
    def test_get_search_with_api_key_equals_form(self, tmp_config_dir):
        """--api-key=VALUE before subcommand should be handled by pre-dispatch."""
        search_id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"

        responses.add(
            responses.GET,
            f"{BASE_URL}/v1/search/{search_id}",
            json=mock_search_response(search_id),
            status=200,
        )

        code, out, err = run_cli(
            "--api-key=test-api-key-1234567890", "search", "get", search_id
        )
        assert code == 0
        data = json.loads(out)
        assert data["status"] == "COMPLETED"

    @responses.activate
    def test_get_search_with_api_key_space_form(self, tmp_config_dir):
        """--api-key KEY (space-separated) before subcommand should be forwarded."""
        search_id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"

        responses.add(
            responses.GET,
            f"{BASE_URL}/v1/search/{search_id}",
            json=mock_search_response(search_id),
            status=200,
        )

        code, out, err = run_cli(
            "--api-key", "test-api-key-1234567890", "search", "get", search_id
        )
        assert code == 0
        data = json.loads(out)
        assert data["status"] == "COMPLETED"

    @responses.activate
    def test_get_search_with_page(self, tmp_config_dir):
        create_config_file(tmp_config_dir)
        search_id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        page_id = "11111111-2222-3333-4444-555555555555"

        responses.add(
            responses.GET,
            f"{BASE_URL}/v1/search/{search_id}",
            json=mock_search_response(search_id),
            status=200,
        )

        code, out, err = run_cli("search", "get", search_id, "--page", page_id)
        assert code == 0
        assert f"page_id={page_id}" in responses.calls[0].request.url


class TestSearchFindMore:
    @responses.activate
    def test_find_more(self, tmp_config_dir, monkeypatch):
        create_config_file(tmp_config_dir)
        search_id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        page_id = "11111111-2222-3333-4444-555555555555"

        responses.add(
            responses.POST,
            f"{BASE_URL}/v1/search/{search_id}/find-more",
            json={"page_id": page_id, "parent_search_id": search_id},
            status=200,
        )
        responses.add(
            responses.GET,
            f"{BASE_URL}/v1/search/{search_id}",
            json=mock_search_response(search_id),
            status=200,
        )

        monkeypatch.setattr("hpn_cli.cli.time.sleep", lambda _: None)

        code, out, err = run_cli("search", "find-more", search_id)
        assert code == 0


# ── Research ──────────────────────────────────────────────────────────────────


class TestResearch:
    @responses.activate
    def test_research_polls_and_returns(self, tmp_config_dir, monkeypatch):
        create_config_file(tmp_config_dir)
        research_id = "11111111-2222-3333-4444-555555555555"

        responses.add(
            responses.POST,
            f"{BASE_URL}/v1/research",
            json={"id": research_id},
            status=200,
        )
        responses.add(
            responses.GET,
            f"{BASE_URL}/v1/research/{research_id}",
            json=mock_research_response(research_id, status="RUNNING"),
            status=200,
        )
        responses.add(
            responses.GET,
            f"{BASE_URL}/v1/research/{research_id}",
            json=mock_research_response(research_id, status="COMPLETED"),
            status=200,
        )

        monkeypatch.setattr("hpn_cli.cli.time.sleep", lambda _: None)

        code, out, err = run_cli("research", "Jane Smith, CTO at Acme")
        assert code == 0
        data = json.loads(out)
        assert data["status"] == "COMPLETED"

    @responses.activate
    def test_research_no_wait(self, tmp_config_dir):
        create_config_file(tmp_config_dir)
        research_id = "11111111-2222-3333-4444-555555555555"

        responses.add(
            responses.POST,
            f"{BASE_URL}/v1/research",
            json={"id": research_id, "status": "RUNNING"},
            status=200,
        )

        code, out, err = run_cli("research", "--no-wait", "Jane Smith")
        assert code == 0


class TestResearchGet:
    @responses.activate
    def test_get_research_results(self, tmp_config_dir):
        create_config_file(tmp_config_dir)
        research_id = "11111111-2222-3333-4444-555555555555"

        responses.add(
            responses.GET,
            f"{BASE_URL}/v1/research/{research_id}",
            json=mock_research_response(research_id),
            status=200,
        )

        code, out, err = run_cli("research", "get", research_id)
        assert code == 0
        data = json.loads(out)
        assert data["status"] == "COMPLETED"


# ── Friends ──────────────────────────────────────────────────────────────────


class TestFriends:
    @responses.activate
    def test_list_friends(self, tmp_config_dir):
        create_config_file(tmp_config_dir)

        responses.add(
            responses.GET,
            f"{BASE_URL}/v1/users/me",
            json=mock_user_response(),
            status=200,
        )

        code, out, err = run_cli("friends")
        assert code == 0
        data = json.loads(out)
        assert data == ["Alice", "Bob"]


# ── Groups ──────────────────────────────────────────────────────────────────


class TestGroups:
    @responses.activate
    def test_list_groups(self, tmp_config_dir):
        create_config_file(tmp_config_dir)

        responses.add(
            responses.GET,
            f"{BASE_URL}/v1/groups",
            json=mock_groups_response(),
            status=200,
        )

        code, out, err = run_cli("groups")
        assert code == 0
        data = json.loads(out)
        assert len(data["groups"]) == 2


class TestGroupsGet:
    @responses.activate
    def test_get_group(self, tmp_config_dir):
        create_config_file(tmp_config_dir)
        group_id = "group-id-1"

        responses.add(
            responses.GET,
            f"{BASE_URL}/v1/groups/{group_id}",
            json=mock_group_detail_response(group_id),
            status=200,
        )

        code, out, err = run_cli("groups", "get", group_id)
        assert code == 0
        data = json.loads(out)
        assert data["name"] == "My Group"
        assert len(data["members"]) == 2


# ── Usage ──────────────────────────────────────────────────────────────────


class TestUsage:
    @responses.activate
    def test_show_usage(self, tmp_config_dir):
        create_config_file(tmp_config_dir)

        responses.add(
            responses.GET,
            f"{BASE_URL}/v1/usage",
            json=mock_usage_response(),
            status=200,
        )

        code, out, err = run_cli("usage")
        assert code == 0
        data = json.loads(out)
        assert data["balance"] == 42


# ── Error paths ──────────────────────────────────────────────────────────────


class TestErrors:
    @responses.activate
    def test_401_unauthorized(self, tmp_config_dir):
        create_config_file(tmp_config_dir)

        responses.add(
            responses.GET,
            f"{BASE_URL}/v1/usage",
            json={"detail": "Invalid API key"},
            status=401,
        )

        code, out, err = run_cli("usage")
        assert code == 1
        assert "Invalid API key" in err

    @responses.activate
    def test_402_insufficient_credits(self, tmp_config_dir):
        create_config_file(tmp_config_dir)

        responses.add(
            responses.POST,
            f"{BASE_URL}/v1/search",
            json={"detail": "Insufficient credits"},
            status=402,
        )

        code, out, err = run_cli("search", "--no-wait", "query")
        assert code == 1
        assert "Insufficient credits" in err
        assert "happenstance.ai/integrations/keys" in err

    @responses.activate
    def test_429_rate_limit(self, tmp_config_dir, monkeypatch):
        create_config_file(tmp_config_dir)

        # Return 429 twice then succeed
        responses.add(
            responses.GET,
            f"{BASE_URL}/v1/usage",
            json={"detail": "Rate limited"},
            status=429,
        )
        responses.add(
            responses.GET,
            f"{BASE_URL}/v1/usage",
            json=mock_usage_response(),
            status=200,
        )

        monkeypatch.setattr("hpn_cli.cli.time.sleep", lambda _: None)

        code, out, err = run_cli("usage")
        assert code == 0
        assert "retrying" in err

    @responses.activate
    def test_404_not_found(self, tmp_config_dir):
        create_config_file(tmp_config_dir)

        responses.add(
            responses.GET,
            f"{BASE_URL}/v1/research/nonexistent",
            json={"detail": "Not found"},
            status=404,
        )

        code, out, err = run_cli("research", "get", "nonexistent")
        assert code == 1
        assert "Not found" in err

    @responses.activate
    def test_500_server_error(self, tmp_config_dir):
        create_config_file(tmp_config_dir)

        responses.add(
            responses.GET,
            f"{BASE_URL}/v1/usage",
            json={"detail": "Internal server error"},
            status=500,
        )

        code, out, err = run_cli("usage")
        assert code == 1

    @responses.activate
    def test_search_timeout(self, tmp_config_dir, monkeypatch):
        create_config_file(tmp_config_dir)
        search_id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"

        responses.add(
            responses.POST,
            f"{BASE_URL}/v1/search",
            json={"id": search_id},
            status=200,
        )
        # Always return RUNNING to trigger timeout
        responses.add(
            responses.GET,
            f"{BASE_URL}/v1/search/{search_id}",
            json={"id": search_id, "status": "RUNNING"},
            status=200,
        )

        monkeypatch.setattr("hpn_cli.cli.time.sleep", lambda _: None)
        # Use a very short timeout (but not 0, so the loop runs at least once)
        monkeypatch.setattr("hpn_cli.cli.SEARCH_TIMEOUT", 0.001)

        code, out, err = run_cli("search", "test query")
        assert code == 1
        assert "Timed out after" in err

    @responses.activate
    def test_search_failed_status(self, tmp_config_dir, monkeypatch):
        create_config_file(tmp_config_dir)
        search_id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"

        responses.add(
            responses.POST,
            f"{BASE_URL}/v1/search",
            json={"id": search_id},
            status=200,
        )
        responses.add(
            responses.GET,
            f"{BASE_URL}/v1/search/{search_id}",
            json={"id": search_id, "status": "FAILED"},
            status=200,
        )

        monkeypatch.setattr("hpn_cli.cli.time.sleep", lambda _: None)

        code, out, err = run_cli("search", "test query")
        assert code == 1
        data = json.loads(out)
        assert data["status"] == "FAILED"

    @responses.activate
    def test_502_retries(self, tmp_config_dir, monkeypatch):
        create_config_file(tmp_config_dir)

        responses.add(
            responses.GET,
            f"{BASE_URL}/v1/usage",
            json={"detail": "Bad Gateway"},
            status=502,
        )
        responses.add(
            responses.GET,
            f"{BASE_URL}/v1/usage",
            json=mock_usage_response(),
            status=200,
        )

        monkeypatch.setattr("hpn_cli.cli.time.sleep", lambda _: None)

        code, out, err = run_cli("usage")
        assert code == 0
        assert "retrying" in err
