# v0.2 Daily 评测

链路：官方 master daily 发布件 / 固定竞品源码 → dog Runner 容器 → recipe 真机评测 → GitHub 结果提交 → Vercel 静态看板。

| 任务 | 设备 | 版本策略 |
| --- | --- | --- |
| Qwen2.5-0.5B MSL W4A16 | Kirin9020 | 当天 MSL daily + 固定模型 |
| Qwen2.5-0.5B MSL Q3_0 | Kirin9020 | 当天 MSL daily 导出工具与算子重新生成模型 |
| Qwen3-4B MSL S16S4 | Kirin9030 | 当天 MSL daily + PR1362/PR62 归档模型 |
| Qwen3-0.6B MSL S16S4 | Kirin9030 | 当天 MSL daily + PR1362/PR62 归档模型 |
| Qwen2.5-0.5B llama.cpp Q4_0 CPU | Kirin9020 | 固定 07822bdd 源码每日重编译；4线程、batch64 |
| Qwen2.5-1.5B MSL W4A16 | Kirin9020 | 当天 MSL daily 导出工具与算子重新生成模型；上传/启动/拉日志不走 br |
| Qwen2.5-1.5B MSL Q3_0 | Kirin9020 | 同上，量化为 q3_0。2026-11-22 只验证了导出，同规格真机与精度都还没有通过记录 |

Q3_0 是 Kirin9020 上 Q4_0 之外的例外量化方式，导出配置名为 `q3_0`（decoder 为 Q3_0，embedding 与 head 仍按运行时契约保持 Q4_0）。该任务每天用当天 master daily 的导出工具和算子重新生成模型，导出能力随 mindspore-lite !1211 于 2026-11-10 合入 master，首个包含该能力的 master daily 发布件为 2026-11-11 构建；更早日期手动补跑会因导出工具不支持 `q3_0` 而失败。

CANN Kit 当前仅支持 PC，短期不支持端侧：已从每日任务矩阵、手动触发选项及看板展示中移除；历史归档保留，不参与运行情况统计。

## 触发与配置

工作流 `.github/workflows/daily-qwen25-9020.yml` 支持手动输入 YYYYMMDD（留空按北京时间当天）、task 选择单项或 all，以及 force 重跑。仅允许 main 分支执行。定时为北京时间每天 03:00（UTC 前一天 19:00），必须设置仓库变量 `DAILY_ENABLED=true` 才执行；首次手动端到端验证完成后启用。GitHub schedule 可能延迟或漏发，v0.2 不承诺严格准点；可手动补跑指定日期。

Runner 使用 `infra/github-runner/compose.yaml` 加 `compose.daily.yaml` 启动。按 `config/daily/*.json` 配置设备、已归档模型和 BinRunner 路径，将配置目录挂载为 `/config/tasks`。Compose 新增 `DAILY_CONFIG_DIR`、`QWEN3_4B_ARCHIVE_DIR`、`QWEN3_06B_ARCHIVE_DIR`、`LLAMA_ARCHIVE_DIR` 环境变量；三个模型归档目录只读。Runner 镜像包含 cmake/make。构建新的探针，复用固定模型，不重新导出模型。模型及探针均需通过 host 和手机沙箱 SHA256 校验；手机需事先部署独立 sha256sum 工具。

```sh
python3 scripts/daily.py --config /config/tasks/qwen3-4b-msl-s16s4-kirin9030.json \
  --recipe recipes/qwen3-4b-msl-s16s4-kirin9030.json --date 20261029
```

任务只调用仓库中的评测逻辑。生成的 recipe/environment 是锁定数据，不生成替代评测脚本。daily 包必须提供官方 `.sha256`；没有当天 master 构建时记录 NO_BUILD，不使用旧包顶替。下载/编译/设备/采样校验失败记录 FAILED。Archive 解包拒绝链接、特殊文件和路径越界。

## 归档与互斥

`/data` 挂载 dog 的持久化归档目录：

