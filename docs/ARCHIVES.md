# dog 复现归档

根目录 `/home/zhugd/llm_archive/`：

| 目录 | 内容 |
|---|---|
| `20261026-qwen25-05b-w4a16-kirin9020-ctx2048-in1024-out128` | MSL 9020 模型、构建、原始测量 |
| `20261026-llama-q40-cpu9020-ctx2048-in1024-out128` | llama.cpp CPU、GGUF、源码与测量 |
| `model-identity-verification-20261026` | Instruct 模型身份核对 |
| `20261026-qwen3-4b-s16s4-kirin9030-daily-failed` | 原始 daily 失败证据 |
| `20261026-qwen3-4b-s16s4-kirin9030-pr1362-pr62` | 成功 PR 组合，模型、算子、源码、依赖、配置、SHA256SUMS |

Qwen3 成功模型 SHA256：`60056f613c4d5ff5721d92f46486f01fd0b4bf573aefd41e40954f642111ea17`，2285402624 字节。运行库及其他模型的身份信息见相应结果 JSON/provenance。

本仓保留小体积原始测量，避免将模型或大体积二进制加入 Git。旧报告中的路径是当时环境记录；完整 SHA256SUMS 可能引用仅在 dog 归档中的文件，不能在裁剪后的本仓直接验证整份旧清单。
