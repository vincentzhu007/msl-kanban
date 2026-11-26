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
才能切换服务使用的程序。线上更新需要取得设备租约，避免中断请求。

当前常驻版本使用 `build_qwen35_resident.py`，输出 `hf-q35-kanban-resident-v3`，
由 `../qwen35_resident.py` 的 `PROGRAM` 选择。它复用上面的已验证后端归档，
仅重编译 pipeline、sampler 与聊天入口。用户消息通过回环 TCP 的角色与 UTF-8 长度协议传输，
不参与命令拼接。模板接口不追加生成前缀，服务显式追加 Qwen3.5 非思考前缀。
presence penalty 通过临时内部桥接设置；此接口不属于正式 Lite LLM API。
当前上游 sampler 的 top-k / top-p 分支互斥，临时构建修正为先 top-k 后 top-p，
确保两个参数都生效；不修改 daily 构建或原始源码目录。

`sampler_check.cc` 验证 top-k 与 top-p 同时生效：固定 seed、3 个候选、top_k=2、
top_p=0.1 时，1000 次采样应只选择最高概率 token。使用源码 include/src 目录编译，
分别链接原 sampler.cc 与临时生成的 sampler.cc，可复现修复前失败、修复后通过。

流式 token 片段通过 ASCII 十六进制字段 `content_hex` 传输，由 Python 按请求增量解码 UTF-8；
不能将 token 片段直接写成 JSON 字符串，尤其是达到输出上限或取消时的尾部字节可能不完整。
完整的跨片段中文和 emoji 无损拼接；真正无效或最终残缺的编码使用替换字符，保持生成与结束事件可读。
统计仍按原始 runtime 回调计数，不按拼接后的字符片段计数。
