# CANN Kit LLM 竞品接入调查（2026-10-27）

## 当前结论

尚未取得可比性能数据，未新增看板测试结果。目标是 Qwen2.5-0.5B-Instruct、Kirin 9020、2K 上下文、1024 输入、128 输出、连续 5 次，复用既有 P90、hidumper PSS/Graph 和 ROM 统计协议。

## 已检查的资产

- dog SDK：`/home/zhugd/tool/CANN-Kit-6.0.1.0.zip`
  - SHA256 `a83671d469285b7aa774f17b7b8d6114e9d09b3d93d7bf786b400a633c100526`
- 解压归档：`/home/zhugd/llm_validation/cann-kit-llm/sdk/ddk/hiai_lm_engine/`
- `lib64/libhiai_llm_engine.so`：1,727,392 bytes
  - SHA256 `7ba643bbe617f73728b9de6490377d400c63fbb22dd543bbb4ec524e48853a84`
  - ELF aarch64；`.note.android.ident` 标记 Android NDK r26d、API 21。
  - NEEDED 含 liblog.so、libdl.so、libc++_shared.so、libc.so；版本要求包含 LIBC。
  - 提供 LLMEngine_Executor_CreateFromJson、LLMEngine_Executor_LLM_Generate、Prompt_SetText/SetTokenIds、Context token count、prefill/decode/total time、token 回调等 API。
- dog 鸿蒙 SDK 的 `hms/native/sysroot/usr/include/CANNKit` 仅找到 hiai_aipp_param.h、hiai_helper.h、hiai_options.h、hiai_single_op.h、hiai_tensor.h；该目录未提供 LLM 头文件。
- `/home/zhugd/code/ms/douyin_llm/config_qwen2_5_embedding_W4A16_decode_W4A16_layer_24.json` 是现有 MSL pack 配置：max_length=1024、vocab_size=114300、do_sample=true。它不符合现有 2K 原始词表/greedy 协议，也不能据此证明其中 OMC 可直接用于 CANN LLM 引擎。
- 在 douyin_llm、ms 源码、LiteAgent 和相关 OHOS 样例的定向搜索中未找到配套 LLMEngine executor JSON 使用示例。

## 9020 实测预检

仓库 `scripts/edge_cann_bench/check_runtime.cc` 用 dog OHOS NDK 编译成功，上传至现有 BinRunner；仅测试 dlopen 与符号检查，不执行推理。

1. `check-cann-runtime @/bin/libhiai_llm_engine.so`

```text
exit=1 timedOut=false
CANN_RUNTIME_LOAD_FAILED: Error loading shared library /data/storage/el2/base/haps/entry/files/bin/libhiai_llm_engine.so: Permission denied
```

2. `check-cann-runtime libhiai_llm_engine.so`

```text
exit=1 timedOut=false
CANN_RUNTIME_LOAD_FAILED: Error loading shared library libhiai_llm_engine.so: Permission denied
```

这表明当前 BinRunner 应用加载路径未通过。不能将 Permission denied 当作 ABI 错误或全系统不存在该库的证据。Android 构建身份是独立的静态检查结论；还需鸿蒙原生 SDK/官方打包方式验证。

## 待补齐

1. 鸿蒙原生 CANN Kit LLM SDK 及官方样例（包含 executor/context JSON、动态库打包和所需应用权限说明）。
2. Qwen2.5-0.5B-Instruct 的配套导出/量化/编译流程或具备完整来源信息的 2K 模型包。
3. 确认 9020 和当前系统版本支持范围。

具备这些输入后，按照 `scripts/edge_cann_bench/README.md` 的准入条件接入 recipe runner。没有实际运行数据前不填充零值、估算值或占位性能结果。

## 用户补充的鸿蒙 DDK 6.1.1（2026-10-27）

路径：`/home/zhugd/tool/hisi_ddk/install_pkg/hisi_ddk_pkg-6.1.1.0`。

已检查完整 ZIP 目录、头文件内 LLMEngine_ 标识、嵌套 wheel 目录，以及工具/插件 lib64 下 ELF 架构：

| 包 | 条目数 | 内容 |
| --- | ---: | --- |
| DDK-tools-next-6.1.1.0.zip | 2937 | tools_ascendc、tools_dopt、tools_omg、platform 配置说明 |
| kirin9020-plugin-next-6.1.1.0.zip | 49 | 9020 算子编译库、仿真器、平台配置 |
| kirin9030-plugin-next-6.1.1.0.zip | 48 | 9030 算子编译库、仿真器、平台配置 |
| kirinx90-plugin-next-6.1.1.0.zip | 48 | X90 算子编译库、仿真器、平台配置 |

上述范围内检查到的 ELF 库均为 EM_X86_64（62），用于主机工具；未找到命名含 llm/lm_engine/qwen/llama 的文件，头文件中未找到 LLMEngine_ API。DOPT 的可见 demo 为 NAS/quant8-8 等，未找到 Qwen 大模型量化导出示例。这些检查不能排除通用工具可用于某些大模型编译步骤，但这四个包不能提供当前缺少的鸿蒙手机端 LLM 推理引擎。

该路径补齐了可候选使用的主机 DDK/芯片插件来源；仍缺手机端 CANN Kit LLM SDK、配套运行配置和模型导出流程。尚未进行新的推理测量或发布看板数据。

完整包 SHA256 和库架构清单：`reports/cann-kit-llm/ddk-6.1.1-inventory.json`。dog 同步归档在 `/home/zhugd/llm_validation/cann-kit-llm/ddk-6.1.1-inventory.json`。
