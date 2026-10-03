#!/bin/bash
# Keep construct_missing_patches workers alive until 1015 packages exist.
set -u
ROOT="$(cd "$(dirname "$0")" && pwd)"
export CONSTRUCT_DIR="$ROOT"
ENV_FILE="$(cd "$ROOT/.." && pwd)/.env"
if [ -f "$ENV_FILE" ]; then
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
fi
: "${CONSTRAINDIAL_REPO:?Fill CONSTRAINDIAL_REPO in ConstraintDial/.env}"
TASKS="$CONSTRAINDIAL_REPO/experiments/lifelong-pilot/tasks"
cd "$ROOT"

count_packages() {
  python3 - <<'PY'
import os
from pathlib import Path
root=Path(os.environ["CONSTRAINDIAL_REPO"]) / "experiments/lifelong-pilot/tasks"
print(sum(1 for p in root.glob("4000-*-patch-case") if p.is_dir() and not p.is_symlink() and (p/"task_kind.json").is_file()))
PY
}

reshard() {
  python3 - <<'PY'
import sys
from pathlib import Path
import os
sys.path.insert(0, os.environ["CONSTRUCT_DIR"])
from construct_missing_patches import packaged, VERSIONS
from construct_dep_queue import version_src
from lib import GOLD_DIR
ids=[]
for g in sorted(GOLD_DIR.glob("*.json")):
    sid=g.stem
    for ver in VERSIONS:
        if version_src(sid, ver) is None:
            continue
        if not packaged(sid, ver):
            ids.append(sid)
            break
slots=sum(1 for sid in ids for ver in VERSIONS if version_src(sid,ver) is not None and not packaged(sid,ver))
print(f"families {len(ids)} slots {slots}", flush=True)
n=16
for i in range(n):
    Path(f"/tmp/missing_patch_w{i}.txt").write_text(",".join(ids[i::n]))
PY
}

kill_orphans() {
  ps -eo pid,ppid,cmd | awk '$2==1 && /revm_node/ {print $1}' | xargs -r kill -9 2>/dev/null || true
  ps -eo pid,cmd | awk '/revm_node.py --task-dir \/tmp\/patch-work/ {print $1}' | xargs -r kill -9 2>/dev/null || true
}

start_all() {
  ps -eo pid,cmd | awk '/construct_missing_patches.py/ && !/awk/ {print $1}' | xargs -r kill -9 2>/dev/null || true
  sleep 1
  kill_orphans
  reshard
  for i in $(seq 0 15); do
    port=$((36000 + i * 80))
    mv -f /tmp/construct_missing_w${i}.log /tmp/construct_missing_w${i}.prev.log 2>/dev/null || true
    PATCH_IDS="$(cat /tmp/missing_patch_w${i}.txt)" CONSTRUCT_GATE_PORT=$port \
      nohup python3 -u construct_missing_patches.py > /tmp/construct_missing_w${i}.log 2>&1 &
    echo "started w$i=$! port=$port"
  done
}

restart_done() {
  local restarted=0
  for i in $(seq 0 15); do
    if grep -q MISSING_PATCH_DONE /tmp/construct_missing_w${i}.log 2>/dev/null; then
      # only restart if there is still missing work
      local remaining
      remaining=$(python3 - <<'PY'
import sys
from pathlib import Path
import os
sys.path.insert(0, os.environ["CONSTRUCT_DIR"])
from construct_missing_patches import packaged, VERSIONS
from construct_dep_queue import version_src
from lib import GOLD_DIR
n=0
for g in GOLD_DIR.glob("*.json"):
  sid=g.stem
  for ver in VERSIONS:
    if version_src(sid,ver) is not None and not packaged(sid,ver):
      n+=1
print(n)
PY
)
      if [ "$remaining" -le 0 ]; then
        return 0
      fi
      # rebuild only this worker's shard from current missing, excluding ids still
      # assigned to live workers
      python3 - <<PY
import sys
from pathlib import Path
import os
sys.path.insert(0, os.environ["CONSTRUCT_DIR"])
from construct_missing_patches import packaged, VERSIONS
from construct_dep_queue import version_src
from lib import GOLD_DIR
done=set()
for i in range(16):
    text=Path(f"/tmp/construct_missing_w{i}.log").read_text(errors="ignore")
    if "MISSING_PATCH_DONE" in text:
        done.add(i)
running=set()
for i in range(16):
    if i in done: continue
    shard=Path(f"/tmp/missing_patch_w{i}.txt").read_text().strip()
    running.update(x for x in shard.split(",") if x)
ids=[]
for g in sorted(GOLD_DIR.glob("*.json")):
    sid=g.stem
    if sid in running: continue
    for ver in VERSIONS:
        if version_src(sid,ver) is None: continue
        if not packaged(sid,ver):
            ids.append(sid); break
done_list=sorted(done)
for j, wid in enumerate(done_list):
    Path(f"/tmp/missing_patch_w{wid}.txt").write_text(",".join(ids[j::len(done_list)]))
    print(f"reshard w{wid} {len(ids[j::len(done_list)])}", flush=True)
PY
      port=$((36000 + i * 80))
      mv -f /tmp/construct_missing_w${i}.log /tmp/construct_missing_w${i}.prev.log
      PATCH_IDS="$(cat /tmp/missing_patch_w${i}.txt)" CONSTRUCT_GATE_PORT=$port \
        nohup python3 -u construct_missing_patches.py > /tmp/construct_missing_w${i}.log 2>&1 &
      echo "restarted w$i=$! remaining_hint=$remaining"
      restarted=1
    fi
  done
  return $restarted
}

echo "watch start packages=$(count_packages)"
start_all
prev_missing=9999
stall=0
while true; do
  sleep 120
  kill_orphans
  pkgs=$(count_packages)
  alive=$(ps -eo pid,cmd | awk '/construct_missing_patches.py/ && !/awk/' | wc -l)
  missing=$(python3 - <<'PY'
import sys
from pathlib import Path
import os
sys.path.insert(0, os.environ["CONSTRUCT_DIR"])
from construct_missing_patches import packaged, VERSIONS
from construct_dep_queue import version_src
from lib import GOLD_DIR
print(sum(1 for g in GOLD_DIR.glob("*.json") for ver in VERSIONS if version_src(g.stem,ver) is not None and not packaged(g.stem,ver)))
PY
)
  echo "packages=$pkgs/1015 missing=$missing alive=$alive $(date -Is)"
  if [ "$pkgs" -ge 1015 ] || [ "$missing" -le 0 ]; then
    echo "COMPLETE packages=$pkgs missing=$missing"
    break
  fi
  restart_done || true
  if [ "$missing" -ge "$prev_missing" ]; then
    stall=$((stall+1))
  else
    stall=0
  fi
  prev_missing=$missing
  if [ "$alive" -eq 0 ] && [ "$stall" -ge 2 ]; then
    echo "all workers idle with stall; full restart"
    start_all
    stall=0
  fi
  if [ "$stall" -ge 8 ]; then
    echo "STALLED packages=$pkgs missing=$missing"
    break
  fi
done
