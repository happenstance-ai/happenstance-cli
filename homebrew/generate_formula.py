#!/usr/bin/env python3
"""Generate a Homebrew formula for the happenstance CLI.

Queries PyPI for the package release and reads all dependency versions and
source archives from uv.lock, then outputs a complete Homebrew formula to
stdout. Using the lockfile keeps a release reproducible when newer dependency
versions appear on PyPI.

The output mirrors what `brew update-python-resources` produces: source
distributions for every resource (Homebrew installs with
--no-binary=:all:), the current Homebrew default Python, and the standard
`virtualenv_install_with_resources` helper. Bump PYTHON_VERSION when
Homebrew moves its default Python; `brew audit --strict` flags the formula
when it falls behind.

Usage:
    python generate_formula.py 0.2.0
    python generate_formula.py 0.2.0 > Formula/happenstance.rb
"""

import json
import re
import sys
import tomllib
import urllib.request
from collections import deque
from pathlib import Path

# Homebrew's current default Python. Must match a python@X.Y formula.
PYTHON_VERSION = "3.14"
LOCK_PATH = Path(__file__).resolve().parents[1] / "uv.lock"


def pypi_json(package, version=None):
    """Fetch package metadata from the PyPI JSON API."""
    if version:
        url = f"https://pypi.org/pypi/{package}/{version}/json"
    else:
        url = f"https://pypi.org/pypi/{package}/json"
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())


def sdist_info(pypi_data):
    """Return (url, sha256) for the source distribution."""
    name = pypi_data["info"]["name"]
    version = pypi_data["info"]["version"]
    for f in pypi_data["urls"]:
        if f["packagetype"] == "sdist":
            return f["url"], f["digests"]["sha256"]
    raise LookupError(f"No sdist found for {name}=={version}")


def _normalize(name):
    """PEP 503 normalize."""
    return re.sub(r"[-_.]+", "-", name).lower()


def _select_locked_package(packages_by_name, dependency):
    """Resolve one uv.lock dependency reference to its package entry."""
    name = _normalize(dependency["name"])
    candidates = packages_by_name.get(name, [])
    version = dependency.get("version")
    if version:
        candidates = [pkg for pkg in candidates if pkg["version"] == version]
    if len(candidates) != 1:
        detail = f"{dependency['name']}=={version}" if version else dependency["name"]
        raise LookupError(f"Expected one locked package for {detail}, found {len(candidates)}")
    return candidates[0]


def _validate_dependency_reference(dependency):
    """Reject lockfile dependency forms the formula generator cannot model."""
    if "marker" in dependency:
        raise ValueError(
            f"Dependency markers require explicit Homebrew handling: {dependency['name']}"
        )
    if "extra" in dependency:
        raise ValueError(
            f"Dependency extras require explicit Homebrew handling: {dependency['name']}"
        )


def collect_deps(root_package, root_version, lock_path=None):
    """Read all transitive dependencies from uv.lock (excluding root).

    Returns sorted list of (display_name, sdist_url, sha256).
    """
    lock_path = LOCK_PATH if lock_path is None else Path(lock_path)
    with lock_path.open("rb") as lock_file:
        lock = tomllib.load(lock_file)

    packages_by_name = {}
    for package in lock["package"]:
        packages_by_name.setdefault(_normalize(package["name"]), []).append(package)

    root = _select_locked_package(
        packages_by_name,
        {"name": root_package, "version": root_version},
    )
    visited = set()
    result = []
    queue = deque(root.get("dependencies", []))

    while queue:
        dependency = queue.popleft()
        _validate_dependency_reference(dependency)
        package = _select_locked_package(packages_by_name, dependency)
        key = _normalize(package["name"])
        if key in visited:
            continue
        visited.add(key)

        sdist = package.get("sdist")
        if not sdist:
            raise LookupError(
                f"No locked sdist found for {package['name']}=={package['version']}"
            )
        hash_algorithm, sha = sdist["hash"].split(":", 1)
        if hash_algorithm != "sha256":
            raise ValueError(
                f"Unsupported hash for {package['name']}=={package['version']}: "
                f"{hash_algorithm}"
            )
        result.append((package["name"], sdist["url"], sha))
        queue.extend(package.get("dependencies", []))

    result.sort(key=lambda t: t[0].lower())
    return result


def generate_formula(version):
    """Return a complete Homebrew formula string."""
    pkg = pypi_json("happenstance", version)
    pkg_url, pkg_sha = sdist_info(pkg)
    deps = collect_deps("happenstance", version)

    lines = [
        "class Happenstance < Formula",
        "  include Language::Python::Virtualenv",
        "",
        '  desc "Search your network and research people via the Happenstance CLI"',
        '  homepage "https://happenstance.ai"',
        f'  url "{pkg_url}"',
        f'  sha256 "{pkg_sha}"',
        '  license "MIT"',
        "",
        f'  depends_on "python@{PYTHON_VERSION}"',
    ]

    for name, url, sha in deps:
        lines += [
            "",
            f'  resource "{name}" do',
            f'    url "{url}"',
            f'    sha256 "{sha}"',
            "  end",
        ]

    lines += [
        "",
        "  def install",
        "    virtualenv_install_with_resources",
        "  end",
        "",
        "  test do",
        '    assert_match version.to_s, shell_output("#{bin}/hpn --version")',
        "",
        '    output = shell_output("#{bin}/hpn config set --api-key test-key")',
        '    assert_match \'"status": "ok"\', output',
        "",
        '    output = shell_output("#{bin}/hpn config show")',
        '    assert_match \'"api_key": "***"\', output',
        "  end",
        "end",
        "",  # trailing newline
    ]

    return "\n".join(lines)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} VERSION", file=sys.stderr)
        print(f"Example: {sys.argv[0]} 0.2.0", file=sys.stderr)
        sys.exit(1)

    # The formula already ends with a newline; print() would add a trailing
    # blank line, which `brew audit --strict` rejects.
    sys.stdout.write(generate_formula(sys.argv[1]))
