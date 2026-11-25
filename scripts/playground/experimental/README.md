# Qwen3.5 临时统计程序

`build_qwen35_stats.py` 针对 dog 上的 PR 1415 复现环境构建临时程序，
并非 daily 评测或通用构建入口。

- 源码：PR 1415，提交 `9c5df2df698ff328eac423b831828202f4943e36`。
- 构建容器：`hf-agent-qwen35-moe-merge`。
- 输出：容器内 `/tmp/kanban-q35-stats/hf-q35-kanban-stats`。
- 在 `PrepareGeneration` 的 tokenizer Encode 后打印实际输入 token 数，包含 chat template。
- Prefill 速度使用该数量除以 mslite-chat 首 token 耗时；计时开始于模型加载之后，
  包含分词、prefill 和首次采样，不包含模型加载及网页传输。
- Decode 速度沿用 mslite-chat 的后续输出计数与耗时。

构建保留原来的链接配置，并重编译整个 NNRT backend 及聊天入口，启用
`QWEN35_Q2_EXPERIMENT`。不要仅替换 qwen35 子目录的对象文件：旧 NNRT
对象可能与当前头文件布局不一致，已在真机验证中导致模型加载失败。

程序需使用 `br push` 推送到 3001 设备，并用同一组模型参数验证成功后，
才能修改 `../qwen35-preview.py` 中的 `PROGRAM`。线上更新需要取得设备租约，
避免中断请求。适配器通过 `--prompt-file` 传递输入，用户文本不参与命令拼接。
