#!/usr/bin/env python3
"""Build and locally gate new root-cause patch trees. Paper stays [TBD]."""
from __future__ import annotations

import json
from pathlib import Path

from build_family import build_one
from run_gold import detect_gates, patch_gates

SIDS = ("1056", "0997")
HERE = Path(__file__).resolve().parent


def main() -> None:
    rows = []
    port = 20400
    for sid in SIDS:
        build_one(sid, kinds=("patch",))
        d = detect_gates(sid)
        rows.append(d)
        print(json.dumps(d, ensure_ascii=False), flush=True)
        p = patch_gates(sid, port)
        rows.append({k: v for k, v in p.items() if k != "log_tail"})
        print(json.dumps(rows[-1], ensure_ascii=False), flush=True)
        if not p["ok"]:
            print("PATCH_LOG", p.get("log_tail"), flush=True)
        port += 20
    out = {"paper": "leave [TBD]", "sids": list(SIDS), "rows": rows}
    (HERE / "new_patch_gates.json").write_text(json.dumps(out, indent=2) + "\n")
    if not all(r["ok"] for r in rows):
        raise SystemExit("new patch gates failed")
    print("NEW_PATCH_GATES_OK")


if __name__ == "__main__":
    main()
