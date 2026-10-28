# 测量口径

- context=2048，raw prompt 为 ` hello` 重复 1024 次，核对 tokenizer 后为 1024 token；不添加 chat template。
- greedy 输出 128 token，同进程连续 5 次，无间隔，无本进程预热。已有烟测不代表冷机状态。
- TTFT：生成 API 入口至首 token 回调；总时延覆盖整个生成；decode 速度按后续 127 token 计算。加载时间不计入生成时延。
- P90：nearest-rank，`sorted[ceil(0.9*n)-1]`；n=5 时为最大值。
- hidumper 的 Graph 第一列为 NPU PSS；Total 第一列为进程总 PSS。Total 已含 Graph，不能相加；DMA 可能重复反映同一内存。
- 稳定值：用设备 wall/monotonic 时间对齐，选择完整落在第 2–5 次 decode 内的采样，计算中位数。
- 峰值是离散采样观测最大值，可能遗漏短暂峰值；同时保留全采样与推理阶段峰值。单位原始 KiB，网页转换 MiB。
- ROM 为实际部署模型文件字节数，不包含运行库、app 与系统缓存。
- 频率/温度未锁定，内存采样开销未扣除；不同芯片不作同硬件性能对比。MSL 与 GGUF 未验证逐 tensor 权重和量化一致性。
- 页面“规格匹配”仅检查上下文、输入、输出、芯片及次数，还需人工核对模型、量化、线程、协议与构建版本。

JSON 顶层主要字段：`id`、`date`、`framework`、`spec`、`build_commit`、`model`、`timing`、`memory`、`samples`、`memory_samples`。具体示例见 `kanban/data/`。服务只检查对象包含 `spec` 和 `samples`，尚无严格 schema 校验；导入前需检查字段和单位。
