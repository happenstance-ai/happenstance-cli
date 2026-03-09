#!/usr/bin/env python3

"""Happenstance CLI - wraps the public developer API for external users and agentic workflows."""

import argparse
import json
import os
import sys
import time

import requests

class HelpFormatter(argparse.RawDescriptionHelpFormatter):
    """Formatter that removes blank lines from empty subparser metavars."""
    def _format_action(self, action):
        result = super()._format_action(action)
        if isinstance(action, argparse._SubParsersAction):
            # Remove blank lines caused by empty metavar
            lines = result.split('\n')
            result = '\n'.join(line for line in lines if line.strip()) + '\n'
        return result


CONFIG_DIR = os.path.expanduser('~/.hpn')
CONFIG_FILE = os.path.join(CONFIG_DIR, 'config.json')
DEFAULT_BASE_URL = 'https://api.happenstance.ai'

SEARCH_TIMEOUT = 90
RESEARCH_TIMEOUT = 420


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
        getattr(args, 'api_key', None)
        or os.environ.get('HPN_API_KEY')
        or file_config.get('api_key')
    )
    base_url = (
        os.environ.get('HPN_API_URL')
        or DEFAULT_BASE_URL
    )

    return api_key, base_url


def do_config_set(args):
    if not args.config_api_key:
        print("Nothing to set. Use --api-key.", file=sys.stderr)
        sys.exit(1)
    os.makedirs(CONFIG_DIR, exist_ok=True)
    config = load_config()
    config['api_key'] = args.config_api_key
    config.pop('base_url', None)
    with open(CONFIG_FILE, 'w') as f:
        json.dump(config, f, indent=2)
    os.chmod(CONFIG_FILE, 0o600)
    output({"status": "ok", "config_file": CONFIG_FILE})


def do_config_show(args):
    config = load_config()
    config.pop('base_url', None)
    if config.get('api_key'):
        key = config['api_key']
        config['api_key'] = key[:8] + '...' + key[-4:] if len(key) > 12 else '***'
    output(config)


# ── HTTP client ───────────────────────────────────────────────────────────────

class HpnClient:
    def __init__(self, base_url, api_key):
        self.session = requests.Session()
        self.session.headers['Authorization'] = f'Bearer {api_key}'
        self.session.headers['Content-Type'] = 'application/json'
        self.base_url = base_url.rstrip('/')

    def get(self, path, params=None):
        return self._request('GET', path, params=params)

    def post(self, path, json_data=None):
        return self._request('POST', path, json=json_data)

    def _request(self, method, path, **kwargs):
        resp = self.session.request(method, f'{self.base_url}{path}', **kwargs)
        if resp.status_code >= 400:
            # RFC 7807 Problem Details
            try:
                error = resp.json()
            except Exception:
                error = {"status": resp.status_code, "detail": resp.text}
            output(error)
            sys.exit(1)
        return resp.json()


def require_client(args):
    """Build HpnClient from resolved config, exit if no API key."""
    api_key, base_url = resolve_config(args)
    if not api_key:
        print("No API key configured. Set one with: hpn config set --api-key KEY", file=sys.stderr)
        print("Or set HPN_API_KEY environment variable, or pass --api-key flag.", file=sys.stderr)
        sys.exit(1)
    return HpnClient(base_url, api_key)


# ── helpers ───────────────────────────────────────────────────────────────────

def output(data):
    print(json.dumps(data, indent=2))


def simple_get(path_template):
    """Factory for handlers that just GET a path and output the result."""
    def handler(args):
        client = require_client(args)
        output(client.get(path_template.format(**vars(args))))
    return handler


do_usage = simple_get('/v1/usage')
do_groups = simple_get('/v1/groups')
do_groups_get = simple_get('/v1/groups/{id}')
do_research_get = simple_get('/v1/research/{id}')


def do_friends(args):
    client = require_client(args)
    data = client.get('/v1/users/me')
    names = [f['name'] for f in data.get('friends', [])]
    output(names)


