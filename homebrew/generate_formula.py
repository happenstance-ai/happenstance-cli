#!/usr/bin/env python3
"""Generate a Homebrew formula for the happenstance CLI.

Queries PyPI to resolve the package and all transitive dependencies,
then outputs a complete Homebrew formula to stdout.

Usage:
    python generate_formula.py 0.2.0
    python generate_formula.py 0.2.0 > Formula/happenstance.rb
"""

import json
import re
import sys
import urllib.request


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


def parse_deps(pypi_data):
    """Return list of required dependency names (excluding extras)."""
    requires = pypi_data["info"].get("requires_dist") or []
    names = []
    for req in requires:
        # Skip dependencies gated on extras
        if re.search(r"\bextra\s*==", req):
            continue
        # Package name is everything up to the first version/marker char
        m = re.match(r"^([A-Za-z0-9]([A-Za-z0-9._-]*[A-Za-z0-9])?)", req)
        if m:
            names.append(m.group(1))
    return names


def _normalize(name):
    """PEP 503 normalize."""
    return re.sub(r"[-_.]+", "-", name).lower()


def collect_deps(root_package, root_version):
    """Resolve all transitive dependencies (excluding root).

    Returns sorted list of (display_name, sdist_url, sha256).
    """
    visited = set()
    result = []
    queue = parse_deps(pypi_json(root_package, root_version))

    while queue:
        raw_name = queue.pop(0)
        key = _normalize(raw_name)
        if key in visited:
            continue
        visited.add(key)

        data = pypi_json(raw_name)
        url, sha = sdist_info(data)
        display_name = data["info"]["name"]
        result.append((display_name, url, sha))
        queue.extend(parse_deps(data))

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
        '  depends_on "python@3.12"',
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

    print(generate_formula(sys.argv[1]))
