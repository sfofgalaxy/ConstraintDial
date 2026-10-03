#!/usr/bin/env python3
"""Honest probe that only calls functions present on the base contract."""
from __future__ import annotations

import json
import os
import re
import subprocess
import time
import urllib.request
from pathlib import Path

from paths import repo_root

ROOT = repo_root()
NODE = ROOT / "infra" / "revm_node.py"
PYTHON = "/usr/bin/python3.10"


def sender_address(info: dict) -> str:
    unlocked = [item for item in (info.get("unlocked") or []) if isinstance(item, str) and item.startswith("0x")]
    if unlocked:
        return unlocked[0]
    accounts = info.get("accounts") or {}
    for key in ("attacker", "trader", "solver", "issuer", "operator", "provider"):
        value = accounts.get(key)
        if isinstance(value, str) and value.startswith("0x"):
            return value
    for value in accounts.values():
        if isinstance(value, str) and value.startswith("0x"):
            return value
    raise KeyError("no sender account")


def info_keys_for_contract(info: dict, cname: str) -> list[str]:
    """Map a Solidity contract name to info.json deployment keys."""
    contracts = info.get("contracts") or {}
    if cname in contracts:
        return [cname]
    keys = []
    lower = cname.lower()
    for key in contracts:
        kl = key.lower()
        if kl == lower or kl.endswith(lower) or lower in kl:
            keys.append(key)
    return keys


def bootstrap_artifact_keys(work: Path) -> dict[str, list[str]]:
    """Best-effort artifact -> info.json key map from bootstrap.py."""
    path = work / "bootstrap.py"
    if not path.is_file():
        return {}
    text = path.read_text(errors="ignore")
    mapping: dict[str, list[str]] = {}
    patterns = [
        r"""_deploy\(\s*ctx\s*,\s*["'](\w+)["']\s*,\s*["'](\w+)["']""",
        r"""\bd\(\s*["'](\w+)["']\s*,\s*["'](\w+)["']""",  # d(key, Artifact) — swapped below
        r"""ctx\.deploy\(\s*["'](\w+)["']""",
        r"""createPair\(\s*ctx\s*,\s*["'](\w+)["']""",
        r"""_create_pair\(\s*ctx\s*,\s*["'](\w+)["']""",
    ]
    # _deploy(ctx, Artifact, key)
    for art, key in re.findall(
        r"""_deploy\(\s*ctx\s*,\s*["'](\w+)["']\s*,\s*["'](\w+)["']""", text
    ):
        mapping.setdefault(art, []).append(key)
    # d("key", "Artifact", ...) as in 0094
    for key, art in re.findall(
        r"""\bd\(\s*["'](\w+)["']\s*,\s*["'](\w+)["']""", text
    ):
        mapping.setdefault(art, []).append(key)
    # createPair / _create_pair register pool aliases as AmmPair clones
    for key in re.findall(
        r"""(?:_create_pair|createPair)\(\s*ctx\s*,\s*["'](\w+)["']""", text
    ):
        mapping.setdefault("AmmPair", []).append(key)
        mapping.setdefault("LiquidityPair", []).append(key)
        mapping.setdefault("TokenPair", []).append(key)
    # de-dupe
    return {art: list(dict.fromkeys(keys)) for art, keys in mapping.items()}


def resolve_info_keys(work: Path, info: dict, cname: str) -> list[str]:
    keys = info_keys_for_contract(info, cname)
    if keys:
        return keys
    mapped = bootstrap_artifact_keys(work).get(cname) or []
    contracts = info.get("contracts") or {}
    keys = [key for key in mapped if key in contracts]
    if keys:
        return keys
    lower = cname.lower()
    if lower.endswith("pair") or lower in {"ammpool", "liquiditypool", "pool"}:
        return [
            key
            for key in contracts
            if "pool" in key.lower() or "pair" in key.lower()
        ]
    return []


def candidates(work: Path, info: dict, skip: set[str], allow: set[str] | None = None) -> list[tuple[str, str, list]]:
    attacker = sender_address(info)
    found = []
    for sol in (work / "contracts").glob("*.sol"):
        text = sol.read_text(errors="ignore")
        parts = re.split(r"\n(?:abstract\s+)?contract\s+(\w+)", text)
        for i in range(1, len(parts), 2):
            cname, body = parts[i], parts[i + 1]
            info_keys = resolve_info_keys(work, info, cname)
            if not info_keys:
                continue
            if allow is not None:
                allowed_keys = set()
                for wanted in allow:
                    allowed_keys.update(resolve_info_keys(work, info, wanted))
                    allowed_keys.update(info_keys_for_contract(info, wanted))
                info_keys = [key for key in info_keys if key in allowed_keys or cname in allow]
                if not info_keys:
                    continue
            for match in re.finditer(
                r"function\s+(\w+)\s*\(([^)]*)\)\s*(external|public)", body
            ):
                name, args = match.group(1), match.group(2).strip()
                if name in skip or "[" in args or "bytes" in args or "string" in args:
                    continue
                values = []
                types = []
                ok = True
                for raw in [item.strip() for item in args.split(",") if item.strip()]:
                    kind = raw.split()[0]
                    if kind == "address":
                        types.append("address")
                        values.append(attacker)
                    elif kind in ("uint256", "uint", "uint8", "uint128", "int256"):
                        types.append("uint256" if kind == "uint" else kind)
                        values.append(0)
                    elif kind == "bool":
                        types.append("bool")
                        values.append(False)
                    else:
                        ok = False
                        break
                if ok:
                    variants = [values]
                    if any(isinstance(v, int) for v in values):
                        alt = [1 if isinstance(v, int) and v == 0 else v for v in values]
                        if alt != values:
                            variants.append(alt)
                    for key in info_keys:
                        for vals in variants:
                            found.append((key, f"{name}({','.join(types)})", vals))
            # Public state variables are real zero-argument calls on the
            # deployed bytecode. They are the ordinary reads that stay
            # available after a patch, including when every mutating
            # entry point is owner-gated.
            for match in re.finditer(
                r"\b(?:address|bool|u?int\d*)\s+public\s+(?:constant\s+|immutable\s+)?(\w+)\b",
                body,
            ):
                name = match.group(1)
                if name in skip:
                    continue
                for key in info_keys:
                    found.append((key, f"{name}()", []))
    found.sort(key=lambda item: (len(item[2]), item[0], item[1]))
    return found


