"""Happenstance CLI — search your network and research people via the Happenstance API."""

import argparse
import json
import os
import random
import sys
import tempfile
import time

import requests

from hpn_cli import __version__


class HelpFormatter(argparse.RawDescriptionHelpFormatter):
    """Formatter that removes blank lines from empty subparser metavars."""

    def _format_action(self, action):
        result = super()._format_action(action)
        if isinstance(
            action, argparse._SubParsersAction
        ):  # private API, stable across 3.11–3.13
            lines = result.split("\n")
            result = (
                "\n".join(
                    line
                    for line in lines
                    if line.strip()
                    and not (
                        line.strip().startswith("{") and line.strip().endswith("}")
                    )
                )
                + "\n"
            )
        return result


CONFIG_DIR = os.path.expanduser("~/.hpn")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")
DEFAULT_BASE_URL = "https://api.happenstance.ai"

SEARCH_TIMEOUT = 90
RESEARCH_TIMEOUT = 600

UPDATE_CHECK_FILE = os.path.join(CONFIG_DIR, "update_check.json")
UPDATE_CHECK_INTERVAL = 86400  # 1 day in seconds


# ── config ────────────────────────────────────────────────────────────────────


def load_config():
    """Load config from file. Returns dict with api_key and base_url (may be None)."""
    if not os.path.exists(CONFIG_FILE):
        return {}
    with open(CONFIG_FILE) as f:
        return json.load(f)


def resolve_config(args):
    """Resolve api_key and base_url from CLI flags > env vars > config file."""
    file_config = load_config()

    api_key = (
        getattr(args, "api_key", None)
        or os.environ.get("HPN_API_KEY")
        or file_config.get("api_key")
    )
    base_url = os.environ.get("HPN_API_URL") or DEFAULT_BASE_URL

    return api_key, base_url


def do_config_set(args):
    api_key = args.config_api_key or getattr(args, "api_key", None)
    if not api_key:
        print("Nothing to set. Use --api-key.", file=sys.stderr)
        sys.exit(1)
    args.config_api_key = api_key
    os.makedirs(CONFIG_DIR, exist_ok=True)
    config = load_config()
    config["api_key"] = args.config_api_key
    config.pop("base_url", None)
    fd, tmp_path = tempfile.mkstemp(dir=CONFIG_DIR, suffix=".tmp")
    with os.fdopen(fd, "w") as f:
        json.dump(config, f, indent=2)
    os.chmod(tmp_path, 0o600)
    os.rename(tmp_path, CONFIG_FILE)
    output({"status": "ok", "config_file": CONFIG_FILE})


def do_config_show(args):
    config = load_config()
    config.pop("base_url", None)
    if config.get("api_key"):
        key = config["api_key"]
        config["api_key"] = key[:8] + "..." + key[-4:] if len(key) > 12 else "***"
    output(config)


# ── HTTP client ───────────────────────────────────────────────────────────────


class HpnClient:
    def __init__(self, base_url, api_key):
        self.session = requests.Session()
        self.session.headers["Authorization"] = f"Bearer {api_key}"
        self.session.headers["Content-Type"] = "application/json"
        self.session.headers["User-Agent"] = f"happenstance-cli/{__version__}"
        self.base_url = base_url.rstrip("/")

    def get(self, path, params=None):
        return self._request("GET", path, params=params)

    def post(self, path, json_data=None):
        return self._request("POST", path, json=json_data)

    MAX_RETRIES = 10  # safety net — _should_retry also caps per status code

    def _request(self, method, path, **kwargs):
        attempt = 0
        while attempt <= self.MAX_RETRIES:
            resp = self.session.request(method, f"{self.base_url}{path}", **kwargs)
            if resp.status_code < 400:
                return resp.json()

            retry = self._should_retry(resp.status_code, attempt)
            if not retry:
                self._handle_error(resp)

            delay = self._retry_delay(resp, attempt)
            print(
                f"HTTP {resp.status_code} — retrying in {delay:.0f}s (attempt {attempt + 1})...",
                file=sys.stderr,
            )
            time.sleep(delay)
            attempt += 1
        self._handle_error(resp)  # retries exhausted

    @staticmethod
    def _handle_error(resp):
        """Print a user-friendly error and exit.

        For 429: reached after _should_retry exhausts its 10-attempt cap.
        """
        if resp.status_code == 402:
            print(
                "Insufficient credits. Purchase more at https://happenstance.ai/api/keys",
                file=sys.stderr,
            )
            sys.exit(1)
        if resp.status_code == 429:
            print(
                "Too many concurrent requests. Wait for running searches or researches to complete.",
                file=sys.stderr,
            )
            sys.exit(1)
        try:
            error = resp.json()
        except Exception:
            error = {"status": resp.status_code, "detail": resp.text}
        print(json.dumps(error, indent=2), file=sys.stderr)
        sys.exit(1)

    @staticmethod
    def _should_retry(status_code, attempt):
        if status_code == 429:
            return attempt < 10
        if status_code in (
            502,
            503,
            504,
        ):  # gateway errors (transient); 500 is not retried (server bug)
            return attempt < 5
        return False

    @staticmethod
    def _retry_delay(resp, attempt):
        retry_after = resp.headers.get("Retry-After")
        if retry_after:
            try:
                return max(0, float(retry_after)) + random.random()
            except ValueError:
                pass
        backoff = min(2**attempt, 32)
        return backoff + random.random()


