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

Pull requests, pushes to `main`, and `hpn-cli-v*` tags run tests on Python 3.11, 3.12, 3.13, and 3.14. Publishing runs only for a release tag when the repository variable `CLI_PUBLISH_ENABLED` is `true`.

## Release migration

Publishing is disabled by default in this new repository. Before enabling it:

1. Configure the existing `happenstance` PyPI project's trusted publisher for owner `happenstance-ai`, repository `happenstance-cli`, workflow `publish-hpn-cli.yml`, and environment `pypi`. Keep the old publisher until the backend removal is ready to merge.
2. Configure the GitHub `pypi` environment with the existing release policy: allow the `main` branch and `hpn-cli-v*` tags.
3. Provide `HOMEBREW_APP_ID` and `HOMEBREW_APP_PRIVATE_KEY` to this repository's release jobs. The GitHub App must have Contents read/write access to `happenstance-ai/homebrew-tap`. Secret values do not transfer with Git history.
4. Verify the new repository's CI and release access, then set the repository variable `CLI_PUBLISH_ENABLED` to `true`.
5. Coordinate the backend removal PR and retirement of the old PyPI publisher so there is one release source.

Moving this source does not affect existing installations: pip, uv, and Homebrew download already-published artifacts from PyPI. No package name, command name, or API endpoint changes are required.

## Publishing

After the migration is complete:

1. Update `version` in `pyproject.toml` and `__version__` in `hpn_cli/__init__.py`, and refresh `uv.lock` with `uv lock`.
2. Merge to `main` and confirm CI passes.
3. Create and push `hpn-cli-v<VERSION>` for the new version. Do not recreate an already-published version.
4. The workflow checks that the tag matches the package version, builds the package, publishes to PyPI through OIDC, and updates the Homebrew tap.

To preview a Homebrew formula for an already-published version:

```bash
python homebrew/generate_formula.py 0.2.3
```

The repository was extracted from the backend's `hpn_cli/` directory with its history. Historical commits predating packaging may still refer to the old monorepo layout.