- `packages/<sha256>/`：已验证发布件缓存。
- `tasks/<run_id>/`：任务状态、构建信息、源码快照、编译日志、编译器身份、配置、原始错误、测量目录索引，以及导出成功时的完整 `model.msl`。该项进程结束时只清理这个目录里的导出中间产物，不碰其他 run。
- `runs/<recipe-run-id>/`：现有 recipe 生成的锁、原始日志、内存采样、CSV 和看板结果。
- `completed/`：成功结果索引；日期、发布件、recipe、评测代码 commit 和设备环境均相同才去重（固定竞品次日仍会重测）。force 可以显式复测。
- `leases/`：整个准备/部署/评测阶段共享的设备锁。其他人工任务也需遵守同一设备使用约定；不强制终止未知进程。

整个工作流互斥，矩阵 max-parallel=1，七项依次执行且 fail-fast=false；某一项失败不取消其余项。前五项的任务 id、顺序和 br 上传路径不变。后两项是 Qwen2.5-1.5B，只在这两项上改用安全传输。定时表达式仍是 `0 19 * * *`，不改 `DAILY_ENABLED`。手动指定一个 task id 时，select 只把该 id 放进矩阵，其余项不会启动评测；`all` 或空选择仍是七项。未知 id 会使 select 失败，不能把全部跳过的绿色 run 当成成功。每项独立归档并提交，run id 包含 recipe id，避免同一工作流内覆盖。发现仍在运行的 recipe-msl / recipe-llama / edge-llama 时拒绝覆盖探针，不杀进程。模型不会从发布件自动替换。异常退出后应检查残留 worker，再重跑。安全传输拆除自己的 fport 也不表示 worker 已经退出。

## 发布和指标

通过校验的指标写入 `kanban/data`；成功、失败、无新构建、去重、依赖阻塞的任务记录写入 `kanban/jobs`。模型内部来源路径、真实设备序列号和详细错误不写入新公开结果。完整证据只保留在 dog；任务记录链接到私有 GitHub Actions 日志。

工作流将结果与任务状态提交回 GitHub。API 提交失败会使 Actions 失败，dog 归档仍在；重跑会复用已成功归档的结果。GitHub 数据提交成功与 Vercel 部署成功是两个独立状态，部署失败不能被解释成测量失败。

固定规格：上下文2048、输入1024、输出128，同进程10次、无预热；P90 最近秩法，10次对应升序第9个值（历史5次数据仍取最大值）。采集总PSS与Graph峰值、推理期峰值及第2–10次Decode稳定中位数。看板增加任务记录与按设备比较指纹分组的历史趋势。

当前不自动批准基线或判定回退；温度、频率未锁定，系统版本与配置不符时拒绝运行。尚未接入多设备队列、weekly竞品、模型重导出、告警和漏跑补偿。

## 发布故障恢复

结果发布使用 GitHub Git Data API，以最新 main 的 tree 为基础原子提交，只允许快进更新；网络失败或分支前进最多尝试4次，不强行覆盖远端。使用工作流自带的 contents:write token，不新增长期密钥。测量成功、发布失败时，dog 的 `tasks/<run_id>/archive.json` 指向已校验结果，`status.json` 保留测量状态。可以重跑相同代码/日期以复用归档，也可以将原始 `kanban-result.json` 和 `status.json` 原样恢复到仓库对应数据目录，单独提交恢复记录。Actions 总状态仍用于判断整条流水线是否成功。

采样中遇到 `hidumper: No such process`，只有时间戳证明整份采样位于最后一次推理结束后才排除；该原始记录仍在 dog 归档中。推理期间的缺失、其他错误及稳定期有效样本不足仍会使校验失败。

llama.cpp 使用 SHA256 固定的归档源码，独立于 MSL 发布件是否存在；构建命令保存在 configure.log / compile.log。编译采用 Release/O3、armv8.2-a+dotprod、静态库、关闭 OpenMP/KleidiAI。与旧历史编译配置不同的结果不能直接认定为运行库性能变化。

## 自动唤醒与防冻结

