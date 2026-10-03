#!/usr/bin/env python3
"""Build detect and patch trees from a verified P0. Independent inodes."""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

from lib import (
    DETECT_PROMPT,
    PATCH_PROMPT,
    TASKS,
    V3,
    apply_gold_patch,
    copy_tree,
    link_v3,
    load_gold,
    locate_p0,
)

DETECT_JUDGE = '''#!/usr/bin/env python3
"""On-chain detect placeholder: clean state and exploit J both fail.

File grading is done by run_gold.py / the detect-patch runner after export.
"""
import json, os, sys
out = sys.argv[sys.argv.index("--out") + 1] if "--out" in sys.argv else "results/result.json"
os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
json.dump({"verdict": "failure", "checks": [{"name": "detect_not_onchain", "passed": False}]}, open(out, "w"))
print(json.dumps({"verdict": "failure"}))
'''


def finish_detect(dst: Path, gold: dict) -> None:
    (dst / "prompt.md").write_text(DETECT_PROMPT)
    held = dst / "held"
    held.mkdir(exist_ok=True)
    (held / "detect_gold.json").write_text(json.dumps(gold, indent=2) + "\n")
    (dst / "task_kind.json").write_text(json.dumps({
        "kind": "detect",
        "family_id": gold["family_id"],
        "parent_task_id": gold["parent_task"],
        "paper": "leave [TBD]",
    }, indent=2) + "\n")
    (dst / "judge" / "judge.py").write_text(DETECT_JUDGE)
    leak = (dst / "prompt.md").read_text()
    if "Vulnerability category" in leak or "Target objective" in leak:
        raise SystemExit("leaky detect prompt")