def resolve_group_ids(client, group_names):
    """Resolve group names to IDs via case-insensitive exact match."""
    data = client.get('/v1/groups')
    groups = data.get('groups', [])
    resolved = []
    for name in group_names:
        matches = [g for g in groups if g['name'].lower() == name.lower()]
        if len(matches) == 0:
            print(f"Error: No group found matching '{name}'.", file=sys.stderr)
            sys.exit(1)
        if len(matches) > 1:
            print(f"Error: Multiple groups match '{name}'. Use the group ID instead.", file=sys.stderr)
            sys.exit(1)
        resolved.append(matches[0]['id'])
    return resolved


def poll_until_done(client, path, timeout, interval=5):
    """Poll a status endpoint until COMPLETED/FAILED/FAILED_AMBIGUOUS or timeout."""
    deadline = time.time() + timeout
    data = None
    while time.time() < deadline:
        data = client.get(path)
        status = data.get('status', '')
        if status in ('COMPLETED', 'FAILED', 'FAILED_AMBIGUOUS'):
            return data
        remaining = max(0, int(deadline - time.time()))
        print(f"Status: {status} — polling again in {interval}s ({remaining}s remaining)...", file=sys.stderr)
        time.sleep(interval)
    print(f"Timed out after {timeout}s. Something may have gone wrong, "
          "but you can keep polling this ID.", file=sys.stderr)
    return data


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

    data = client.post('/v1/search', body)

    if args.no_wait:
        output(data)
        return

    search_id = data['id']
    print(f"Search started: {search_id}", file=sys.stderr)
    result = poll_until_done(client, f'/v1/search/{search_id}', timeout=SEARCH_TIMEOUT)
    output(result)


def do_search_get(args):
    client = require_client(args)
    params = {}
    if args.page:
        params['page_id'] = args.page
    output(client.get(f'/v1/search/{args.id}', params=params))


def do_search_find_more(args):
    client = require_client(args)
    data = client.post(f'/v1/search/{args.id}/find-more')

    if args.no_wait:
        output(data)
        return

    page_id = data['page_id']
    parent_id = data['parent_search_id']
    print(f"Find-more started: {page_id}", file=sys.stderr)
    result = poll_until_done(client, f'/v1/search/{parent_id}?page_id={page_id}', timeout=SEARCH_TIMEOUT)
    output(result)


# ── research ──────────────────────────────────────────────────────────────────

