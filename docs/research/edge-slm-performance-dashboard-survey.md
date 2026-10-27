# 端侧 SLM/LLM 性能数据看板调研

核对日期：2026-10-26。范围：手机及其他个人端设备上的本地推理；只采用项目官方页面、官方文档、源码或发布者自己的测量说明。这里的“ROM”定义为**设备持久存储占用**，包括模型权重、分词器、视觉投影器、运行库及必要的编译产物；它与运行时 RAM / 峰值内存不是同一指标。下表的“公开”只表示来源明确提供该字段，**不表示各来源可直接横向排名**。

## 六个代表性方案

| 方案与定位 | 模型规格、量化 | 性能 | 内存 | ROM / 文件大小 | 可借鉴点与边界 |
| --- | --- | --- | --- | --- | --- |
| [Qualcomm AI Hub 模型页](https://aihub.qualcomm.com/mobile/models/qwen3_5_2b)：芯片/模型组合目录 | **公开**：模型架构与支持设备；[官方模型仓库](https://github.com/qualcomm/ai-hub-models/blob/v0.65.0/src/qai_hub_models/models/qwen3_5_2b/README.md)给出 Q4_0 量化和 GenieX/llama.cpp 下载配方 | **提供查询入口**：官方仓库说明 CLI 可查性能与准确率；该网页当前静态视图未展示可复核的逐设备数值 | **未在该模型页公开**运行峰值 RAM | **未在当前静态视图确认**模型文件和整套部署 ROM 的具体数值 | 借鉴“模型 × 量化 × 设备”的目录和可下载部署配方；页面会按芯片入口切换，留存结果时必须记录设备/后端/上下文。当前静态页面显示“Not supported”，不据此引用设备跑分。 |
| [MLPerf Inference: Mobile](https://mlcommons.org/benchmarks/inference-mobile/)：标准化设备结果榜 | **公开**：套件版本、基准模型、提交设备/软件栈；v6.0 包含 Llama 3.2 3B Instruct 和 Llama 3.1 8B Instruct | **公开**：交互结果表和情景指标；Mobile 要求 Single Stream，页面将其定义为第 90 百分位延迟，并链接提交详情/代码 | **未作为核心榜单字段公开** | **未作为核心榜单字段公开** | 借鉴“版本、场景、质量门槛、提交元数据、代码链接”；不能把不同版本/Division/可用性类别混作一组。官方 [v6.0 发布说明](https://mlcommons.org/2026/06/mlperf-mobile-v6/)还列出 1B/3B/8B 移动 LLM 测试，具体当前结果以结果页及规则为准。 |
| [Google AI Edge Gallery](https://github.com/google-ai-edge/gallery)：设备上模型管理与即时 benchmark | **公开**：选择/下载/导入本地模型；[官方介绍](https://github.com/google-ai-edge/gallery/wiki/1.-Overview)支持跨模型切换 | **公开**：官方介绍列出实时 TTFT、decode speed、latency；README 说明可在本机运行 benchmark | **未从官方总览确认** benchmark 同屏显示峰值 RAM | **模型下载管理公开**；[1.0.19 发布记录](https://github.com/google-ai-edge/gallery/releases)说明 Android 用 Hugging Face API 获取模型大小，但它不是“安装后总 ROM” | 借鉴“在目标手机实测、模型可导入、交互式配置”；数值是当前设备本地结果，不是统一公开排行榜。 |
| [PocketPal AI / AI Phone Leaderboard](https://github.com/a-ghorbani/pocketpal-ai)：手机自测与自愿分享 | **公开**：GGUF 模型选择、量化与设备信息；官方 README 说明从 Hugging Face 选适合设备内存和存储的量化 | **公开**：Benchmark 页测 token/s，结果可选择提交榜单；[界面文案源码](https://github.com/a-ghorbani/pocketpal-ai/blob/main/src/locales/en.json)区分 prompt processing、token generation 和总时间，并保存 PP/TG/重复次数、上下文、线程、GPU 层等设置 | **公开**：Benchmark 页显示 memory，结果卡含 peak memory；模型列表有估算内存提示 | **模型下载大小/可用存储用于选择**，但 README 未称 benchmark 记录整套部署 ROM | 借鉴“模型—量化—设备—配置—结果”单次运行记录，以及用户同意后上榜。社区数据质量需单独控制；[项目设备规则说明](https://github.com/a-ghorbani/pocketpal-device-rules)曾记录峰值内存遥测损坏/噪声，因此不能把社区峰值直接当真值。 |
| [llama.cpp llama-bench](https://github.com/ggml-org/llama.cpp/blob/master/tools/llama-bench/README.md)：可脚本化原始数据来源 | **公开**：输出含模型类型、参数量、量化类型、后端、线程/GPU 层、KV 类型等 | **公开**：pp/tg/pg 测试，平均 tok/s、标准差及每次样本；可扫 prompt/generation 长度与 context depth | **不直接输出**进程峰值 RAM；`fit-target` 是适配设备内存的配置，不能当实测 RAM | **公开**：模型 `size` / `model_size`，可作为权重文件大小；不含应用、运行库、外部记忆 | 借鉴 CSV/JSON/JSONL/SQL 导出及完整运行参数。官方明确指出**不计 tokenization 和 sampling 时间**，因此其吞吐不能冒充端到端 TTFT。 |
| [MLPerf Client](https://mlcommons.org/benchmarks/client/)：PC 本地 LLM 用户体验榜 | **公开**：基准模型、任务类别及各类约定输入/输出长度 | **公开**：TTFT 和首 token 后 TPS；例如内容生成约 128→256 token、代码分析约 1856→128 token | **并非本页核心结果字段** | **并非本页核心结果字段** | 虽面向 PC 而非手机，其“TTFT + 后续 token 速率”定义和按输入长度分组适合迁移到端侧 SLM 看板；不能与 Mobile 的 Single Stream 第 90 百分位延迟混称为一个指标。 |

## 结论与拟议看板字段

**观察（有来源）**：Qualcomm 提供模型、量化配方、支持设备和性能查询入口；PocketPal 将设备上的速度与峰值内存放在同一次记录；llama-bench 提供机器可读的完整测试配置；MLPerf 强调版本、情景和质量门槛。[来源：Qualcomm](https://github.com/qualcomm/ai-hub-models/blob/v0.65.0/src/qai_hub_models/models/qwen3_5_2b/README.md)、[PocketPal](https://github.com/a-ghorbani/pocketpal-ai)、[llama-bench](https://github.com/ggml-org/llama.cpp/blob/master/tools/llama-bench/README.md)、[MLPerf Mobile](https://mlcommons.org/benchmarks/inference-mobile/)。

**本项目建议（推断/设计判断，非业界现成统一规范）**：以一条“模型构建 × 量化配方 × 设备 × 后端 × 测试场景 × 一次运行”作为数据主键，分四层展示：

1. **模型与部署配方**：模型版本/hash、架构、总/激活参数、原生上下文、模态；权重精度与逐层混合量化、KV cache 精度、格式、运行时及 build/commit、CPU/GPU/NPU 分工。
2. **ROM / 持久存储**：权重文件、tokenizer、投影器/外部记忆、编译缓存/运行库分别列字节数，再给“下载量”和“安装后总占用”。多模态附件遗漏会低报。未实测的项显示“缺测”，不要用参数量×bit 数冒充文件大小。
3. **运行 RAM 与性能**：加载后常驻、prefill/decode 过程中峰值 RAM（注明 RSS、PSS、物理占用或 GPU/NPU 内存的具体口径）、KV/工作区；冷启动、prefill tok/s、TTFT、decode tok/s、TPOT、请求总耗时，分 P50/P90/P95 与样本数。TTFT/TPS 的用户体验定义可参见 [MLPerf Client](https://mlcommons.org/benchmarks/client/)；`llama-bench` 的 pp/tg 不含 tokenization/sampling，需另测端到端路径。[来源](https://github.com/ggml-org/llama.cpp/blob/master/tools/llama-bench/README.md)。
4. **复现与质量约束**：设备型号/SoC/RAM、OS、功耗/温度状态、线程、batch、prompt/decode 长度、上下文深度、采样参数、冷/热缓存、重复次数、原始结果和准确率/任务质量；不同场景先分组再比较。MLPerf Mobile 的质量目标、Division 与情景区分给出了范例。[来源](https://mlcommons.org/benchmarks/inference-mobile/)。

这与本仓库现有 [Qwen3.5-4B 端侧探索](../QWEN35-4B-EDGE-EXPLORATION.md)的成本审计项对应：模型文件及外部记忆、峰值内存、prefill、TTFT、TPOT、端到端延迟和能耗。**仍需自测**实际 ROM 总占用、峰值 RAM、能耗及持续运行热降频；上列产品公开字段不能替代本项目目标机测量。
