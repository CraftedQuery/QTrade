"""Repository hygiene: acceptance test #5 and the secret-handling rules."""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


def tracked_files() -> list[str]:
    """Every file git currently tracks."""
    git = shutil.which("git")
    if git is None:  # pragma: no cover - git is present in every supported environment
        pytest.skip("git executable not found")
    result = subprocess.run(  # noqa: S603
        [git, "ls-files"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return [line for line in result.stdout.splitlines() if line]


def test_env_file_is_not_tracked() -> None:
    """Acceptance test #5: .env is absent from git."""
    assert ".env" not in tracked_files()


def test_gitignore_covers_env() -> None:
    ignored = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert ".env" in ignored


def test_env_example_is_tracked_and_empty_of_values() -> None:
    """The template ships with placeholder names only, never populated secrets."""
    example = REPO_ROOT / ".env.example"
    assert ".env.example" in tracked_files()
    for line in example.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        key, _, value = stripped.partition("=")
        if key in {"ALPACA_PAPER_BASE_URL", "LAB_ENV", "LAB_DATA_DIR", "LAB_ARTIFACT_DIR"}:
            continue
        assert value == "", f"{key} in .env.example must have no value"


def test_env_example_names_no_live_endpoint() -> None:
    """Paper only: the live trading host must not appear in the template."""
    text = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")
    assert "https://api.alpaca.markets" not in text
    assert "paper-api.alpaca.markets" in text


SECRET_PATTERNS = {
    "alpaca key id": re.compile(r"\bAK[A-Z0-9]{16,}\b"),
    "aws access key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "openai style key": re.compile(r"\bsk-[A-Za-z0-9]{32,}\b"),
    "private key block": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
}

TEXT_SUFFIXES = {".py", ".md", ".toml", ".yaml", ".yml", ".json", ".example", ".txt", ".lock"}


@pytest.mark.parametrize("label,pattern", sorted(SECRET_PATTERNS.items()))
def test_no_secret_shaped_strings_in_tracked_files(label: str, pattern: re.Pattern[str]) -> None:
    offenders = []
    for relative in tracked_files():
        path = REPO_ROOT / relative
        if path.suffix not in TEXT_SUFFIXES or path == Path(__file__):
            continue
        if pattern.search(path.read_text(encoding="utf-8", errors="ignore")):
            offenders.append(relative)
    assert not offenders, f"possible {label} committed in: {offenders}"


def test_package_is_importable_from_src_layout() -> None:
    import lab
    from lab import contracts

    assert lab.__version__
    assert len(contracts.CONTRACTS) == 9