仓库 recipe 执行器在手机文件校验与推理前临时覆盖亮屏超时为30分钟，调用 `power-shell wakeup`，若窗口焦点在普通锁屏则按屏幕尺寸执行一次正常上滑，再启动 BinRunner 并确认焦点已进入应用。出现认证锁屏或无法进入前台时直接失败，不输入密码、不绕过认证。测量期间每10秒通过设备命令唤醒屏幕，避免系统重置超时后再次熄屏；不在测量中途做滑动或切换前台。执行结束或失败均停止保活并恢复屏幕超时。

采集器将进程 cgroup 与内存原始数据一同归档；检测到 `freezer:/Frozen` 时拒绝该组结果。冻结前后续跑的数据不能作为有效性能对照，应清理本次 worker 后重新运行独立测量。

## 每日重新生成 MSL 模型

六个带 `model_generation` 的 MSL 任务启用全链路：Qwen2.5-0.5B W4A16、Qwen2.5-0.5B Q3_0、Qwen3-4B、Qwen3-0.6B、Qwen2.5-1.5B W4A16、Qwen2.5-1.5B Q3_0。

1. 选择指定日期最新成功发布的 master daily 包，校验归档 SHA256。
2. 从同一包取 `mslite_llm` wheel、`mslite_llm_ops` wheel 和算子 `.run`。三者独立记录哈希，不混用 PR adapter 或既有算子。包中没有独立 internal Git SHA 时明确记为 null，不能将 runtime SHA 当作 internal SHA。
3. 从只读挂载的原始 DDK 6.1.1.0 zips 为当次任务建立独立 DDK，安装当天算子；Python 工具安装到当次任务的独立目录。
4. 原始 HF 权重/配置/tokenizer 建立哈希清单，验证 raw hello 的实际 token 数，按 recipe 上下文重新导出、量化、编译和打包。导出后再次校验源文件没有变化。
5. 将新模型 SHA256、字节数和 token 证据写入本次解析的 recipe；部署新模型及探针，并核对手机侧 SHA256，再执行连续10次评测。
6. 失败停在 EXPORT_MODEL/DEPLOY/MEASURE 等对应阶段，不使用旧模型生成成功记录。此前成功数据仍可在看板按历史实测查看。

`tasks/<id>/` 保存每日组件清单、源权重清单、DDK zip 哈希、导出/编译日志、解析后的 recipe，以及导出成功时的完整 `model.msl`。基础 HF 权重仍固定；每日变化的是导出工具、算子和运行库。

每一项在 `pipeline.run` 的 `finally` 中清理**当前** `tasks/<run_id>/`，成功、失败、NO_BUILD、SKIPPED 都会执行，在本进程退出、下一项开始之前完成。删除 `.msl_export*`（导出命令仍带 `--keep-artifacts`，所以导出器自己不会删这棵工作树）、`ddk/`、`ddk-source/`、`python/`，以及为编译/导出解压的 `package/`。`packages/<sha256>/` 里的发布件缓存保留。`export.log` 压成 `export.log.gz`。

`model.msl` 只在 `export_model` 成功返回后保留。打包中途失败时，文件头已经是 `.MSL` 也不能留下半截模型，其他 `*.msl` 一并删除。部署时的同 inode 硬链接跟着保留。`status.json`、`error.txt`、`cleanup.json` 和其他小记录留在 dog；`kanban/jobs` 里的任务记录仍按原来的时机写入。不扫描历史 `tasks/`，不删除 `runs/` 测量归档，也不清理别的 recipe 正在使用的目录。

### Runner 导出环境

使用 `infra/github-runner/Dockerfile.export` 构建 `msl-kanban-runner:daily-export`。EXPORT_BASE 提供 torch/transformers/onnx 等依赖，RUNNER_IMAGE 提供 GitHub runner 发行件；部署时记录实际镜像ID。任务不使用基础镜像自带 DDK 或旧算子。

新增只读挂载：

