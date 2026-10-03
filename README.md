# ConstraintDial

```text
construction/    build Detect and Patch tasks
benchmark/       run one task from a local Hugging Face dataset checkout
```

Copy `.env.example` to `.env`. Paths are left empty.

## Benchmark

`HF_DATASET_DIR` is the local dataset directory. It is expected to contain `tasks/`, `infra/revm_node.py`, and `vendor/`.

```bash
bash benchmark/run.sh 4000-0001-case
bash benchmark/run.sh 4000-0001-case judge
```

Run the two commands in separate terminals. The default endpoint is `http://127.0.0.1:8545`. Override it with `PORT` and `RPC_URL`.

Python 3.10 is required. `vendor/` supplies the Linux CPython 3.10 build of `pyrevm`.

## Construction

```text
CONSTRAINDIAL_REPO=
CONSTRAINDIAL_API_BASE=
CONSTRAINDIAL_API_KEY=
CONSTRAINDIAL_MODEL=
```

`CONSTRAINDIAL_REPO` must contain `experiments/lifelong-pilot/` and `tools/bin/solc`. Gold labels are in `construction/gold/`. Built tasks are written into that repository.

```bash
python3 construction/build_dep_versions.py
python3 construction/construct_missing_patches.py
```