def finish_patch(dst: Path, gold: dict, src: Path) -> None:
    (dst / "prompt.md").write_text(PATCH_PROMPT)
    held = dst / "held"
    held.mkdir(exist_ok=True)
    gold_dir = held / "gold_patch"
    gold_dir.mkdir(exist_ok=True)
    target = gold["files"][0]
    text = (dst / "contracts" / target).read_text()
    (gold_dir / target).write_text(apply_gold_patch(text, gold["family_id"]))
    parent_solve = src / "solution" / "solve.py"
    if parent_solve.exists():
        (held / "parent_solve.py").write_bytes(parent_solve.read_bytes())
    for art_src in (src / "solution" / "artifacts", src / "held" / "artifacts"):
        if art_src.is_dir():
            dst_art = held / "artifacts"
            dst_art.mkdir(exist_ok=True)
            for item in art_src.iterdir():
                if item.is_file():
                    (dst_art / item.name).write_bytes(item.read_bytes())
    eq = TASKS / gold["parent_task"].replace("-case", "-eq-case")
    if not eq.exists():
        eq = V3 / gold["parent_task"].replace("-case", "-eq-case")
    honest = eq / "held" / "honest_flow.py"
    if honest.exists():
        (held / "honest_flow.py").write_bytes(honest.read_bytes())
        unlock = eq / "held" / "honest_unlock.txt"
        if unlock.exists():
            (held / "honest_unlock.txt").write_bytes(unlock.read_bytes())
    if gold["family_id"] == "0302":
        (held / "honest_flow.py").write_text(
            '''#!/usr/bin/env python3
"""Honest 0302: record owner points payout at the official receiver."""
import json, os, sys
TASK = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
def _root():
    probe = TASK
    for _ in range(8):
        if os.path.isfile(os.path.join(probe, "infra", "abi.py")):
            return probe
        probe = os.path.dirname(probe)
    return None
r = _root()
if r:
    sys.path.insert(0, r)
from infra.abi import encode_call
from infra.ethlite import EthLite
RPC_URL = os.environ.get("RPC_URL", "http://127.0.0.1:8545")
def main():
    rpc = EthLite(RPC_URL)
    info = json.load(open(os.path.join(TASK, "info.json")))
    attacker = info["unlocked"][0]
    payroll = info["contracts"]["SettlementPayroll"]
    receiver = info["contracts"]["StaffPayoutReceiver"]
    rpc.must_send(attacker, payroll, encode_call("setReceiver(uint256,address)", [3, receiver]))
    print("honest 0302 OK")
if __name__ == "__main__":
    main()
'''
        )
        info = json.loads((src / "info.json").read_text())
        (held / "honest_unlock.txt").write_text(info["unlocked"][0] + "\n")
    if gold["family_id"] == "0235":
        (held / "honest_flow.py").write_text(
            '''#!/usr/bin/env python3
"""Honest 0235: open one tranche and redeem it once."""
import json, os, sys
TASK = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
def _root():
    probe = TASK
    for _ in range(8):
        if os.path.isfile(os.path.join(probe, "infra", "abi.py")):
            return probe
        probe = os.path.dirname(probe)
    return None
r = _root()
if r:
    sys.path.insert(0, r)
from infra.abi import encode_call, decode_uint256
from infra.ethlite import EthLite
RPC_URL = os.environ.get("RPC_URL", "http://127.0.0.1:8545")
STAKE = 4_000 * 10 ** 8
def main():
    rpc = EthLite(RPC_URL)
    info = json.load(open(os.path.join(TASK, "info.json")))
    attacker = info["unlocked"][0]
    token = info["contracts"]["CollateralToken"]
    pool = info["contracts"]["LiquidityPool"]
    rpc.must_send(attacker, token, encode_call("approve(address,uint256)", [pool, STAKE]))
    tranche = decode_uint256(rpc.call(attacker, pool, encode_call("nextTrancheID()", [])))
    rpc.must_send(attacker, pool, encode_call("provide(uint256,uint256)", [STAKE, 0]))
    rpc.must_send(attacker, pool, encode_call("redeemUnhedged(uint256)", [tranche]))
    print("honest 0235 OK")
if __name__ == "__main__":
    main()
'''
        )
        info = json.loads((src / "info.json").read_text())
        (held / "honest_unlock.txt").write_text(info["unlocked"][0] + "\n")
    if gold["family_id"] == "1081":
        (held / "honest_flow.py").write_text(
            '''#!/usr/bin/env python3
"""Honest 1081: one subscribe and redeem of a small amount."""
import json, os, sys
TASK = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
def _root():
    probe = TASK
    for _ in range(8):
        if os.path.isfile(os.path.join(probe, "infra", "abi.py")):
            return probe
        probe = os.path.dirname(probe)
    return None
r = _root()
if r:
    sys.path.insert(0, r)
from infra.abi import encode_call, decode_uint256
from infra.ethlite import EthLite
RPC_URL = os.environ.get("RPC_URL", "http://127.0.0.1:8545")
UNIT = 10 ** 18
def main():
    rpc = EthLite(RPC_URL)
    info = json.load(open(os.path.join(TASK, "info.json")))
    entry = info["unlocked"][0]
    asset = info["contracts"]["SavingsAsset"]
    vault = info["contracts"]["SavingsVault"]
    small = UNIT
    rpc.must_send(entry, asset, encode_call("approve(address,uint256)", [vault, small]))
    rpc.must_send(entry, vault, encode_call("subscribe(uint256)", [small]))
    raw = rpc.call(entry, vault, encode_call("receipts()", []))
    receipts = "0x" + bytes(raw[12:32]).hex()
    credited = decode_uint256(rpc.call(entry, receipts, encode_call("balanceOf(address)", [entry])))
    rpc.must_send(entry, vault, encode_call("redeem(uint256)", [credited]))
    print("honest 1081 OK")
if __name__ == "__main__":
    main()
'''
        )
        info = json.loads((src / "info.json").read_text())
        (held / "honest_unlock.txt").write_text(info["unlocked"][0] + "\n")
    if gold["family_id"] == "1056":
        (held / "honest_flow.py").write_text(
            '''#!/usr/bin/env python3
"""Honest 1056: the unlocked account deposits and redeems its own units."""
import json, os, sys
TASK = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
def _root():
    probe = TASK
    for _ in range(8):
        if os.path.isfile(os.path.join(probe, "infra", "abi.py")):
            return probe
        probe = os.path.dirname(probe)
    return None
r = _root()
if r:
    sys.path.insert(0, r)
from infra.abi import encode_call, decode_uint256
from infra.ethlite import EthLite
RPC_URL = os.environ.get("RPC_URL", "http://127.0.0.1:8545")
UNIT = 10 ** 18
def main():
    rpc = EthLite(RPC_URL)
    info = json.load(open(os.path.join(TASK, "info.json")))
    attacker = info["unlocked"][0]
    vault = info["contracts"]["YieldVault"]
    router = info["contracts"]["SettlementRouter"]
    small = 100 * UNIT
    rpc.must_send(attacker, router, encode_call("deposit(uint256)", [small]))
    shares = decode_uint256(rpc.call(attacker, vault, encode_call("balanceOf(address)", [attacker])))
    rpc.must_send(attacker, router, encode_call("redeem(uint256,address)", [shares, attacker]))
    print("honest 1056 OK")
if __name__ == "__main__":
    main()
'''
        )
        info = json.loads((src / "info.json").read_text())
        (held / "honest_unlock.txt").write_text(info["unlocked"][0] + "\n")
    if gold["family_id"] == "0997":
        (held / "honest_flow.py").write_text(
            '''#!/usr/bin/env python3
"""Honest 0997: wrap a slice of shares and unwrap without a rate sync."""
import json, os, sys
TASK = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
def _root():
    probe = TASK
    for _ in range(8):
        if os.path.isfile(os.path.join(probe, "infra", "abi.py")):
            return probe
        probe = os.path.dirname(probe)
    return None
r = _root()
if r:
    sys.path.insert(0, r)
from infra.abi import encode_call, decode_uint256
from infra.ethlite import EthLite
RPC_URL = os.environ.get("RPC_URL", "http://127.0.0.1:8545")
UNIT = 10 ** 18
def main():
    rpc = EthLite(RPC_URL)
    info = json.load(open(os.path.join(TASK, "info.json")))
    attacker = info["unlocked"][0]
    vault = info["contracts"]["ShareVault"]
    wrapper = info["contracts"]["WrappedShareToken"]
    shares = decode_uint256(rpc.call(attacker, vault, encode_call("balanceOf(address)", [attacker])))
    small = min(shares, UNIT)
    if small == 0:
        raise SystemExit("no shares to wrap")
    rpc.must_send(attacker, wrapper, encode_call("syncPricePerShare()", []))
    rpc.must_send(attacker, vault, encode_call("approve(address,uint256)", [wrapper, small]))
    rpc.must_send(attacker, wrapper, encode_call("deposit(uint256)", [small]))
    wrapped = decode_uint256(rpc.call(attacker, wrapper, encode_call("balanceOf(address)", [attacker])))
    rpc.must_send(attacker, wrapper, encode_call("redeem(uint256)", [wrapped]))
    print("honest 0997 OK")
if __name__ == "__main__":
    main()
'''
        )
        info = json.loads((src / "info.json").read_text())
        (held / "honest_unlock.txt").write_text(info["unlocked"][0] + "\n")
    (dst / "task_kind.json").write_text(json.dumps({
        "kind": "patch",
        "family_id": gold["family_id"],
        "parent_task_id": gold["parent_task"],
        "grade": "compile + A0 fail + honest pass",
        "paper": "leave [TBD]",
    }, indent=2) + "\n")
    leak = (dst / "prompt.md").read_text()
    if "Vulnerability category" in leak or "Target objective" in leak:
        raise SystemExit("leaky patch prompt")


def build_one(sid: str, kinds: tuple[str, ...] = ("detect", "patch")) -> None:
    gold = load_gold(sid)
    src = locate_p0(sid)
    for kind in kinds:
        name = f"4000-{sid}-{kind}-case"
        dst = TASKS / name
        print("copy", name)
        copy_tree(src, dst)
        if kind == "detect":
            finish_detect(dst, gold)
        elif kind == "patch":
            try:
                apply_gold_patch("", gold["family_id"])
            except SystemExit as exc:
                if "no gold patch transform" in str(exc):
                    shutil.rmtree(dst, ignore_errors=True)
                    print("skip patch", sid)
                    continue
                # needle miss still means a transform exists
            finish_patch(dst, gold, src)
        else:
            raise SystemExit(f"bad kind {kind}")
        link_v3(name)
        print("built", name)


def main() -> None:
    sids = sys.argv[1:] or ["0990", "0804"]
    for sid in sids:
        build_one(sid)
    print("detect_patch ready", sids)


if __name__ == "__main__":
    main()
