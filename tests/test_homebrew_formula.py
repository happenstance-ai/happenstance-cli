import textwrap

import pytest

from homebrew import generate_formula


ROOT_RELEASE = {
    "info": {"name": "happenstance", "version": "1.2.3"},
    "urls": [
        {
            "packagetype": "sdist",
            "url": "https://files.example/happenstance-1.2.3.tar.gz",
            "digests": {"sha256": "a" * 64},
        }
    ],
}


def write_lock(tmp_path, root_version="1.2.3"):
    lock_path = tmp_path / "uv.lock"
    lock_path.write_text(
        textwrap.dedent(
            f"""
            version = 1
            revision = 3
            requires-python = ">=3.11"

            [[package]]
            name = "happenstance"
            version = "{root_version}"
            source = {{ editable = "." }}
            dependencies = [
                {{ name = "requests" }},
                {{ name = "urllib3" }},
            ]

            [[package]]
            name = "requests"
            version = "2.33.1"
            source = {{ registry = "https://pypi.org/simple" }}
            dependencies = [
                {{ name = "certifi" }},
                {{ name = "urllib3" }},
            ]
            sdist = {{ url = "https://files.example/requests-2.33.1.tar.gz", hash = "sha256:{'b' * 64}" }}

            [[package]]
            name = "certifi"
            version = "2026.2.25"
            source = {{ registry = "https://pypi.org/simple" }}
            sdist = {{ url = "https://files.example/certifi-2026.2.25.tar.gz", hash = "sha256:{'c' * 64}" }}

            [[package]]
            name = "urllib3"
            version = "2.7.0"
            source = {{ registry = "https://pypi.org/simple" }}
            sdist = {{ url = "https://files.example/urllib3-2.7.0.tar.gz", hash = "sha256:{'d' * 64}" }}
            """
        ).lstrip()
    )
    return lock_path


def test_formula_uses_locked_dependency_versions(tmp_path, monkeypatch):
    lock_path = write_lock(tmp_path)
    calls = []

    def fake_pypi_json(package, version=None):
        calls.append((package, version))
        return ROOT_RELEASE

    monkeypatch.setattr(generate_formula, "pypi_json", fake_pypi_json)
    monkeypatch.setattr(generate_formula, "LOCK_PATH", lock_path)

    formula = generate_formula.generate_formula("1.2.3")

    assert calls == [("happenstance", "1.2.3")]
    assert "requests-2.33.1.tar.gz" in formula
    assert "certifi-2026.2.25.tar.gz" in formula
    assert "urllib3-2.7.0.tar.gz" in formula
    assert formula.count('resource "urllib3"') == 1


def test_formula_selects_explicit_version_when_lock_contains_two(tmp_path):
    lock_path = write_lock(tmp_path)
    contents = lock_path.read_text().replace(
        '{ name = "urllib3" }',
        '{ name = "urllib3", version = "2.7.0" }',
    )
    contents += textwrap.dedent(
        f"""

        [[package]]
        name = "urllib3"
        version = "2.8.0"
        source = {{ registry = "https://pypi.org/simple" }}
        sdist = {{ url = "https://files.example/urllib3-2.8.0.tar.gz", hash = "sha256:{'e' * 64}" }}
        """
    )
    lock_path.write_text(contents)

    dependencies = generate_formula.collect_deps("happenstance", "1.2.3", lock_path)

    urls = [url for _, url, _ in dependencies]
    assert "https://files.example/urllib3-2.7.0.tar.gz" in urls
    assert "https://files.example/urllib3-2.8.0.tar.gz" not in urls


@pytest.mark.parametrize(
    ("qualifier", "message"),
    [
        ('marker = "sys_platform == \'win32\'"', "markers require explicit"),
        ('extra = ["security"]', "extras require explicit"),
    ],
)
def test_formula_rejects_conditional_or_extra_dependencies(
    tmp_path, qualifier, message
):
    lock_path = write_lock(tmp_path)
    contents = lock_path.read_text().replace(
        '{ name = "requests" },',
        f'{{ name = "requests", {qualifier} }},',
        1,
    )
    lock_path.write_text(contents)

    with pytest.raises(ValueError, match=message):
        generate_formula.collect_deps("happenstance", "1.2.3", lock_path)


def test_formula_rejects_version_that_does_not_match_lock(tmp_path, monkeypatch):
    monkeypatch.setattr(generate_formula, "LOCK_PATH", write_lock(tmp_path))
    monkeypatch.setattr(generate_formula, "pypi_json", lambda *_: ROOT_RELEASE)

    with pytest.raises(LookupError, match="happenstance==1.2.4"):
        generate_formula.generate_formula("1.2.4")


def test_formula_rejects_dependency_without_locked_sdist(tmp_path):
    lock_path = write_lock(tmp_path)
    contents = lock_path.read_text().replace(
        f'sdist = {{ url = "https://files.example/certifi-2026.2.25.tar.gz", hash = "sha256:{"c" * 64}" }}',
        "",
    )
    lock_path.write_text(contents)

    with pytest.raises(LookupError, match="No locked sdist found for certifi==2026.2.25"):
        generate_formula.collect_deps("happenstance", "1.2.3", lock_path)
