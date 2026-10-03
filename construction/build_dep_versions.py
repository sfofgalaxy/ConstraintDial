#!/usr/bin/env python3
"""Build Detect, and Patch where a root-cause edit exists, on every shipped version.

Same public case as Exploit: P0, Peq, K1, K2, K1+K2.
P0 detect/patch trees already named 4000-{sid}-detect-case / -patch-case are kept.
Other versions use 4000-{sid}-{ver}-detect-case and 4000-{sid}-{ver}-patch-case.
Independent inodes. Official parents stay untouched. Paper stays [TBD].
"""
from __future__ import annotations

import csv
import json
import sys
import traceback
from pathlib import Path

from build_family import finish_detect, finish_patch
from lib import TASKS, V3, apply_gold_patch, copy_tree, link_v3, load_gold

from paths import pilot

PLAN = pilot() / "eval" / "plan_v5"
FAM = PLAN / "families.csv"
LEDGER = PLAN / "dep_version_ledger.json"
VERSIONS = ("", "eq", "b1", "b2", "b12")
PATCH_READY = {"0990", "0804", "0302", "0235", "1056", "0997"}


def families() -> list[str]:
    ids = []
    seen = set()
    for row in csv.DictReader(FAM.open()):
        sid = row["family_id"]
        if sid not in seen:
            seen.add(sid)
            ids.append(sid)
    return ids


def version_src(sid: str, ver: str) -> Path:
    name = f"4000-{sid}-case" if not ver else f"4000-{sid}-{ver}-case"
    for base in (TASKS, V3):
        path = base / name
        if path.is_symlink() or not path.is_dir():
            continue
        real = path.resolve()
        if real.is_symlink() or not real.is_dir():
            continue
        return real
    raise FileNotFoundError(name)


def task_name(sid: str, ver: str, kind: str) -> str:
    if not ver:
        return f"4000-{sid}-{kind}-case"
    return f"4000-{sid}-{ver}-{kind}-case"


def gold_functions_present(src: Path, gold: dict) -> str | None:
    contracts = src / "contracts"
    texts = []
    for name in gold["files"]:
        sol = contracts / name
        if sol.is_file():
            texts.append(sol.read_text(errors="ignore"))
    if not texts and contracts.is_dir():
        texts = [p.read_text(errors="ignore") for p in contracts.glob("*.sol")]
    else:
        # Mutated versions keep the same functions but not always in files[0].
        texts.extend(p.read_text(errors="ignore") for p in contracts.glob("*.sol"))
    blob = "\n".join(texts)
    missing = [fn for fn in gold["functions"] if f"function {fn}" not in blob]
    if missing:
        return "function missing: " + ",".join(missing)
    return None


def already(dst: Path, kind: str) -> bool:
    marker = dst / "task_kind.json"
    if not (dst.is_dir() and marker.is_file() and not dst.is_symlink()):
        return False
    try:
        meta = json.loads(marker.read_text())
    except json.JSONDecodeError:
        return False
    return meta.get("kind") == kind


def build_detect(sid: str, ver: str, gold: dict) -> str:
    name = task_name(sid, ver, "detect")
    dst = TASKS / name
    if already(dst, "detect"):
        return "kept"
    src = version_src(sid, ver)
    reason = gold_functions_present(src, gold)
    if reason:
        return "filtered:" + reason
    print("copy", name, flush=True)
    copy_tree(src, dst)
    held_gold = dict(gold)
    held_gold["source_version"] = ver or "p0"
    held_gold["parent_task"] = f"4000-{sid}-case" if not ver else f"4000-{sid}-{ver}-case"
    finish_detect(dst, held_gold)
    link_v3(name)
    return "built"


def build_patch(sid: str, ver: str, gold: dict) -> str:
    if sid not in PATCH_READY:
        return "no_root_cause_edit"
    name = task_name(sid, ver, "patch")
    dst = TASKS / name
    if already(dst, "patch"):
        return "kept"
    src = version_src(sid, ver)
    try:
        apply_gold_patch((src / "contracts" / gold["files"][0]).read_text(), sid)
    except SystemExit as exc:
        return "filtered:" + str(exc)
    print("copy", name, flush=True)
    copy_tree(src, dst)
    try:
        finish_patch(dst, gold, src)
    except SystemExit as exc:
        if dst.exists():
            import shutil
            shutil.rmtree(dst, ignore_errors=True)
        link = V3 / name
        if link.is_symlink():
            link.unlink()
        return "filtered:" + str(exc)
    link_v3(name)
    return "built"


def main() -> None:
    wanted = sys.argv[1:]
    sids = families()
    if wanted:
        sids = [sid for sid in sids if sid in set(wanted)]
    rows = []
    for sid in sids:
        try:
            gold = load_gold(sid)
        except SystemExit as exc:
            rows.append({"family_id": sid, "kind": "detect", "version": "*", "status": f"no_gold:{exc}"})
            continue
        for ver in VERSIONS:
            label = ver or "p0"
            try:
                status = build_detect(sid, ver, gold)
            except (Exception, SystemExit) as exc:
                status = "error:" + str(exc)
                traceback.print_exc()
            rows.append({"family_id": sid, "kind": "detect", "version": label, "status": status})
            print(sid, "detect", label, status, flush=True)
            try:
                pstatus = build_patch(sid, ver, gold)
            except (Exception, SystemExit) as exc:
                pstatus = "error:" + str(exc)
                traceback.print_exc()
            rows.append({"family_id": sid, "kind": "patch", "version": label, "status": pstatus})
            print(sid, "patch", label, pstatus, flush=True)
    summary = {
        "paper": "leave [TBD]",
        "plan": "2026-09-23-v6",
        "n_rows": len(rows),
        "counts": {},
    }
    for row in rows:
        key = f"{row['kind']}:{row['status'].split(':')[0]}"
        summary["counts"][key] = summary["counts"].get(key, 0) + 1
    summary["rows"] = rows
    LEDGER.write_text(json.dumps(summary, indent=2) + "\n")
    print("LEDGER", summary["counts"], flush=True)


if __name__ == "__main__":
    main()
