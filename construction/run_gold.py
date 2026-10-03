#!/usr/bin/env python3
"""Local gold gates for detect and patch. No model calls."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from lib import (
    PILOT,
    TASKS,
    apply_gold_patch,
    compile_contracts,
    detect_match,
    load_gold,
    locate_p0,
    lower_pragma,
    score_detect,
    write_artifact,
)

def run(cmd: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, cwd=str(cwd) if cwd else None)


def detect_gates(sid: str) -> dict:
    gold = load_gold(sid)
    task = TASKS / f"4000-{sid}-detect-case"
    held = task / "held" / "detect_gold.json"
    empty = score_detect(task / "missing.json", gold)
    wrong = {"files": ["Unrelated.sol"], "functions": ["pause"]}
    gold_pred = {"files": gold["files"], "functions": gold["functions"]}
    ok_empty = empty["verdict"] == "failure"
    ok_wrong = not detect_match(wrong, gold)
    ok_gold = detect_match(gold_pred, json.loads(held.read_text()))
    leak = (task / "prompt.md").read_text()
    leak_ok = "Vulnerability category" not in leak and "Target objective" not in leak
    return {
        "sid": sid,
        "kind": "detect",
        "ok": ok_empty and ok_wrong and ok_gold and leak_ok,
        "empty_fails": ok_empty,
        "wrong_fails": ok_wrong,
        "gold_matches": ok_gold,
        "leak_free": leak_ok,
    }


def patch_gates(sid: str, port: int) -> dict:
    gold = load_gold(sid)
    src = locate_p0(sid)
    work = Path(__file__).resolve().parent / "_work" / sid
    if work.exists():
        shutil.rmtree(work)
    work.parent.mkdir(parents=True, exist_ok=True)
    try:
        shutil.copytree(src, work, symlinks=False)
        task = work
        lower_pragma(task)
        target = gold["files"][0]
        sol = task / "contracts" / target
        sol.write_text(apply_gold_patch(sol.read_text(), sid))
        compiled = compile_contracts(
            task / "contracts",
            gold["compile"]["files"],
            gold["compile"]["wanted"],
        )
        name = gold["compile"]["wanted"][0]
        write_artifact(
            task / "artifacts" / gold["compile"]["artifact"],
            name,
            compiled[name],
            src / "artifacts" / gold["compile"]["artifact"],
        )
        held = TASKS / f"4000-{sid}-patch-case" / "held"
        (task / "held").mkdir(exist_ok=True)
        shutil.copyfile(held / "parent_solve.py", task / "held" / "parent_solve.py")
        shutil.copyfile(held / "honest_flow.py", task / "held" / "honest_flow.py")
        unlock = held / "honest_unlock.txt"
        if unlock.exists():
            shutil.copyfile(unlock, task / "held" / "honest_unlock.txt")
        held_art = held / "artifacts"
        if held_art.is_dir():
            dst_art = task / "held" / "artifacts"
            dst_art.mkdir(exist_ok=True)
            for item in held_art.iterdir():
                if item.is_file():
                    shutil.copyfile(item, dst_art / item.name)
        patch = run([str(Path(__file__).resolve().parent / "run_patch_gates.sh"), str(task), str(port)])
        return {
            "sid": sid,
            "kind": "patch",
            "ok": patch.returncode == 0,
            "parent_solve_killed": "parent solve failed as required" in (patch.stdout + patch.stderr),
            "honest_ok": "honest gate OK" in (patch.stdout + patch.stderr),
            "log_tail": (patch.stdout + patch.stderr)[-1200:],
        }
    finally:
        shutil.rmtree(work, ignore_errors=True)


def main() -> None:
    rows = []
    port = 20100
    for sid in ("0990", "0804"):
        d = detect_gates(sid)
        rows.append(d)
        print(json.dumps(d, ensure_ascii=False))
        p = patch_gates(sid, port)
        rows.append(p)
        print(json.dumps({k: v for k, v in p.items() if k != "log_tail"}, ensure_ascii=False))
        if not p["ok"]:
            print("PATCH_LOG", p.get("log_tail"))
        port += 20
    out = Path(__file__).resolve().parent / "gold_smoke.json"
    out.write_text(json.dumps({"paper": "leave [TBD]", "rows": rows}, indent=2) + "\n")
    if not all(r["ok"] for r in rows):
        raise SystemExit("gold smoke failed")
    print("DETECT_PATCH_GOLD_OK")


if __name__ == "__main__":
    main()
