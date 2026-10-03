#!/usr/bin/env python3
"""Restart construct_missing_patches workers without self-pkill hazards."""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from construct_missing_patches import packaged, VERSIONS  # noqa: E402
from construct_dep_queue import version_src  # noqa: E402
from lib import GOLD_DIR, TASKS  # noqa: E402

PROXY = os.environ.get("https_proxy") or os.environ.get("http_proxy") or ""
N_WORKERS = 16
STATUS = Path("/tmp/patch_status.txt")
WATCH = Path("/tmp/watch3.log")


def package_count() -> int:
    return sum(
        1
        for p in TASKS.glob("4000-*-patch-case")
        if p.is_dir() and not p.is_symlink() and (p / "task_kind.json").is_file()
    )


def missing_ids() -> list[str]:
    ids: list[str] = []
    for g in sorted(GOLD_DIR.glob("*.json")):
        sid = g.stem
        for ver in VERSIONS:
            if version_src(sid, ver) is None:
                continue
            if not packaged(sid, ver):
                ids.append(sid)
                break
    return ids


def missing_slots(ids: list[str]) -> int:
    return sum(
        1
        for sid in ids
        for ver in VERSIONS
        if version_src(sid, ver) is not None and not packaged(sid, ver)
    )


def kill_matching(substr: str) -> int:
    killed = 0
    mypid = os.getpid()
    for pid in Path("/proc").iterdir():
        if not pid.name.isdigit():
            continue
        p = int(pid.name)
        if p == mypid:
            continue
        try:
            cmd = (pid / "cmdline").read_bytes().replace(b"\0", b" ").decode(errors="ignore")
        except Exception:
            continue
        if substr not in cmd:
            continue
        # Never kill this launcher / watchdog wrappers by broad patterns elsewhere
        if "restart_patch_workers.py" in cmd:
            continue
        try:
            os.kill(p, signal.SIGKILL)
            killed += 1
        except ProcessLookupError:
            pass
    return killed


def kill_orphan_revm() -> int:
    killed = 0
    for pid in Path("/proc").iterdir():
        if not pid.name.isdigit():
            continue
        p = int(pid.name)
        try:
            status = (pid / "status").read_text()
            cmd = (pid / "cmdline").read_bytes().replace(b"\0", b" ").decode(errors="ignore")
        except Exception:
            continue
        if "revm_node" not in cmd:
            continue
        ppid = None
        for line in status.splitlines():
            if line.startswith("PPid:"):
                ppid = int(line.split()[1])
                break
        if ppid == 1:
            try:
                os.kill(p, signal.SIGKILL)
                killed += 1
            except ProcessLookupError:
                pass
    return killed


def alive_workers() -> int:
    n = 0
    for pid in Path("/proc").iterdir():
        if not pid.name.isdigit():
            continue
        try:
            cmd = (pid / "cmdline").read_bytes().replace(b"\0", b" ").decode(errors="ignore")
        except Exception:
            continue
        if "construct_missing_patches.py" in cmd and "restart_patch_workers.py" not in cmd:
            n += 1
    return n


def start_workers(ids: list[str]) -> list[int]:
    env = os.environ.copy()
    if PROXY:
        env["http_proxy"] = PROXY
        env["https_proxy"] = PROXY
        env["HTTP_PROXY"] = PROXY
        env["HTTPS_PROXY"] = PROXY
    pids = []
    for i in range(N_WORKERS):
        shard = ids[i::N_WORKERS]
        Path(f"/tmp/missing_patch_w{i}.txt").write_text(",".join(shard))
        log = Path(f"/tmp/construct_missing_w{i}.log")
        log.write_text("")
        if not shard:
            continue
        port = 36000 + i * 80
        child_env = env.copy()
        child_env["PATCH_IDS"] = ",".join(shard)
        child_env["CONSTRUCT_GATE_PORT"] = str(port)
        with open(log, "w") as handle:
            proc = subprocess.Popen(
                [sys.executable, "-u", "construct_missing_patches.py"],
                cwd=str(HERE),
                env=child_env,
                stdout=handle,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        pids.append(proc.pid)
    return pids


def snapshot(msg: str = "") -> None:
    ids = missing_ids()
    text = (
        f"packages={package_count()}/1015 missing={missing_slots(ids)} "
        f"families={len(ids)} alive={alive_workers()} {msg}\n"
    )
    STATUS.write_text(text)
    with WATCH.open("a") as handle:
        handle.write(time.strftime("%Y-%m-%dT%H:%M:%S%z ") + text)


def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else "once"
    kill_matching("construct_missing_patches.py")
    kill_matching("watch_missing_patches.sh")
    kill_orphan_revm()
    time.sleep(1)
    ids = missing_ids()
    snapshot(f"start families={len(ids)}")
    if not ids:
        STATUS.write_text(f"COMPLETE packages={package_count()}/1015 missing=0\n")
        return
    pids = start_workers(ids)
    snapshot(f"started pids={len(pids)}")
    if mode != "watch":
        return
    stall = 0
    prev_missing = missing_slots(ids)
    while True:
        time.sleep(90)
        kill_orphan_revm()
        ids = missing_ids()
        slots = missing_slots(ids)
        pkgs = package_count()
        alive = alive_workers()
        snapshot()
        if pkgs >= 1015 or slots <= 0:
            STATUS.write_text(f"COMPLETE packages={pkgs}/1015 missing={slots}\n")
            return
        if alive < 8:
            kill_matching("construct_missing_patches.py")
            time.sleep(1)
            if not ids:
                STATUS.write_text(f"COMPLETE packages={pkgs}/1015 missing=0\n")
                return
            start_workers(ids)
            snapshot("full_restart")
            stall = 0
            prev_missing = slots
            continue
        if slots >= prev_missing:
            stall += 1
        else:
            stall = 0
        prev_missing = slots
        if stall >= 10 and alive == 0:
            STATUS.write_text(f"STALLED packages={pkgs}/1015 missing={slots}\n")
            return


if __name__ == "__main__":
    main()