def require_client(args):
    """Build HpnClient from resolved config, exit if no API key."""
    api_key, base_url = resolve_config(args)
    if not api_key:
        print(
            "No API key configured. Set one with: hpn config set --api-key KEY",
            file=sys.stderr,
        )
        print(
            "Or set HPN_API_KEY environment variable, or pass --api-key flag.",
            file=sys.stderr,
        )
        sys.exit(1)
    return HpnClient(base_url, api_key)


# ── helpers ───────────────────────────────────────────────────────────────────


def output(data):
    print(json.dumps(data, indent=2))


def output_poll_result(data):
    """Output polled result and exit non-zero if not COMPLETED."""
    if data is None:
        sys.exit(1)
    output(data)
    if data.get("status") != "COMPLETED":
        sys.exit(1)


def simple_get(path_template):
    """Factory for handlers that just GET a path and output the result."""

    def handler(args):
        client = require_client(args)
        output(client.get(path_template.format(**vars(args))))

    return handler


do_usage = simple_get("/v1/usage")
do_groups = simple_get("/v1/groups")
do_groups_get = simple_get("/v1/groups/{id}")
do_research_get = simple_get("/v1/research/{id}")


def do_friends(args):
    client = require_client(args)
    data = client.get("/v1/users/me")
    names = [f["name"] for f in data.get("friends", [])]
    output(names)


def resolve_group_ids(client, group_names):
    """Resolve group names to IDs via case-insensitive exact match."""
    data = client.get("/v1/groups")
    groups = data.get("groups", [])
    resolved = []
    for name in group_names:
        matches = [g for g in groups if g["name"].lower() == name.lower()]
        if len(matches) == 0:
            print(f"Error: No group found matching '{name}'.", file=sys.stderr)
            sys.exit(1)
        if len(matches) > 1:
            print(
                f"Error: Multiple groups match '{name}'. Use the group ID instead.",
                file=sys.stderr,
            )
            sys.exit(1)
        resolved.append(matches[0]["id"])
    return resolved


def poll_until_done(client, path, timeout, interval=5, params=None):
    """Poll a status endpoint until COMPLETED/FAILED/FAILED_AMBIGUOUS or timeout."""
    deadline = time.time() + timeout
    data = None
    while time.time() < deadline:
        data = client.get(path, params=params)
        status = data.get("status", "")
        if status in ("COMPLETED", "FAILED", "FAILED_AMBIGUOUS"):
            return data
        print(f"Status: {status} — polling again in {interval}s...", file=sys.stderr)
        time.sleep(interval)
    print(
        f"Timed out after {timeout}s. Something may have gone wrong, "
        "but you can keep polling this ID.",
        file=sys.stderr,
    )
    return data


# ── update check ──────────────────────────────────────────────────────────────


def _is_homebrew_install():
    """Return True if the CLI was installed via Homebrew."""
    try:
        exe = os.path.realpath(sys.executable)
        return "/Cellar/" in exe or "/homebrew/" in exe.lower()
    except Exception:
        return False


def _upgrade_command():
    """Return the appropriate upgrade command based on install method."""
    if _is_homebrew_install():
        return "brew upgrade happenstance"
    return "pip install --upgrade happenstance"


