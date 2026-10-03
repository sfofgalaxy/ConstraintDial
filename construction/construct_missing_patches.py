#!/usr/bin/env python3
"""Construct a Patch package per missing case version and keep only gate passes."""
from __future__ import annotations

import json
import os
import re
import shutil
import sys
import time
import urllib.error
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
from construct_dep_queue import (  # noqa: E402
    ask_json,
    function_excerpt,
    parent_solve,
    parse_json,
    version_src,
)
from paths import pilot  # noqa: E402

VERSIONS = ("", "eq", "b1", "b2", "b12")


def eoa_guard(text: str, functions: list[str]) -> tuple[str, str] | None:
    """Block contract callers at the first vulnerable function. Skip if already present."""
    for name in functions:
        match = re.search(rf"function\s+{re.escape(name)}\s*\(", text)
        start = match.start() if match else -1
        if start < 0:
            continue
        brace = text.find("{", start)
        if brace < 0:
            continue
        old = text[start:brace + 1]
        if text.count(old) != 1:
            continue
        window = text[brace:brace + 200]
        if "tx.origin" in window:
            continue
        return old, old + '\n        require(msg.sender == tx.origin, "eoa");'
    return None


def task_name(sid: str, ver: str) -> str:
    if not ver:
        return f"4000-{sid}-patch-case"
    return f"4000-{sid}-{ver}-patch-case"


def packaged(sid: str, ver: str) -> bool:
    dst = TASKS / task_name(sid, ver)
    return dst.is_dir() and not dst.is_symlink() and (dst / "task_kind.json").is_file()


def construct(sid: str, ver: str, port: int) -> str:
    if packaged(sid, ver):
        return "kept"
    src = version_src(sid, ver)
    if src is None:
        return "no_parent"
    gold = load_gold(sid)
    sol_rel = gold["files"][0]
    contracts = src / "contracts"
    chosen = contracts / sol_rel
    text = chosen.read_text(errors="ignore") if chosen.is_file() else ""
    names = list(gold["functions"])
    if not any(f"function {name}(" in text or f"function {name} " in text for name in names):
        names = [{"onFlash": "invokeCallback"}.get(name, name) for name in names]
    if not any(f"function {name}(" in text or f"function {name} " in text for name in names):
        for sol in sorted(contracts.glob("*.sol")):
            body = sol.read_text(errors="ignore")
            if any(f"function {name}(" in body or f"function {name} " in body for name in names):
                sol_rel = sol.name
                text = body
                break
    gold = dict(gold)
    gold["functions"] = names
    sol = contracts / sol_rel
    if not sol.is_file():
        return "missing_file"
    excerpts = [function_excerpt(text, name) for name in gold["functions"]]
    excerpts = [chunk for chunk in excerpts if chunk]
    if not excerpts:
        aliases = {"onFlash": "invokeCallback"}
        renamed = [aliases.get(name, name) for name in gold["functions"]]
        if renamed != list(gold["functions"]):
            gold = dict(gold)
            gold["functions"] = renamed
            excerpts = [chunk for chunk in (function_excerpt(text, name) for name in renamed) if chunk]
    if not excerpts:
        return "gold_mismatch"
    solve = src / "solution" / "solve.py"
    attack = solve.read_text(errors="ignore")[-2500:] if solve.is_file() else ""
    feedback = ""
    status = "not_tried"
    # Keep the work tree inside the repo. Some bootstraps only walk a few
    # parents to find infra/, and /tmp is not one of those parents.
    work = pilot() / "eval" / "dep-completion" / "_patch_work" / f"{sid}-{ver or 'p0'}-{port}"
    for _attempt in range(6):
        prompt = (
            "The parent attack below already succeeds against this function. "
            "Propose the smallest Solidity edit that makes that attack fail "
            "while an ordinary call on this same contract still succeeds. "
            "The old string must be copied exactly once from the function source "
            "and the new string must still compile as Solidity.\n"
            + "\n\n".join(excerpts[:3])
            + "\n\nParent attack script tail:\n"
            + attack
            + feedback
            + '\n\nReply with one JSON object and no markdown: {"old":"...","new":"..."}'
        )
        attack_uses_contract = bool(
            re.search(
                r"deploy|create2|Contract\(|solcx|compile_source|solution[/\\]artifacts",
                attack,
                re.I,
            )
        )
        guard = (
            eoa_guard(text, list(gold["functions"]))
            if _attempt == 0 and attack_uses_contract
            else None
        )
        if guard:
            old, new = guard
        else:
            try:
                parsed = parse_json(ask_json(prompt))
            except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as exc:
                status = "error:" + type(exc).__name__
                feedback = "\nPrevious request failed before an edit was produced. Try the same task again.\n"
                time.sleep(2 + _attempt)
                continue
            old, new = str(parsed.get("old") or ""), str(parsed.get("new") or "")
        if not old or old not in text or text.count(old) != 1 or old == new:
            status = "needle_rejected"
            feedback = "\nPrevious edit was rejected: old must occur exactly once in the source.\n"
            continue
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
            status = "compile_failed"
            feedback = "\nPrevious edit failed to compile:\n" + str(exc)[:500] + "\n"
            continue
        parent_solve(src, work)
        if not (work / "held" / "parent_solve.py").is_file():
            shutil.rmtree(work, ignore_errors=True)
            return "missing_parent_solve"
        checked = probe_and_check(
            work, sid, port, set(gold.get("functions") or []), set(gold.get("contracts") or [])
        )
        status = checked.get("status") or "gate_failed"
        if status == "one_init_pass":
            break
        feedback = (
            f"\nPrevious edit status: {status}. The attack still succeeds or the ordinary call failed.\n"
            "Do not use tx.origin or msg.sender == tx.origin. The parent attack is sent by an externally owned account, so that check does not stop it. "
            "Change the vulnerable condition itself.\n"
            + (checked.get("detail") or "")
            + "\n"
        )
        shutil.rmtree(work, ignore_errors=True)
    else:
        return status
    if status != "one_init_pass":
        return status
    dst = TASKS / task_name(sid, ver)
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
        "parent_task_id": src.name,
        "grade": "base call succeeds, parent attack fails, call is not the objective",
        "honest_call": checked.get("call"),
        "paper": "leave [TBD]",
    }, indent=2) + "\n")
    link_v3(task_name(sid, ver))
    shutil.rmtree(work, ignore_errors=True)
    return "built"


def main() -> None:
    ids = [item for item in os.environ.get("PATCH_IDS", "").split(",") if item]
    port = int(os.environ.get("CONSTRUCT_GATE_PORT", "36000"))
    built = 0
    for sid in ids:
        for ver in VERSIONS:
            try:
                status = construct(sid, ver, port)
            except Exception as exc:
                status = "error:" + type(exc).__name__
            print(sid, ver or "p0", status, flush=True)
            if status == "built":
                built += 1
    print("MISSING_PATCH_DONE", built, flush=True)


if __name__ == "__main__":
    main()
