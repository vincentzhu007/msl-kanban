# Recipe v1：新增模型与统一评测入口

## 已实现与边界

已实现 JSON recipe 校验、预部署 frozen model、不可覆盖的运行锁定清单、设备本机互斥、模型/探针 SHA256 校验、统一运行/统计入口以及参数化探针。支持 MSL NPU 和 llama.cpp CPU；只支持 raw hello 合成输入、greedy、无预热。

此次没有启动新探针的手机推理，也没有更新 dog 看板。新 MSL 探针通过 OHOS 完整编译链接，llama.cpp 探针通过 OHOS 头文件/语法检查，仍需真机确认行为。app 沙箱 SHA256 校验依赖 BinRunner 可执行 `sha256sum`；若命令不可用或受 launcher 时间限制，运行会停止，不能跳过校验。v1 不负责上传模型或导出模型。

自动 daily 发现、rebuild_model、自动 baseline 批准、性能回退复测、告警、温度/频率资格判定及 daily/weekly 调度留待下一阶段。所有 v1 结果 `baseline_eligible=false`，不能冒充已经具备自动性能看护。

## 文件边界

| 位置 | 作用 |
|---|---|
| `recipes/*.json` | 模型与量化身份、构建提交、输入验证证据、测试与采样规格 |
| `config/*.example.json` | 主机、设备、系统版本、部署路径与文件 SHA |
| `scripts/recipe_ci/recipe.py` | 严格字段及能力检查、recipe 与比较指纹 |
| `scripts/recipe_ci/planner.py` | 将 recipe 和环境合成为锁定计划 |
| `scripts/recipe_ci/execution.py` | 校验预部署资产、设备互斥、调用共享 runner |
| `scripts/recipe_ci/results.py` | 校验实际 SPEC、生成统一看板 JSON |
| `scripts/bench_common/probe_options.h` | 两种新探针的共同参数协议 |
| `scripts/edge_slm_bench/bench_recipe.cc` | MSL 通用探针，进程名 recipe-msl |
| `scripts/edge_llama_bench/bench_recipe.cpp` | llama.cpp 通用探针，进程名 recipe-llama |

原有测量入口和原始 C++ 探针保留。新的 recipe 模式必须使用新探针，不能将旧二进制改名冒充。

## 新增 recipe

1. 复制同后端 recipe，设置唯一 id、Base/Instruct 身份、模型 SHA256、文件大小、context 和量化参数。
2. 固定 build commit；MSL 同时固定 daily 包 URL/SHA256。PR 组件填写具体提交。
3. 根据该模型 tokenizer 核对 ` hello` 重复 N 次确实为 N 个 token，将验证记录写入 `input_verification.evidence`。MSL API 不提供实际 token 数，因此 `input_tokens_source` 明确标为外部验证；更换模型或 tokenizer 必须重新核对。
4. 设置工作负载和采样规格。输入加输出不得超过模型上下文；frozen MSL 的上下文必须与模型 metadata 中 `npu.max_length` 一致。v1 不支持任意 prompt/template、warmup 或 rebuild 配方，填写这些能力会报错。
5. 配置单独的 environment，补齐新探针、模型、runtime 的 host/device 路径与 SHA。示例的占位值不代表可执行配置。

同后端支持的模型无需新增 Python 汇总/采集脚本或前端字段。

## 命令

仓库根目录：

```sh
python3 scripts/bench.py validate recipes/qwen3-4b-msl-s16s4-kirin9030.json

# 本地预览：不访问手机，不读取大模型文件；生成的锁不允许执行。
python3 scripts/bench.py resolve recipes/qwen3-4b-msl-s16s4-kirin9030.json \
  --environment config/dog-kirin9030.example.json --preview --output /tmp/recipe-preview.json

# 在 dog 上：先补齐 environment、编译并部署新探针、归档模型和 runtime。
python3 scripts/bench.py resolve recipes/qwen3-4b-msl-s16s4-kirin9030.json \
  --environment /path/to/actual-environment.json --output /path/to/new-resolved-recipe.json
python3 scripts/bench.py run --lock /path/to/new-resolved-recipe.json
```

