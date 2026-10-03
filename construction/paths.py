"""Repository location. Values come from ConstraintDial/.env."""
from __future__ import annotations

import os
from pathlib import Path

ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


def load_env(path: Path = ENV_FILE) -> None:
    if not path.is_file():
        return
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        if key and key not in os.environ:
            os.environ[key] = value


load_env()


def repo_root() -> Path:
    raw = os.environ.get("CONSTRAINDIAL_REPO", "").strip()
    if not raw:
        raise SystemExit(f"Fill CONSTRAINDIAL_REPO in {ENV_FILE}")
    return Path(raw).expanduser().resolve()


def pilot() -> Path:
    return repo_root() / "experiments" / "lifelong-pilot"