def check_for_updates():
    """Check PyPI for a newer version, at most once per day. Non-blocking."""
    try:
        upgrade_cmd = _upgrade_command()

        # Check if we should skip (cached recently)
        if os.path.exists(UPDATE_CHECK_FILE):
            with open(UPDATE_CHECK_FILE) as f:
                cache = json.load(f)
            if time.time() - cache.get("timestamp", 0) < UPDATE_CHECK_INTERVAL:
                latest = cache.get("latest_version")
                if latest and latest != __version__:
                    print(
                        f"Update available: {__version__} → {latest}. "
                        f"Run `{upgrade_cmd}` to update.",
                        file=sys.stderr,
                    )
                return  # cache is fresh, skip network check

        # Fetch latest version from PyPI
        resp = requests.get("https://pypi.org/pypi/happenstance/json", timeout=3)
        if resp.status_code != 200:
            return
        latest = resp.json()["info"]["version"]

        # Cache the result (atomic write, consistent with do_config_set)
        os.makedirs(CONFIG_DIR, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(dir=CONFIG_DIR, suffix=".tmp")
        with os.fdopen(fd, "w") as f:
            json.dump({"timestamp": time.time(), "latest_version": latest}, f)
        os.rename(tmp_path, UPDATE_CHECK_FILE)

        if latest != __version__:
            print(
                f"Update available: {__version__} → {latest}. "
                f"Run `{upgrade_cmd}` to update.",
                file=sys.stderr,
            )
    except Exception:
        pass  # silently skip on any failure


# ── search ────────────────────────────────────────────────────────────────────


def do_search(args):
    client = require_client(args)
    # If no scope flags are set, search everything. Otherwise, only search what was specified.
    scope_specified = args.groups or args.friends or args.my_connections
    body = {
        "text": args.query,
        "include_friends_connections": args.friends if scope_specified else True,
        "include_my_connections": args.my_connections if scope_specified else True,
    }
    if args.groups:
        body["group_ids"] = resolve_group_ids(client, args.groups)

    data = client.post("/v1/search", body)

    if args.no_wait:
        output(data)
        return

    search_id = data["id"]
    print(f"Search started: {search_id}", file=sys.stderr)
    result = poll_until_done(client, f"/v1/search/{search_id}", timeout=SEARCH_TIMEOUT)
    output_poll_result(result)


def do_search_get(args):
    client = require_client(args)
    params = {}
    if args.page:
        params["page_id"] = args.page
    output(client.get(f"/v1/search/{args.id}", params=params))


def do_search_find_more(args):
    client = require_client(args)
    data = client.post(f"/v1/search/{args.id}/find-more")

    if args.no_wait:
        output(data)
        return

    page_id = data["page_id"]
    parent_id = data["parent_search_id"]
    print(f"Find-more started: {page_id}", file=sys.stderr)
    result = poll_until_done(
        client,
        f"/v1/search/{parent_id}",
        timeout=SEARCH_TIMEOUT,
        params={"page_id": page_id},
    )
    output_poll_result(result)


# ── research ──────────────────────────────────────────────────────────────────


def do_research(args):
    client = require_client(args)
    data = client.post("/v1/research", {"description": args.description})

    if args.no_wait:
        output(data)
        return

    research_id = data["id"]
    print(f"Research started: {research_id}", file=sys.stderr)
    result = poll_until_done(
        client, f"/v1/research/{research_id}", timeout=RESEARCH_TIMEOUT, interval=10
    )
    output_poll_result(result)


# Subcommands that need pre-dispatch (because their parent has a required positional).
# Maps (command, subcommand) → builder function that returns a callable.
_SUBCOMMANDS = {
    ("search", "get"): lambda argv: _make_handler(
        "hpn search get",
        "Get status and results of a network search. If the search is still running, shows current status.",
        do_search_get,
        lambda p: (
            p.add_argument("id", help="Search ID"),
            p.add_argument("--page", help="Page ID (from find-more results)"),
        ),
        argv,
    ),
    ("search", "find-more"): lambda argv: _make_handler(
        "hpn search find-more",
        "Find additional results for a completed search. Excludes all people already returned "
        "in previous results. Uses the same query and settings as the original search.",
        do_search_find_more,
        lambda p: (
            p.add_argument("id", help="Search ID"),
            p.add_argument(
                "--no-wait", action="store_true", help="Don't wait for completion"
            ),
        ),
        argv,
    ),
    ("research", "get"): lambda argv: _make_handler(
        "hpn research get",
        "Get status and results of a person research request. Includes full profile when completed.",
        do_research_get,
        lambda p: p.add_argument("id", help="Research ID"),
        argv,
    ),
}


def _make_handler(prog, description, func, add_args, argv):
    """Build an argparse parser, parse argv, and return a bound handler."""
    p = argparse.ArgumentParser(prog=prog, description=description)
    p.add_argument("--api-key", help="API key (overrides config/env)")
    add_args(p)
    args = p.parse_args(argv)
    return lambda: func(args)


def _pop_subcommand(argv):
    """If argv contains a known (command, subcommand) pair, remove them and
    return a callable that runs the subcommand. Otherwise return None.

    Handles flags like --api-key KEY appearing before the command.
    """
    # Walk argv[1:] skipping flags to find positional tokens
    i = 1
    cmd_i = subcmd_i = None
    cmd = subcmd = None
    while i < len(argv):
        arg = argv[i]
        if arg == "--api-key" and i + 1 < len(argv):
            i += 2
            continue
        if arg.startswith("--api-key="):
            i += 1
            continue
        if arg.startswith("-"):
            i += 1
            continue
        if cmd is None:
            cmd, cmd_i = arg, i
        elif subcmd is None:
            subcmd, subcmd_i = arg, i
            break
        else:
            break
        i += 1

    if cmd and subcmd and (cmd, subcmd) in _SUBCOMMANDS:
        # Remove command and subcommand from argv, keep everything else
        rest = argv[1:cmd_i] + argv[cmd_i + 1 : subcmd_i] + argv[subcmd_i + 1 :]
        return _SUBCOMMANDS[(cmd, subcmd)](rest)

    return None


# ── main ──────────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(
        prog="hpn",
        description=(
            "Happenstance CLI — search your network and research people "
            "via the Happenstance API.\n\n"
            "All output is JSON. Configure your API key with "
            "`hpn config set --api-key KEY`\n"
            "or set the HPN_API_KEY environment variable."
        ),
        formatter_class=HelpFormatter,
        epilog="""Examples:
  hpn config set --api-key YOUR_API_KEY
  hpn search "CISOs interested in AI"
  hpn research "https://www.linkedin.com/in/garrytan/"
  hpn friends
  hpn groups
  hpn usage""",
    )
    parser.add_argument("--api-key", help="API key (overrides config/env)")
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )
    parser._optionals.title = "Options"
    subparsers = parser.add_subparsers(dest="command", title="Commands", metavar="")

    # config
    config_parser = subparsers.add_parser(
        "config",
        help="Manage API key",
        description="Store your API key in ~/.hpn/config.json",
        formatter_class=HelpFormatter,
    )
    config_parser.set_defaults(func=lambda args: config_parser.print_help())
    config_sub = config_parser.add_subparsers(
        dest="config_command", title="Commands", metavar=""
    )

    config_set = config_sub.add_parser("set", help="Save your API key")
    config_set.add_argument(
        "--api-key", dest="config_api_key", metavar="KEY", help="API key"
    )
    config_set.set_defaults(func=do_config_set)

    config_show = config_sub.add_parser("show", help="Show saved API key (masked)")
    config_show.set_defaults(func=do_config_show)

    # search
    search_parser = subparsers.add_parser(
        "search",
        help="Search for people",
        description=(
            "Search across your connections, groups, and friends' networks. "
            "Runs asynchronously — returns a search ID, then polls until results are ready."
        ),
        formatter_class=HelpFormatter,
        epilog="""Scope:
  By default, searches your connections, friends' connections, and all
  groups. If you specify --groups, --friends, or --my-connections, only
  those sources are searched. You can combine multiple scope flags.

Credits:
  Each search costs 2 credits. Run `hpn usage` to check your balance.
  Returns exit code 1 if the search fails or times out.

Errors:
  402  Insufficient credits — purchase more at https://happenstance.ai/api/keys
  429  Too many concurrent requests (max 10 running searches or researches)

Examples:
  hpn search "CISOs interested in AI in the SF Bay Area"
  hpn search "ML engineers who rock climb"
  hpn search "VCs who would invest in a dev tools startup"
  hpn search "engineers" --groups "My Group"
  hpn search "product designers" --friends --my-connections
  hpn search "engineers @<Alex Teichman> knows"
  hpn search get ID              Fetch results for a search
  hpn search get ID --page PID   Fetch a specific page of results
  hpn search find-more ID        Find additional results for a search

The query is freeform. You can, for example, paste in a raw job
description copied from a website (stray formatting is fine).

@mentions: Use @<Full Name> in queries to restrict results to a
specific person's connections or exclude them. Run `hpn friends`
to see names available for @mentions.""",
    )
    search_parser.add_argument("query", help="Search query text")
    search_parser.add_argument(
        "--groups", nargs="+", help="Group names to search (run `hpn groups` to list)"
    )
    search_parser.add_argument(
        "--friends", action="store_true", help="Search friends' connections"
    )
    search_parser.add_argument(
        "--my-connections", action="store_true", help="Search your own connections"
    )
    search_parser.add_argument(
        "--no-wait", action="store_true", help="Don't wait for completion"
    )
    search_parser.set_defaults(func=do_search)

    # research
    research_parser = subparsers.add_parser(
        "research",
        help="Research a person",
        description=(
            "Research a specific person to get a detailed professional profile. "
            "Runs asynchronously."
        ),
        formatter_class=HelpFormatter,
        epilog="""Credits:
  Each successful research costs 1 credit. Failed/ambiguous lookups are free.

Tips:
  Include as many details as possible for best results:
  - "Garry Tan, CEO of Y Combinator, @garrytan on Twitter"
  - "https://www.linkedin.com/in/garrytan/"
  A name alone is often too ambiguous.

Examples:
  hpn research "https://www.linkedin.com/in/garrytan/"
  hpn research "the CEO of Happenstance"
  hpn research "@mkbhd on Instagram"
  hpn research "Garry Tan, CEO of Y Combinator"
  hpn research get 11111111-2222-3333-4444-555555555555

The description is freeform: a name with title/company, a LinkedIn
URL, a social media handle, or any identifying details. Include
enough detail to uniquely identify the person (e.g. "Alex Teichman"
alone is too ambiguous, but "Alex Teichman, CEO at Happenstance" is not).""",
    )
    research_parser.add_argument(
        "description",
        help="Any identifying info: name, title, LinkedIn URL, handle, etc.",
    )
    research_parser.add_argument(
        "--no-wait", action="store_true", help="Don't wait for completion"
    )
    research_parser.set_defaults(func=do_research)

    # friends
    friends_parser = subparsers.add_parser(
        "friends",
        help="List your friends",
        description=(
            "List your friends. Use as @<Full Name> mentions in search queries "
            "to filter results to a specific person's connections or exclude them."
        ),
    )
    friends_parser.set_defaults(func=do_friends)

    # groups
    groups_parser = subparsers.add_parser(
        "groups",
        help="List your groups",
        description=(
            'List your groups. Use group names with `hpn search --groups "Group Name"` '
            "to scope searches. Use `hpn groups get ID` to see members for @mention lookup."
        ),
        formatter_class=HelpFormatter,
    )
    groups_parser.set_defaults(func=do_groups)
    groups_sub = groups_parser.add_subparsers(
        dest="groups_command", title="Commands", metavar=""
    )

    groups_get = groups_sub.add_parser(
        "get",
        help="Show group members",
        description=(
            "Get details of a group including full member list. "
            "Member names can be used as @mentions in search queries."
        ),
    )
    groups_get.add_argument("id", help="Group ID (from `hpn groups` output)")
    groups_get.set_defaults(func=do_groups_get)

    # usage
    usage_parser = subparsers.add_parser(
        "usage",
        help="View credit balance and history",
        description=(
            "Show your credit balance, purchase history, usage history, "
            "and auto-reload settings."
        ),
    )
    usage_parser.set_defaults(func=do_usage)

    # Subcommand dispatch: argparse can't mix a required positional with
    # subparsers (e.g. `search <query>` vs `search get <id>`). This is the
    # same pattern used by `git stash [push]` / `git stash pop`. We intercept
    # known subcommands before argparse sees them.
    subcmd = _pop_subcommand(sys.argv)
    if subcmd:
        return subcmd()

    # Bare `hpn search` / `hpn research` with no args → show help
    if len(sys.argv) == 2 and sys.argv[1] in ("search", "research"):
        sys.argv.append("--help")

    args = parser.parse_args()

    check_for_updates()

    if hasattr(args, "func"):
        args.func(args)
    else:
        parser.print_help()
