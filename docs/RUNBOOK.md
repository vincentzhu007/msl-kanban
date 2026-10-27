# 运行说明

## 环境

采集在 dog 上执行，依赖已有 hdc、BinRunner、手机权限和安装好的 runner；Python 统计及看板仅使用标准库。编译探针需要 OHOS NDK 与 daily C API。Qwen3 导出/编译还需要现有 DDK 容器、模型权重和 daily Python 工具，不能只靠本仓重建。

| 流程 | 探针源码 | 手机采集 | 汇总 |
|---|---|---|---|
| MSL Qwen2.5 9020 正式 2K | `bench_2k.cc` | `run_2k.py` | `summarize_2k.py` |
| MSL Qwen3 9030 PR | `bench_qwen3.cc` | `run_qwen3_pr_validation.py` | `summarize_qwen3.py RESULTS_DIR` |
| llama.cpp Qwen2.5 CPU | `edge_llama_bench/bench.cpp` | `edge_llama_bench/run.py` | `edge_llama_bench/summarize.py` |

MSL 文件位于 `scripts/edge_slm_bench/`。`daily_bench.cc` / `run_daily.py` 是早期 1K 上下文、多进程预热实验，`run_qwen3.py` 是原始 daily 排障脚本，不能与正式结果混用。`compile_pr62.py` 是历史复用中间量化图的脚本，依赖原临时目录；新导出应使用下述完整入口。

## MSL 编译

在 dog 设置实际路径后执行：

```sh
export NATIVE=/home/zhugd/tool/hmos-ndk/command-line-tools/sdk/default/openharmony/native
export DAILY=/home/zhugd/llm_validation/20261026-qwen25-05b-w4a16-9020/mindspore-lite-llm-linux-x64-0.2.0
"$NATIVE/llvm/bin/clang++" --target=aarch64-linux-ohos --sysroot="$NATIVE/sysroot" \
  -std=c++17 -O2 -static-libstdc++ -I "$DAILY/include" \
  scripts/edge_slm_bench/bench_qwen3.cc \
  -Wl,--whole-archive "$DAILY/lib/libmindspore-lite-llm.a" \
  -Wl,--no-whole-archive -ldl -pthread -o daily-qwen3
```

静态库必须 whole-archive，保留 NPU 注册。9020 替换源码及输出名并与对应 runner 一致。llama.cpp 使用 `scripts/edge_llama_bench/CMakeLists.txt`，通过 `-DLLAMA_CPP_DIR=...` 指定固定源码；原实测 commit 见归档与结果，CPU 4 线程、armv8.2-a+dotprod、repack 开、OpenMP 关。交叉编译需使用 OHOS toolchain 和 `ohos_compat.h`（原构建使用的兼容 shim）。

## Qwen3 PR 导出

固定 !1362 `a6cd83f6a6d4fc8afe426f153d63491fe4a7bb50` 与 !62 `abaea09acf6a4cb1e0cf8b6af4ef84f415925941`。运行库固定 daily `5501731a356ffb4ec017a4dc37c3f5631be79489`。!1362 只复用 functional adapter，未启用 DFlash。

在匹配的 DDK 容器中，从 !62 源码执行：

```sh
./build.sh --ops MsMatmulS16S4 MsAttention MsRmsNorm MsAddRmsNorm MsTransRopeScatterNDUpdate MsFloatCastInt
```

将产出的 `.run` 安装至 `/opt/ddk`（`bash PACKAGE.run -- --prefix /opt/ddk`）。加载 DDK 环境，保留原 `PYTHONPATH`，追加 daily Python 工具目录；同样保留并扩展 `LD_LIBRARY_PATH`。当前 dog 验证容器为 `edge-qwen3-pr62-20261026`，路径详见归档 provenance。用完整导出入口进行新一轮验证：

```sh
python3 scripts/edge_slm_bench/export_pr1362.py \
  --model /models/Qwen3-4B --output /out/qwen3-4b-pr.msl \
  --target kirin9030 --quant-type s16s4 --max-length 2048 --chunk-size 64 --keep-artifacts
```

以上是依据已验证组件整理的入口，本次仓库整理未重新执行全量导出。历史成功编译复用了中间图，完整过程见 RESULT.md。

## 手机采集

9020：`127.0.0.1:2000`，BinRunner 端口 18888；9030：`5JV0226127000651`，端口 18940。BinRunner 路径 `/home/zhugd/code/ohos/BinRunner`。在 runner 顶部核对 ROOT、OUT、设备和部署文件名，使用新的输出目录避免旧日志干扰。先将探针及模型部署到 app 的 `@/bin/`。

BinRunner 单文件推送限制 1 GiB，Qwen3 模型需分片传入并在 app 沙箱内拼接，再核对 SHA256。系统 `/data/local/tmp` 文件不能直接当 app 模型路径。launcher 子进程限制约 30 秒，探针采用 detached worker；不要在日志拉取超时时停止内存采样。Qwen3 PR runner 已包含此处理。

模型成功加载后连续运行 5 次，采集 hidumper。全部 status=0 且输出达到 128 后再汇总。统计脚本写回结果目录；llama 汇总还更新仓库的看板 JSON。MSL 汇总产物需补齐 id/date/framework/samples/memory_samples 等展示字段，可参考已收录 JSON。

## 本地复核既有 Qwen3 数据

```sh
cp -R reports/qwen3-9030-daily-20261026/pr-validation/results-aligned /tmp/qwen3-results-check
python3 scripts/edge_slm_bench/summarize_qwen3.py /tmp/qwen3-results-check
```

该操作仅重算已有测量，不运行手机。生产测量仍应归档模型、运行库、源码/PR SHA、配置、依赖版本、原始日志和校验清单。

## 重构后的可配置入口

Qwen3 daily / PR 和 llama.cpp 三个采集入口支持 `--device`、`--port`、`--binrunner`、`--output`、`--binary`、`--model`、`--log`、`--initial-wait`、`--timeout`、`--poll-interval`；用 `--help` 查看默认值。每轮必须使用空输出目录，并配置唯一设备日志名。设备进程名仍由 profile 指定，须与 C++ 探针中的进程名一致。运行配置保存为 `run-config.json`。

```sh
python3 scripts/edge_slm_bench/run_qwen3_pr_validation.py \
  --output /home/zhugd/llm_validation/new-run --log new-run.log
python3 scripts/edge_llama_bench/summarize.py /path/to/results \
  --publish dashboard/data/new-cpu-result.json
python3 -m unittest discover -s tests -v
```

三个汇总入口都支持指定结果目录。llama.cpp 仅在显式提供 `--publish` 时更新看板，避免重算历史记录时覆盖已发布结果；MSL 需补齐展示字段后发布。早期同步 9020 `run_2k.py` 和实验脚本保留原行为。