`resolve` 默认重新计算 host 文件 SHA256，检查模型大小；`run` 再校验 host 文件以及 app 沙箱中模型/探针 SHA256，然后生成唯一运行目录和设备日志名。结果包含 `resolved-recipe.json`、配置、原始日志、采样、CSV 及 `kanban-result.json`。文件锁只协调共享同一 `output_root` 的 recipe 进程，不覆盖其他独立工具的设备占用；批量调度前仍需统一设备管理。

host runtime 归档校验不等于证明 probe 的链接来源，构建流水线应进一步补充编译命令、依赖与产物签名。系统版本目前由 environment 声明，尚未自动核验；结果 `environment_qualified=false`。

新 MSL 命令协议：

```text
recipe-msl MODEL REPEATS LOGFILE CONTEXT INPUT OUTPUT
```

新 llama.cpp 命令协议：

```text
recipe-llama MODEL REPEATS LOGFILE CONTEXT INPUT OUTPUT THREADS BATCH
```

两者都会输出 `SPEC`。MSL 校验冻结模型上下文，llama.cpp 检查实际 context 和 tokenizer 计数，支持非 batch 整数倍输入。输出回调数和生成状态由主机再校验。

MSL 编译沿用 RUNBOOK 中的 NDK/daily 命令，将源码换为 `scripts/edge_slm_bench/bench_recipe.cc`、输出名改为 `recipe-msl`，保留相对目录以找到共享头文件。llama.cpp 的 CMake 新增 `recipe-llama` 目标，沿用 OHOS toolchain/兼容头和原框架源码。

## 导入已有结果

先复制原始测量到临时目录，汇总会重写该副本中的 CSV：

```sh
cp -R reports/qwen3-9030-daily-20261026/pr-validation/results-aligned /tmp/qwen3-import
python3 scripts/bench.py summarize recipes/qwen3-4b-msl-s16s4-kirin9030.json \
  /tmp/qwen3-import --legacy --output /tmp/qwen3-kanban-result.json
```

旧 MSL 9020 数据另外传 `--log five-aligned.log --samples five-aligned-samples.json --memory-pattern 'five-aligned-memory-*.txt'`。`--legacy` 明确表示没有新 SPEC/资产校验证据，不会自动取得基线资格。导入结果与原 recipe 的身份关系仍需人工核对。

展示字段保持兼容现有看板；发布时将结果放到 kanban/data。命令不自动修改线上数据。

## 比较指纹

`recipe_sha256` 覆盖完整 recipe；`comparison_key` 覆盖模型、量化、工作负载、采集协议等可比条件，排除被测 build 版本及说明性路径。`device_comparison_key` 进一步包含具体设备和声明的系统版本。模型 SHA、Base/Instruct、线程、规格变化都会产生不同比较组。

下一阶段应在此基础上实现已批准 baseline、PASS/SUSPECT/REGRESSION/INVALID 等状态、同设备复测和环境资格检查，不能仅用 recipe id 选基线。

## 验证

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
```

覆盖三组既有时延及内存结果、配方拒绝条件、SPEC 不一致、锁篡改/防覆盖、预览禁止执行、设备互斥、旧入口兼容等。不替代真机验证。

## 独立阶段计时

- `initialization.model_init_ms`：探针单调时钟测量一次模型初始化。MSL 为 CreateModel 到 BuildModel 和生成配置完成；llama.cpp 为 backend 初始化到模型、context、sampler 就绪。不含进程启动，不控制文件缓存，不称为冷启动或 P90。
- `samples[].prefill_ms` / `timing.prefill_ms`：llama.cpp 分词完成后，输入 batch 计算至显式同步结束，不含首 token 采样；按实际连续次数取最近秩 P90。
- `ttft_ms`：已初始化模型的一次推理请求至首 token，包含分词、Prefill、采样和接口开销，不含上述初始化。不要相加两个 P90 推算端到端 P90。
- MSL daily 公共生成接口没有独立 Prefill 事件，当前日志仅暴露初始化内部阶段。需要运行库提供阶段统计 API/事件后再采集纯 Prefill，不能用 TTFT 替代。
- 历史结果没有这些字段时显示缺失，不补零。新探针输出 INIT 事件，解析器对重复、负值、非有限值及不完整 Prefill 数据拒绝发布。
