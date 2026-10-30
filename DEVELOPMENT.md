# Happenstance CLI development

This repository contains the `hpn` / `happenstance` CLI, published as the `happenstance` Python package. It calls the Happenstance public API over HTTP and runs independently of the backend repository.

## Setup

From the repository root:

```bash
uv sync --frozen --group dev
uv run hpn --help
```

Python 3.11 or newer is required. Dependencies are `requests` and `urllib3`; command parsing uses the standard-library `argparse` module.

## Tests

```bash
uv run pytest tests/ -s --cov=hpn_cli --cov-report=term-missing
```

All HTTP is mocked with `responses`. No API key or running backend is needed.

## Running locally

```bash
# Against a local API
HPN_API_URL=http://localhost:8001 uv run hpn --api-key YOUR_KEY search "engineers"

# Against the public API
uv run hpn --api-key YOUR_KEY search "engineers"
```

`HPN_API_URL` defaults to `https://api.happenstance.ai`. API keys resolve in this order: `--api-key`, `HPN_API_KEY`, then `~/.hpn/config.json`. JSON results go to stdout; progress and errors go to stderr.

## Project structure

- `hpn_cli/cli.py`: command parsing, API client, polling, and output handling
- `hpn_cli/__init__.py`: package version
- `tests/`: unit and mocked HTTP integration tests
- `homebrew/generate_formula.py`: generates the Homebrew formula from a published PyPI release
- `.github/workflows/publish-hpn-cli.yml`: tests and release automation

Nested commands such as `search get` are dispatched before argparse. Reuse the existing client and polling helpers when adding commands.

## CI

Pull requests, pushes to `main`, and `hpn-cli-v*` tags run tests on Python 3.11, 3.12, 3.13, and 3.14. A pull request into `main` needs one approving review and all four test checks to merge.

## Publishing

A release is an ordinary pull request:

1. Update `version` in `pyproject.toml` and `__version__` in `hpn_cli/__init__.py`, and refresh `uv.lock` with `uv lock`.
2. Open a pull request into `main`, get it reviewed, and merge it.
3. An org admin creates and pushes `hpn-cli-v<VERSION>` on `main`'s current commit. Do not recreate an already-published version.
4. The workflow checks that the tag points at `main`'s current commit and matches the package version, builds the package, publishes to PyPI through OIDC, and updates the Homebrew tap. No further approval is needed.

To preview a Homebrew formula for an already-published version:

```bash
python homebrew/generate_formula.py 0.2.3
```

The repository was extracted from the backend's `hpn_cli/` directory with its history. Historical commits predating packaging may still refer to the old monorepo layout.