def do_research(args):
    client = require_client(args)
    data = client.post('/v1/research', {"description": args.description})

    if args.no_wait:
        output(data)
        return

    research_id = data['id']
    print(f"Research started: {research_id}", file=sys.stderr)
    result = poll_until_done(client, f'/v1/research/{research_id}', timeout=RESEARCH_TIMEOUT)
    output(result)


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        prog='hpn',
        description='Happenstance CLI',
        formatter_class=HelpFormatter,
        epilog='''Examples:
  hpn config set --api-key sk-...
  hpn search "CISOs interested in AI"
  hpn research "John Smith, CTO at Acme Corp"
  hpn friends
  hpn groups
  hpn usage''',
    )
    parser.add_argument('--api-key', help='API key (overrides config/env)')
    parser._optionals.title = 'Options'
    subparsers = parser.add_subparsers(dest='command', title='Commands', metavar='')

    # config
    config_parser = subparsers.add_parser(
        'config', help='Manage API key',
        description='Store your API key in ~/.hpn/config.json',
        formatter_class=HelpFormatter,
    )
    config_parser.set_defaults(func=lambda args: config_parser.print_help())
    config_sub = config_parser.add_subparsers(dest='config_command', title='Commands', metavar='')

    config_set = config_sub.add_parser('set', help='Save your API key')
    config_set.add_argument('--api-key', dest='config_api_key', metavar='KEY', help='API key')
    config_set.set_defaults(func=do_config_set)

    config_show = config_sub.add_parser('show', help='Show saved API key (masked)')
    config_show.set_defaults(func=do_config_show)

    # search
    search_parser = subparsers.add_parser(
        'search', help='Search for people',
        formatter_class=HelpFormatter,
        epilog='''Scope:
  By default, searches your connections, friends' connections, and all
  groups. If you specify --groups, --friends, or --my-connections, only
  those sources are searched.

Examples:
  hpn search "CISOs interested in AI"
  hpn search "engineers" --groups "My Group"
  hpn search "VCs in SF" --friends --my-connections
  hpn search "engineers @<Jane Smith> knows"
  hpn search "VCs but not anyone @<Bob Jones> knows"

@mentions: Use @<Name> in queries to restrict results to a specific
person's connections or to exclude them. Use "hpn friends" to see
names available for @mentions.''',
    )
    search_parser.add_argument('query', nargs='?', help='Search query text')
    search_parser.add_argument('--groups', nargs='+',
                               help='Group names to search (run `hpn groups` to list)')
    search_parser.add_argument('--friends', action='store_true',
                               help="Search friends' connections")
    search_parser.add_argument('--my-connections', action='store_true',
                               help='Search your own connections')
    search_parser.add_argument('--no-wait', action='store_true', help="Don't wait for completion")
    search_parser.set_defaults(func=lambda args: do_search(args) if args.query else search_parser.print_help())
    search_sub = search_parser.add_subparsers(dest='search_command', title='Commands')

    search_get = search_sub.add_parser('get', help='Fetch results for a search',
                                       description='Fetch results for a completed or in-progress search.')
    search_get.add_argument('id', help='Search ID')
    search_get.add_argument('--page', help='Page ID (from find-more results)')
    search_get.set_defaults(func=do_search_get)

    search_find_more = search_sub.add_parser('find-more', help='Find additional results',
                                             description='Find additional results for a completed search.')
    search_find_more.add_argument('id', help='Search ID')
    search_find_more.add_argument('--no-wait', action='store_true', help="Don't wait for completion")
    search_find_more.set_defaults(func=do_search_find_more)

    # research
    research_parser = subparsers.add_parser(
        'research', help='Research a person',
        formatter_class=HelpFormatter,
        epilog='''Examples:
  hpn research "Jane Smith, CTO at Acme Corp"
  hpn research "Bob Jones, partner at Sequoia Capital"''',
    )
    research_parser.add_argument('description', nargs='?',
                                 help="Name and details, e.g. 'Jane Smith, CTO at Acme'")
    research_parser.add_argument('--no-wait', action='store_true', help="Don't wait for completion")
    research_parser.set_defaults(func=lambda args: do_research(args) if args.description else research_parser.print_help())
    research_sub = research_parser.add_subparsers(dest='research_command', title='Commands')

    research_get = research_sub.add_parser('get', help='Fetch results for a research request',
                                           description='Fetch results for a research request.')
    research_get.add_argument('id', help='Research ID')
    research_get.set_defaults(func=do_research_get)

    # friends
    friends_parser = subparsers.add_parser(
        'friends',
        help='List your friends (use as @<Full Name> in searches)',
        description='List friend names. Use as @<Full Name> mentions in search queries.',
    )
    friends_parser.set_defaults(func=do_friends)

    # groups
    groups_parser = subparsers.add_parser(
        'groups',
        help='List your groups (names for search --groups)',
        description='List your groups. Pass group names to `hpn search --groups`.',
        formatter_class=HelpFormatter,
    )
    groups_parser.set_defaults(func=do_groups)
    groups_sub = groups_parser.add_subparsers(dest='groups_command', title='Commands', metavar='')

    groups_get = groups_sub.add_parser('get', help='Show group members')
    groups_get.add_argument('id', help="Group ID (from `hpn groups` output)")
    groups_get.set_defaults(func=do_groups_get)

    # usage
    usage_parser = subparsers.add_parser(
        'usage', help='View credit balance and history',
        description='Show your credit balance and usage history.',
    )
    usage_parser.set_defaults(func=do_usage)

    args = parser.parse_args()
    if hasattr(args, 'func'):
        args.func(args)
    else:
        parser.print_help()


if __name__ == '__main__':
    main()
