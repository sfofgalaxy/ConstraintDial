#!/usr/bin/env python3
"""Build remaining detect trees, drop incomplete patch trees, gate 0320/0347.

Paper stays [TBD].
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from lib import GOLD_DIR, TASKS
from build_family import build_one
from run_gold import detect_gates

KEEP_PATCH = {"0990", "0804", "0302", "0235", "1056", "0997"}


def main() -> None:
    removed = []
    for patch in sorted(TASKS.glob("4000-*-patch-case")):
        sid = patch.name.split("-")[1]
        held = patch / "held" / "gold_patch"
        if sid not in KEEP_PATCH or not held.is_dir():
            shutil.rmtree(patch)
            link = Path(str(patch).replace("/tasks/", "/tasks-v3/"))
            if link.is_symlink():
                link.unlink()
            removed.append(patch.name)
            print("removed", patch.name)
    built = []
    failed = []
    for gold in sorted(GOLD_DIR.glob("*.json")):
        sid = gold.stem
        detect = TASKS / f"4000-{sid}-detect-case"
        if not detect.is_dir():
            try:
                build_one(sid, kinds=("detect",))
                built.append(sid)
            except Exception as exc:
                failed.append({"sid": sid, "error": f"{type(exc).__name__}: {exc}"[:240]})
                print("FAIL build", sid, exc)
                continue
        try:
            row = detect_gates(sid)
            print(json.dumps(row, ensure_ascii=False), flush=True)
            if not row["ok"]:
                failed.append({"sid": sid, "error": "detect_gates"})
        except Exception as exc:
            failed.append({"sid": sid, "error": f"{type(exc).__name__}: {exc}"[:240]})
    out = {
        "paper": "leave [TBD]",
        "removed_incomplete_patch": removed,
        "built_detect": built,
        "failed": failed,
    }
    Path(__file__).resolve().parent.joinpath("finish_remaining.json").write_text(
        json.dumps(out, indent=2) + "\n"
    )
    print("FINISH_REMAINING", json.dumps(out))


if __name__ == "__main__":
    main()