- `SOURCE_MODELS_DIR` → `/assets/source-models`（Qwen2.5-0.5B-Instruct、Qwen2.5-1.5B-Instruct、Qwen3-4B、Qwen3-0.6B）。
- `DDK_PACKAGES_DIR` → `/assets/ddk-packages`（官方 DDK-tools 及两种芯片 plugin zip）。

配置必须同步到 `/config/tasks`。GitHub任务超时150分钟，单模型导出超时90分钟。未设置 `minimum_free_bytes` 时，任务目录的可用空间缺省门槛是 12GiB。Qwen2.5-1.5B 两项在任务目录上另设 64GiB，并在 `/tmp` 上另设 40GiB；这是两次独立比较。正式容器里 `/tmp` 与 `/data` 可能在同一存储池，两处读到的可用空间不能相加。不扫描、不删除其他日期或其他 recipe 的历史归档；只在本项结束时删除本任务目录里的导出中间产物。llama.cpp CPU 对照继续使用固定GGUF，与MSL重新导出策略分开。

## Qwen2.5-1.5B Kirin9020

两个任务共用 HF 源 `/assets/source-models/Qwen2.5-1.5B-Instruct`，`model_generation.mode` 都是 `master_daily`。`qwen25-15b-msl-w4a16-kirin9020` 的 `quant_type` 与 recipe `format` 是 `q4_0`。`qwen25-15b-msl-q30-kirin9020` 的 `quant_type` 与 recipe `format` 是 `q3_0`。导出产物和结果曲线按 format 分开。模型清单里 Kirin 9020 的 Q4_0 标为支持，依据是 2026-11-22 16:00 包的 10 次真机，不是新的测量。Q3_0 保持待确认：没有晚于那天的同规格真机结果；名为 Q30 的当天日志实际是 W4A16。

规格都是上下文 2048、输入 1024、输出 128、连续 10 次，与 0.5B 相同。测量沿用现有 Total PSS、Graph、hidumper 与样本合同，并记录 TTFT 与 decode。不发布 ION、DMA 与普通内存拆分。链路跑通、样本完整、精度达标是三件不同的事。

recipe 里的 `model.sha256` 与 `build.commit` 是全 0 哨兵。`model.bytes` 是 1，因为 schema 的下限是 1，写成 0 会被拒绝。这三项都不是测量值，也不能把 `bytes` 的 1 读成文件大小。导出成功后由当次 `export_model` 写成该次模型的摘要和字节数，以及该次包的身份。2026-11-23 14:17 现场核对过的最新 master daily tar SHA256 是 `05c304249884d7674a415442eb437042844a53745e3a73f9d66f2c4f6ee438a1`（commit `415fad80e2f936f73400477d92ac063bcbdd40b2`）。这只是该时点的包身份。任务仍按日期发现当天包，并用包内 sidecar 校验；commit 相同不能代替 tar 摘要。

### 只给这两项的安全传输

`device_transport.mode` 为 `safe_norestart`。它覆盖探针和模型上传、沙箱 `sha256sum`、`aa start` 启动和日志 pull，失败后不回退 `python -m binrunner`。连接被拒绝、连接超时、传输中断、摘要不符、pull 超时、已有 worker、未知 fport 或端口竞态都停在安全失败：不 force-stop，不杀共享 App，不删 19005 或任何不是本任务刚创建的转发。宿主端口只从当时空闲的 19147–19159 里选，设备端固定 8888。监听端口从 `/proc/net/tcp` 和 `/proc/net/tcp6` 读取，不调用 `ss`。任一表缺失、不可读或无法按内核格式解析，就拒绝建立转发。不再使用宿主 18888，也不使用宿主 8888。`hdc` 命令带 `-t` 本机序列号；序列号以 `:3000` 结尾时直接拒绝，不向 TTS 的 3000 发命令。