def write_flow(path: Path, sid: str, contract: str, signature: str, values: list, sender: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rendered = ", ".join(repr(value) for value in values)
    path.write_text(
        "#!/usr/bin/env python3\n"
        f'"""Base honest call for {sid}: {contract}.{signature}."""\n'
        "import json, os, sys\n"
        "TASK = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))\n"
        "def _root():\n"
        "    probe = TASK\n"
        "    for _ in range(12):\n"
        "        if os.path.isfile(os.path.join(probe, 'infra', 'abi.py')):\n"
        "            return probe\n"
        "        probe = os.path.dirname(probe)\n"
        "    return None\n"
        "r = _root()\n"
        "if r:\n"
        "    sys.path.insert(0, r)\n"
        "from infra.abi import encode_call\n"
        "from infra.ethlite import EthLite\n"
        "def main():\n"
        "    rpc = EthLite(os.environ.get('RPC_URL', 'http://127.0.0.1:8545'))\n"
        "    info = json.load(open(os.path.join(TASK, 'info.json')))\n"
        f"    rpc.must_send({sender!r}, info['contracts'][{contract!r}], "
        f"encode_call({signature!r}, [{rendered}]))\n"
        f"    print('honest {sid} OK')\n"
        "if __name__ == '__main__':\n"
        "    main()\n"
    )


def _wait_node(url: str) -> bool:
    body = b'{"jsonrpc":"2.0","id":1,"method":"eth_blockNumber","params":[]}'
    for _ in range(50):
        try:
            urllib.request.urlopen(
                urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"}),
                timeout=1,
            )
            return True
        except Exception:
            time.sleep(0.2)
    return False


def _node(work: Path, port: int) -> subprocess.Popen:
    env = os.environ.copy()
    env["PYTHONPATH"] = f"{ROOT}:{ROOT / 'vendor'}"
    return subprocess.Popen(
        [PYTHON, str(NODE), "--task-dir", str(work), "--port", str(port)],
        env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


def _judge_verdict(work: Path, env: dict) -> str:
    subprocess.run(
        ["bash", str(work / "judge.sh")],
        cwd=str(work), env=env, capture_output=True, text=True, timeout=120,
    )
    for cand in (work / "results" / "result.json", work / "result.json"):
        if cand.is_file():
            try:
                return str(json.loads(cand.read_text()).get("verdict") or "")
            except json.JSONDecodeError:
                return ""
    return ""


def probe_and_check(work: Path, sid: str, port: int, skip: set[str], allow: set[str] | None = None) -> dict:
    info = json.loads((work / "info.json").read_text())
    sender = sender_address(info)
    primary = candidates(work, info, skip, allow)
    rest = [item for item in candidates(work, info, skip, None) if item not in primary]
    cands = (primary + rest)[:24]
    env = os.environ.copy()
    env["PYTHONPATH"] = f"{ROOT}:{ROOT / 'vendor'}"
    url = f"http://127.0.0.1:{port}"
    env["RPC_URL"] = url
    if not (work / "held" / "parent_solve.py").is_file():
        return {"sid": sid, "status": "missing_parent_solve"}
    parent_node = _node(work, port)
    try:
        if not _wait_node(url):
            return {"sid": sid, "status": "node_down"}
        parent = subprocess.run(
            [PYTHON, str(work / "held" / "parent_solve.py")],
            env=env, capture_output=True, text=True, timeout=180,
        )
    finally:
        parent_node.kill()
        parent_node.wait(timeout=5)
    if parent.returncode == 0:
        return {
            "sid": sid,
            "status": "parent_still_passes",
            "parent_rc": 0,
            "detail": (parent.stdout or "")[-400:],
        }
    import sys
    sys.path.insert(0, str(ROOT))
    from infra.abi import encode_call
    from infra.ethlite import EthLite

    # If the judge already passes on a fresh chain with no agent action,
    # it cannot discriminate objective-meeting calls — accept any live call.
    baseline = ""
    base_node = _node(work, port)
    try:
        if _wait_node(url):
            baseline = _judge_verdict(work, env)
    finally:
        base_node.kill()
        base_node.wait(timeout=5)
    judge_always = baseline in {"pass", "success"}

    for contract, signature, values in cands:
        write_flow(work / "held" / "honest_flow.py", sid, contract, signature, values, sender)
        node = _node(work, port)
        try:
            if not _wait_node(url):
                return {"sid": sid, "status": "node_down", "call": f"{contract}.{signature}"}
            rpc = EthLite(url)
            try:
                rpc.must_send(sender, info["contracts"][contract], encode_call(signature, values))
            except Exception:
                continue
            if not judge_always:
                verdict = _judge_verdict(work, env)
                if verdict in {"pass", "success"}:
                    continue
            return {
                "sid": sid,
                "status": "one_init_pass",
                "call": f"{contract}.{signature}",
                "parent_rc": parent.returncode,
            }
        finally:
            node.kill()
            node.wait(timeout=5)
    return {"sid": sid, "status": "no_base_call", "tried": len(cands)}
