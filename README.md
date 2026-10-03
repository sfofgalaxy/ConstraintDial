# ConstraintDial

两个文件夹并排放着，不要改名字，也不要改层级：

```text
huggingface/
ConstraintDial/
```

`huggingface` 是要上传的题目。链也在里面，`run.sh` 会自己找到，不用填地址。

| 东西 | 路径 |
| --- | --- |
| 题目 | `huggingface/tasks/<题目名>/` |
| 链 | `huggingface/infra/revm_node.py` |
| 依赖 | `huggingface/vendor/` |
| 清单 | `huggingface/task_manifest.csv` |
| 构造代码 | `ConstraintDial/construction/` |

构造代码从 `ConstraintDial/.env` 读取路径和接口，不写在源码里。把 `.env.example` 复制成 `.env` 后填写：

```text
CONSTRAINDIAL_REPO=
CONSTRAINDIAL_API_BASE=
CONSTRAINDIAL_API_KEY=
CONSTRAINDIAL_MODEL=
```

`.env` 只留在本机，不要放进 `huggingface`。`CONSTRAINDIAL_REPO` 下面要有 `experiments/lifelong-pilot/` 和 `tools/bin/solc`。

```bash
python3 ConstraintDial/construction/build_dep_versions.py
python3 ConstraintDial/construction/construct_missing_patches.py
```

`construction/gold/` 是 Detect / Patch 的标注。造出来的题目写回该仓库的题目树，不写进 `huggingface`。

在这两个文件夹的上一层执行：

```bash
bash ConstraintDial/run.sh 4000-0001-case
```

链起来之后，另开一个终端：

```bash
bash ConstraintDial/run.sh 4000-0001-case judge
```

默认端口 `8545`。换端口：

```bash
PORT=18545 bash ConstraintDial/run.sh 4000-0001-case
RPC_URL=http://127.0.0.1:18545 bash ConstraintDial/run.sh 4000-0001-case judge
```

本机需要 `/usr/bin/python3.10`。`vendor` 里的 pyrevm 是 Linux 上的 Python 3.10 扩展。
