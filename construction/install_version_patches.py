#!/usr/bin/env python3
"""Install a gated Patch task for every version whose source still has the edit."""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from build_family import PATCH_PROMPT  # noqa: E402
from lib import (  # noqa: E402
    TASKS,
    copy_tree,
    link_v3,
    load_gold,
    lower_pragma,
    refresh_artifacts,
)
from base_honest import probe_and_check  # noqa: E402
from construct_dep_queue import parent_solve, version_src  # noqa: E402

from paths import pilot

DEP = pilot() / "eval" / "dep-completion"
VERSIONS = ("", "eq", "b1", "b2", "b12")


def task_name(sid: str, ver: str) -> str:
    if not ver:
        return f"4000-{sid}-patch-case"
    return f"4000-{sid}-{ver}-patch-case"


def accepted_ids() -> list[str]:
    ids = []
    for path in sorted((DEP / "references").glob("*/patch_attempt.json")):
        row = json.loads(path.read_text())
        if row.get("accepted") is True and row.get("status") == "one_init_pass":
            ids.append(path.parent.name)
    return ids


def install_one(sid: str, ver: str, port: int) -> str:
    name = task_name(sid, ver)
    dst = TASKS / name
    if (dst / "task_kind.json").is_file() and not dst.is_symlink():
        return "kept"
    snippet = json.loads((DEP / "references" / sid / "patch_snippet.json").read_text())
    old, new = snippet["old"], snippet["new"]
    src = version_src(sid, ver)
    if src is None:
        return "no_parent"
    gold = load_gold(sid)
    sol_rel = gold["files"][0]
    sol = src / "contracts" / sol_rel
    if not sol.is_file():
        return "missing_file"
    text = sol.read_text(errors="ignore")
    if not old or old not in text or text.count(old) != 1 or old == new:
        return "needle_rejected"
    work = DEP / "_version_work" / f"{sid}-{ver or 'p0'}"
    if work.exists():
        shutil.rmtree(work)
    shutil.copytree(src, work, symlinks=False)
    lower_pragma(work)
    target = work / "contracts" / sol_rel
    target.write_text(target.read_text().replace(old, new, 1))
    try:
        refresh_artifacts(work, src, gold)
    except SystemExit as exc:
        shutil.rmtree(work, ignore_errors=True)
        return "compile_failed:" + str(exc)[:80]
    parent_solve(src, work)
    if not (work / "held" / "parent_solve.py").is_file():
        shutil.rmtree(work, ignore_errors=True)
        return "missing_parent_solve"
    checked = probe_and_check(
        work, sid, port, set(gold.get("functions") or []), set(gold.get("contracts") or [])
    )
    if checked.get("status") != "one_init_pass":
        shutil.rmtree(work, ignore_errors=True)
        return checked.get("status") or "gate_failed"
    if dst.exists():
        shutil.rmtree(dst)
    copy_tree(src, dst)
    held = dst / "held"
    held.mkdir(exist_ok=True)
    gold_dir = held / "gold_patch"
    gold_dir.mkdir(exist_ok=True)
    (gold_dir / sol_rel).write_text(text.replace(old, new, 1))
    shutil.copyfile(work / "held" / "parent_solve.py", held / "parent_solve.py")
    if (work / "held" / "honest_flow.py").is_file():
        shutil.copyfile(work / "held" / "honest_flow.py", held / "honest_flow.py")
    (dst / "prompt.md").write_text(PATCH_PROMPT)
    (dst / "task_kind.json").write_text(json.dumps({
        "kind": "patch",
        "family_id": sid,
        "parent_task_id": f"4000-{sid}-case" if not ver else f"4000-{sid}-{ver}-case",
        "grade": "base call succeeds, parent attack fails, call is not the objective",
        "honest_call": checked.get("call"),
        "paper": "leave [TBD]",
    }, indent=2) + "\n")
    link_v3(name)
    shutil.rmtree(work, ignore_errors=True)
    return "built"


def main() -> None:
    ids = sys.argv[1:] or accepted_ids()
    port = 31000
    built = 0
    for sid in ids:
        for ver in VERSIONS:
            status = install_one(sid, ver, port)
            port += 1
            print(sid, ver or "p0", status, flush=True)
            if status == "built":
                built += 1
    print("INSTALLED", built, flush=True)


if __name__ == "__main__":
    main()
