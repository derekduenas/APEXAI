"""The repository must actually contain the code it claims to contain.

WHY THIS FILE EXISTS

`.gitignore` carried a bare `data/` line. Git patterns without a leading slash
match at ANY depth, so it silently excluded `apex/data/` -- the entire data
adapter package: base, synthetic, sharadar, identity, crosscheck. Five commits
described work that was never committed, and a clean clone could not import
`apex.data` at all, so the whole suite failed at collection.

Nothing caught it because every test ran against the WORKING TREE, where the
files exist. A green local suite said nothing about what was in the repository.

These tests close that gap: they ask git what is tracked, not the filesystem.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent


def _git(*args) -> str:
    return subprocess.run(
        ["git", "-C", str(REPO), *args], capture_output=True, text=True, check=True
    ).stdout


def _tracked() -> set:
    return {line for line in _git("ls-files").splitlines() if line}


def test_every_python_module_in_the_package_is_tracked():
    """The exact failure that shipped: source present locally, absent from git."""
    tracked = _tracked()
    on_disk = {
        str(p.relative_to(REPO))
        for p in (REPO / "apex").rglob("*.py")
        if "__pycache__" not in p.parts
    }

    untracked = sorted(on_disk - tracked)
    assert not untracked, (
        f"{len(untracked)} module(s) exist on disk but are NOT in version control:\n  "
        + "\n  ".join(untracked)
        + "\n\nA clean clone would be missing them. Check .gitignore for an "
        "unanchored pattern -- a bare `name/` matches at every depth."
    )


def test_every_test_module_is_tracked():
    tracked = _tracked()
    on_disk = {
        str(p.relative_to(REPO))
        for p in (REPO / "tests").rglob("*.py")
        if "__pycache__" not in p.parts
    }

    assert not sorted(on_disk - tracked), "test modules missing from version control"


def test_config_and_registration_documents_are_tracked():
    tracked = _tracked()

    for required in (
        "APEX-Research-Protocol-v1.0-Experiment-001.md",
        "CONVENTIONS.md",
        "config/experiment.yaml",
        "config/costs.yaml",
        "config/sharadar.yaml",
    ):
        assert required in tracked, f"{required} is not under version control"


def test_no_package_directory_is_ignored():
    """Directly interrogate git's ignore rules for every package directory."""
    packages = sorted(
        {str(p.parent.relative_to(REPO)) for p in (REPO / "apex").rglob("__init__.py")}
    )
    assert packages, "no packages found -- the test is looking in the wrong place"

    for package in packages:
        result = subprocess.run(
            ["git", "-C", str(REPO), "check-ignore", "-q", package],
            capture_output=True,
        )
        assert result.returncode != 0, (
            f"package directory '{package}' is IGNORED by .gitignore and will "
            f"never be committed"
        )


def test_raw_vendor_snapshots_stay_ignored():
    """The other direction: large raw data must NOT be committed."""
    result = subprocess.run(
        ["git", "-C", str(REPO), "check-ignore", "-q", "data/snapshots/sharadar/x/SEP.csv"],
        capture_output=True,
    )
    assert result.returncode == 0, (
        "raw vendor snapshots are no longer ignored; a multi-gigabyte export "
        "could be committed by accident"
    )


def test_no_credential_reaches_the_repository():
    """No tracked file may contain something shaped like a live API key."""
    import re

    suspicious = re.compile(r"(api_key|apikey|auth_token)\s*[=:]\s*['\"][A-Za-z0-9]{20,}['\"]")

    offenders = []
    for relative in _tracked():
        path = REPO / relative
        if path.suffix not in {".py", ".yaml", ".yml", ".json", ".md", ".txt", ".cfg", ".toml"}:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for match in suspicious.finditer(text):
            # The test file's own synthetic constant is not a credential.
            if "FAKE_KEY" in text[max(0, match.start() - 120) : match.start()]:
                continue
            offenders.append(f"{relative}: {match.group(0)[:48]}")

    assert not offenders, "possible credential(s) committed:\n  " + "\n  ".join(offenders)


@pytest.mark.slow
def test_a_clean_clone_can_import_the_package(tmp_path):
    """The end-to-end version of the bug: does a fresh checkout actually work?"""
    clone = tmp_path / "clone"
    subprocess.run(
        ["git", "clone", "-q", str(REPO), str(clone)], check=True, capture_output=True
    )

    result = subprocess.run(
        [
            sys.executable, "-c",
            "import apex.data.synthetic, apex.data.sharadar, apex.data.identity; print('ok')",
        ],
        cwd=clone, capture_output=True, text=True,
    )
    assert result.returncode == 0, (
        f"a clean clone cannot import the package:\n{result.stderr}"
    )
