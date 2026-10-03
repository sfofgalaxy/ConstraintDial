#!/usr/bin/env python3
"""Build detect trees for admitted families when a file+function gold is recoverable."""

from __future__ import annotations

import json
import re
from pathlib import Path

from lib import GOLD_DIR, TASKS, V3, detect_match, locate_p0
from build_family import build_one
from run_gold import detect_gates

ADMITTED = [
    "0001", "0002", "0004", "0005", "0009", "0020", "0024", "0026", "0032", "0033",
    "0035", "0039", "0043", "0086", "0094", "0109", "0115", "0140", "0154", "0158",
    "0159", "0170", "0176", "0180", "0208", "0417", "0698", "0775", "0804", "0990",
    "0039", "0084", "0092", "0157", "0173", "0194", "0201", "0210", "0239", "0240",
    "0248", "0249", "0262", "0270", "0276", "0277",
    "0301", "0302", "0303", "0312", "0316", "0317", "0645", "0670", "0791",
    "0235", "0311", "0320", "0347",
]
FN_RE = re.compile(r"\b([A-Z][A-Za-z0-9]+)\.([a-zA-Z_][a-zA-Z0-9_]*)\b")
SOL_RE = re.compile(r"\b([A-Za-z0-9_]+)\.sol\b")


def family_text(sid: str) -> str:
    chunks = []
    for name in (f"4000-{sid}-b1-case", f"4000-{sid}-b2-case", f"4000-{sid}-case"):
        for base in (TASKS, V3):
            p = base / name
            if not p.exists():
                continue
            for rel in ("mutant.json", "oracle/spec.md"):
                f = p / rel
                if f.exists():
                    chunks.append(f.read_text(errors="ignore"))
    return "\n".join(chunks)


def recover_gold(sid: str) -> dict | None:
    p0 = locate_p0(sid)
    sols = {p.name: p.read_text() for p in (p0 / "contracts").glob("*.sol")}
    if not sols:
        return None
    text = family_text(sid)
    files = []
    functions = []
    contracts = []
    for match in SOL_RE.finditer(text):
        name = match.group(1) + ".sol"
        if name in sols:
            files.append(name)
    for match in FN_RE.finditer(text):
        contract, fn = match.group(1), match.group(2)
        for name, src in sols.items():
            if f"contract {contract}" in src and f"function {fn}(" in src:
                files.append(name)
                contracts.append(contract)
                functions.append(fn)
    files = list(dict.fromkeys(files))
    functions = list(dict.fromkeys(functions))
    contracts = list(dict.fromkeys(contracts))
    if not files or not functions:
        return None
    return {
        "family_id": sid,
        "parent_task": f"4000-{sid}-case",
        "files": files[:2],
        "contracts": contracts[:2],
        "functions": functions[:3],
        "recovered": True,
        "paper": "leave [TBD]",
    }


def main() -> None:
    built = []
    skipped = []
    failed = []
    seen = set()
    for sid in ADMITTED:
        if sid in seen:
            continue
        seen.add(sid)
        gold_path = GOLD_DIR / f"{sid}.json"
        if not gold_path.exists():
            recovered = recover_gold(sid)
            if recovered is None:
                skipped.append(sid)
                continue
            gold_path.write_text(json.dumps(recovered, indent=2) + "\n")
        try:
            build_one(sid, kinds=("detect",))
            row = detect_gates(sid)
            if not row["ok"]:
                failed.append(sid)
            else:
                built.append(sid)
            print(json.dumps(row, ensure_ascii=False), flush=True)
        except Exception as exc:
            failed.append(sid)
            print("FAIL", sid, type(exc).__name__, str(exc)[:200], flush=True)
    out = {
        "paper": "leave [TBD]",
        "built_detect": built,
        "skipped_no_gold": skipped,
        "failed": failed,
        "n_built": len(built),
    }
    (Path(__file__).resolve().parent / "scale_detect.json").write_text(json.dumps(out, indent=2) + "\n")
    print("SCALE_DETECT", json.dumps(out))


if __name__ == "__main__":
    main()
