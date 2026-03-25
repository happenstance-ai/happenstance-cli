# happenstance

Command-line interface for the [Happenstance](https://happenstance.ai) API — search your network and research individual people.

## Install

```bash
# pip
pip install happenstance

# pipx (recommended for CLI tools)
pipx install happenstance

# uv
uv tool install happenstance
```

## Quick start

```bash
# Configure your API key (get one at https://happenstance.ai/settings/api)
hpn config set --api-key YOUR_API_KEY

# Search your network
hpn search "CISOs interested in AI in the SF Bay Area"

# Research a specific person
hpn research "Jane Smith, CTO at Acme Corp"

# Check your credit balance
hpn usage
```

## Commands

| Command | Description |
|---------|-------------|
| `hpn config set --api-key KEY` | Save your API key |
| `hpn config show` | Show saved API key (masked) |
| `hpn search "query"` | Search your network |
| `hpn search get ID` | Get search results |
| `hpn search find-more ID` | Find additional results |
| `hpn research "description"` | Research a person |
| `hpn research get ID` | Get research results |
| `hpn friends` | List your friends |
| `hpn groups` | List your groups |
| `hpn groups get ID` | Get group details |
| `hpn usage` | Show credit balance |

## Configuration

The API key can be provided in three ways (in priority order):

1. `--api-key` flag on any command
2. `HPN_API_KEY` environment variable
3. Config file at `~/.hpn/config.json` (set via `hpn config set`)

All output is JSON and can be piped to `jq` for processing.

## Documentation

Full API docs: https://developer.happenstance.ai
