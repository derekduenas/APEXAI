"""Configuration loading, validation and hashing.

Every parameter the pipeline uses arrives through here. The code body contains
no magic numbers; if a number changes a result, it lives in config/ and is
covered by `Config.hash`, which is stamped on every RunResult.

Access is deliberately dict-like rather than attribute-like: a typo in a key
raises immediately with the key name, instead of silently returning a default.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = REPO_ROOT / "config"


class ConfigError(KeyError):
    """A configuration key was missing or invalid. Never defaulted."""


def _canonical(obj: Any) -> str:
    """Deterministic serialisation for hashing: sorted keys, no whitespace drift."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


@dataclass(frozen=True)
class Config:
    """A validated, hashed configuration tree."""

    data: dict
    sources: tuple[str, ...]

    def __getitem__(self, key: str) -> Any:
        return self.get(key)

    def get(self, dotted: str) -> Any:
        """Fetch by dotted path. Raises on a missing key -- never returns a default.

        A default here would be a magic number smuggled into the code body.
        """
        node: Any = self.data
        walked: list[str] = []
        for part in dotted.split("."):
            walked.append(part)
            if not isinstance(node, dict) or part not in node:
                raise ConfigError(
                    f"missing config key '{dotted}' (failed at '{'.'.join(walked)}'); "
                    f"loaded from {list(self.sources)}"
                )
            node = node[part]
        return node

    def section(self, dotted: str) -> dict:
        node = self.get(dotted)
        if not isinstance(node, dict):
            raise ConfigError(f"config key '{dotted}' is not a section")
        return node

    @property
    def hash(self) -> str:
        return hashlib.sha256(_canonical(self.data).encode("utf-8")).hexdigest()

    def period(self, name: str) -> dict:
        return self.section(f"periods.{name}")

    def cost_profile(self, name: str | None = None) -> dict:
        profile = name or self.get("default_profile")
        return self.section(f"profiles.{profile}")

    def cost_bps_per_side(self, name: str | None = None) -> float:
        p = self.cost_profile(name)
        for key in ("commission_bps", "half_spread_bps", "slippage_bps"):
            if key not in p:
                raise ConfigError(f"cost profile missing '{key}'")
        return float(p["commission_bps"] + p["half_spread_bps"] + p["slippage_bps"])


def load_config(*names: str, config_dir: Path | None = None) -> Config:
    """Load and merge one or more YAML files from config/.

    Merging is shallow-by-top-level-key and rejects collisions outright: two
    files silently overwriting the same key is exactly how a frozen parameter
    quietly changes.
    """
    directory = config_dir or CONFIG_DIR
    merged: dict = {}
    loaded: list[str] = []
    for name in names:
        path = directory / f"{name}.yaml"
        if not path.exists():
            raise ConfigError(f"config file not found: {path}")
        with path.open("r", encoding="utf-8") as fh:
            parsed = yaml.safe_load(fh)
        if not isinstance(parsed, dict):
            raise ConfigError(f"config file {path} did not parse to a mapping")
        collisions = set(parsed) & set(merged)
        if collisions:
            raise ConfigError(
                f"config key collision between {loaded} and {name}: {sorted(collisions)}"
            )
        merged.update(parsed)
        loaded.append(name)
    return Config(data=merged, sources=tuple(loaded))


def git_sha(repo_root: Path | None = None) -> str:
    """Current commit SHA, or an explicit marker. Stamped on every RunResult."""
    root = repo_root or REPO_ROOT
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return "GIT-UNAVAILABLE"
    if result.returncode != 0:
        return "GIT-UNAVAILABLE"
    sha = result.stdout.strip()
    dirty = subprocess.run(
        ["git", "-C", str(root), "status", "--porcelain"],
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    if dirty.stdout.strip():
        return f"{sha}-DIRTY"
    return sha


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def frame_hash(*frames) -> str:
    """Stable hash of one or more DataFrames, for the RunResult data_hash."""
    digest = hashlib.sha256()
    for frame in frames:
        digest.update(_canonical(list(map(str, frame.columns))).encode("utf-8"))
        digest.update(_canonical([str(i) for i in frame.index]).encode("utf-8"))
        digest.update(frame.to_numpy(dtype="float64", na_value=float("nan")).tobytes())
    return digest.hexdigest()