转发在同一把 `/data/leases` 设备锁里创建。成功去重使用序列号、系统版本、设备池和 SoC；当次选出的宿主端口写在 environment 和 `safe-transport.json`，不进入 completed 键。Daily 的 `/data/leases` 与 `execute()` 的 `runs/.leases` 是两个 flock 文件，不会天然互斥，本 PR 不把它们合成一把。导出阶段已经持有本任务的 fport，但还没有 `runs/.leases`。评测结束或失败时，只要本会话已经发出创建命令，关闭阶段会再列一次转发；只有列表里仍是本序列号的同一条 `tcp:<port> tcp:8888` 才删除。列表失败或看不到该行时不删除任何转发。笔记 `removed-own-fport` 只在实际发出 `fport rm` 且随后列表不再含该条时写入。若关闭时第一次列表看得到、下一次列表已经没有，则不发 `rm`，笔记是 `own-tuple-not-listed`。pull 超时只让内存采样继续，不拆转发，也不把 detached worker 记成已经退出。已有 `recipe-msl` / `recipe-llama` / `edge-llama` 时拒绝启动，不杀进程。`awake_device` 仍负责亮屏和把 BinRunner 拉到前台，那是现有的 `aa start`，不是 force-stop。probe 只说明 `127.0.0.1:<port>` 能连上，不作为设备身份；设备身份仍是原来的 OS 版本核对。pull 的字节数不是产物身份，沙箱 SHA256 必须与主机一致。

`environment.binrunner` 仍要填容器里的 `/assets/binrunner`，因为锁定 schema 需要这个字段。它不是“可以调用 br”的许可。不要把旧的 `binrunner=/data/binrunner-1.4.1` 或 `binrunner_device_port: 8888` 抄进来。

### 导出环境

只有这两项设置 `export_environment`。导出子进程使用 `/tmp/e15.*` 短目录，使 `$TMPDIR/listener-XXXXXXXX` 短于 107 字节，并在 `source set_ascendc_env.sh` 之后重新导出 `TMPDIR` 和 `PATH`。`PATH` 前置 `/opt/ddk/ddk/ccec_compiler/bin`，因为正式镜像里有 `bisheng`，默认 PATH 找不到它，1.5B 的 JIT 不能靠 0.5B 的缓存命中。目录只删除本进程创建的 `/tmp/e15.*`。`/data` 上该次任务要求至少 64GiB 可用（24GiB 低水位加 40GiB 工作预算），`/tmp` 至少 40GiB。这两道门槛分开比较。正式容器里 `/tmp` 与 `/data` 可能在同一存储池，读到的可用空间不能相加，40GiB 不是 64GiB 之外的另一份容量。未设置 `minimum_free_bytes` 的其他导出任务仍用 12GiB 缺省。不删除历史归档；本项结束时仍会删掉该任务目录中的 `.msl_export*`、`ddk/` 和 `ddk-source/`。两项高峰不要重叠；第一项结束后再决定是否发第二项。

### 私有部署文件

仓库 `config/daily/` 里的两份 JSON 不含设备序列号和环境，避免把运行配置写进公开任务文件。dog 上 `/home/zhugd/msl-kanban-runner-deploy/tasks/` 要换成 `config/deploy/` 里同名的两份，只替换这两份，不改原来五项。部署文件带 Kirin9020 环境、`device_alias`、`/assets/native` 和 `/assets/binrunner`。其中的 model/probe/runtime 路径和全 0 摘要是占位，进入锁之前会被当次编译、导出和包校验替换，不能填旧 runtime `29e90492…` 或宿主 `/home/...` 探针路径。目录是只读挂载，通常不用重启容器；若现场发现必须重启，先停下说明，不要连同 App 一起重启。

### 只串行跑这两项

不要选 `all`，不要留空 task。workflow 的 concurrency group 不会替你保留两个排队的 dispatch。先只发 `qwen25-15b-msl-w4a16-kirin9020`，`force=false`，日期用执行日。等该 run 终态、10 次样本和内存归属都通过，并确认手机没有遗留 worker 之后，再单独发 `qwen25-15b-msl-q30-kirin9020`。第一项失败就不要发第二项。Q3_0 的第一次真机不是已经通过的精度结果。
