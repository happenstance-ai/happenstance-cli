# happenstance Development

Internal guide for developing and testing the CLI.

## Setup

```bash
cd hpn_cli
uv sync --group dev
```

This creates a `.venv` inside `hpn_cli/` with the package installed in editable mode plus test dependencies.

## Running locally

```bash
# Against local API
HPN_API_URL=http://localhost:8001 uv run hpn --api-key YOUR_KEY search "engineers"

# Against production
uv run hpn --api-key YOUR_KEY search "engineers"

# Or configure once and skip the flag
uv run hpn config set --api-key YOUR_KEY
HPN_API_URL=http://localhost:8001 uv run hpn search "engineers"
```

`HPN_API_URL` defaults to `https://api.happenstance.ai` if not set.

## Tests

```bash
cd hpn_cli
uv run pytest tests/ -s --cov=hpn_cli --cov-report=term-missing
```

All HTTP is mocked with the `responses` library — no API key or running server needed.

## Project structure

```
hpn_cli/
├── pyproject.toml          # Package metadata, hatchling build, `hpn` entry point
├── README.md               # Public-facing (shown on PyPI)
├── DEVELOPMENT.md          # This file (internal)
├── LICENSE                 # MIT
├── hpn_cli/
│   ├── __init__.py         # __version__
│   ├── __main__.py         # python -m hpn_cli
│   └── cli.py              # All CLI logic
└── tests/
    ├── conftest.py          # Shared fixtures
    ├── test_unit.py         # Pure logic tests
    ├── test_integration.py  # Full CLI flows with mocked HTTP
    └── utils.py             # Test helpers
```

## How it's built

- Pure Python, only dependency is `requests`
- Uses `argparse` for CLI parsing (no click/typer — keeps the dependency footprint minimal)
- Subcommands like `search get` and `research get` are pre-dispatched before argparse because argparse can't mix a required positional with subparsers (same pattern as `git stash`/`git stash pop`)
- Config stored in `~/.hpn/config.json`, API key resolution: `--api-key` flag > `HPN_API_KEY` env var > config file
- All output is JSON to stdout, status/errors go to stderr

## CI

The workflow at `.github/workflows/publish-hpn-cli.yml` handles both CI and publishing:

- **Pull requests** touching `hpn_cli/**` → runs tests only (no publish)
- **Tag push** matching `hpn-cli-v*` → runs tests, then builds and publishes to PyPI

Tests run on Ubuntu with Python 3.12 using `uv sync --group dev` and `pytest`.

## Publishing

To release a new version:

1. Bump `__version__` in `hpn_cli/__init__.py` and `version` in `pyproject.toml`
2. Merge to main
3. Tag and push: `git tag hpn-cli-v0.1.0 && git push origin hpn-cli-v0.1.0`
4. The workflow runs tests, builds, and publishes to PyPI via trusted publishing (OIDC)

**First-time setup**: Register `happenstance` on PyPI and configure trusted publishing to accept tokens from this repo's `publish-hpn-cli.yml` workflow with the `pypi` environment.

## Monorepo integration

`hpn_cli/` is excluded from the root workspace (`[tool.uv.workspace] exclude = ["hpn_cli"]`) so it doesn't interfere with the monorepo's venv. It manages its own `.venv` independently.
