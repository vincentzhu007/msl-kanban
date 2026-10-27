# Qwen2.5-0.5B W4A16 · Kirin 9020 · 2026-10-26 每日运行库性能测试

状态：完成。五组独立进程均正常退出；每组对两档输入分别预热一次并测量一次，共 10 条正式样本、10 条预热样本。每次正式生成均为 128 token，正常以输出长度上限结束。

## 结果

下表为 5 次正式测量的中位数，括号内为最小—最大值。使用合成输入，未评估模型回答质量。

| 输入 → 输出 | 首 token 延迟 TTFT | 解码速度 | 生成总耗时 | 进程内存高水位中位数 |
|---|---:|---:|---:|---:|
| 64 → 128 | 101.36 ms（100.34–102.72） | 39.02 token/s（38.92–39.11） | 3.356 s | 143.38 MiB |
| 512 → 128 | 685.86 ms（680.13–695.23） | 39.05 token/s（38.96–39.11） | 3.940 s | 143.43 MiB |

模型加载耗时中位数：**726.75 ms**（709.36–748.93 ms），未计入上表 TTFT；多次加载可能使用系统页缓存，因此不称为冷启动。

模型文件为 **275.32 MiB**（288,692,736 bytes）；每日包内原始 CLI 为 4.80 MiB，两者合计 **280.12 MiB**。这只表示模型与独立 CLI 文件之和，不含 BinRunner、系统 NPU 运行库、运行时解包缓存等，不能称为完整安装 ROM。

## 测试身份与协议

- 每日构建：[用户指定归档](https://repo.mindspore.cn/mindspore/mindspore-lite/version/202610/20261026/master_20261026010016_5501731a356ffb4ec017a4dc37c3f5631be79489_newest/lite/ohos_aarch64/mindspore-lite-llm-linux-x64-0.2.0.tar.gz)，版本 0.2.0，commit `5501731a356ffb4ec017a4dc37c3f5631be79489`。
- 归档 SHA-256：`29e904924e12e4bc351f9b99569602f1fd2bb7b2a8cf4ea3c160866ca795b046`。
- 设备：dog → `127.0.0.1:2000`，HUAWEI Mate 70 Pro / PLR-AL00 / Kirin 9020。
- 系统：`6.1.0.135(SP8C00E120R4P5)`；已有 BinRunner 调用 NNRT，日志显示 NPU EXTREME 模式。
- 模型：手机现有 `@/bin/st3_qwen25.msl`；元数据架构 `qwen2.5-0.5b`，24 层，hidden 896，14 attention heads、2 KV heads，vocab 151936。
- 模型设备端 SHA-256：`f86dd4a7f4b2b6a0794f965cae91b11a4b444dbd304d931ffa900c1228e3f9a2`。
- 量化：`npu.embedding_format=W4A16`，group 32，`q4_0_nzf_compact_phase4`，量化 embedding 开启。部署上下文 1024，prefill chunk 64；模型架构 max_position 32768 不代表本产物支持 32768。
- 输入：原始字符串 ` hello` 重复 64 / 512 次，不套 chat template。服务器已有 HF tokenizer 核验分别为 64 / 512 token；公开 C API 未提供运行时输入 token 计数。分词器哈希见 `tokenizer.sha256`。
- 输出：greedy，max_new_tokens=128，repetition_penalty=1。回调中不输出文本，避免日志 I/O 影响测量。
- 每个新进程中：64 输入预热→正式；512 输入预热→正式。每次生成后等待 3 秒，进程间等待 15 秒；共 5 个进程。没有锁定温度、CPU 频率或电量条件。
- TTFT：设备 steady_clock，从调用 MSLLMStreamGenerate 至第一个 token 回调，含 tokenization、prefill、首 token 采样，不含 BuildModel。解码速度为后续 127 个回调数除以首末回调时间差。
- 内存：进程 VmRSS 和 getrusage ru_maxrss，包含 BinRunner fork 继承的内存；不包含可确认的全量 NPU/服务侧内存。不同进程基线有波动，因此不可把该值当作纯模型 RAM。

## 版本边界和发现

本次使用每日归档中未修改的 `libmindspore-lite-llm.a`，按照官方示例以 whole-archive 方式保留 NPU 后端注册。原始每日 `mslite-chat` 也已完成短对话冒烟验证。测试程序源码与库哈希已归档。

**本次是运行库更新后的固定模型测试。** 手机上的编译模型没有用当日转换工具及算子包重新导出，因此结果不代表每日构建的转换器、编译器和算子包全链路收益。

先前 2048 上下文的旧模型被每日运行库拒绝，错误为 `FP16 embedding requires embedding_quant=false`；改用手机现有、具备新格式字段的 1024 上下文模型后通过契约检查。旧测试与本次上下文及模型哈希不同，不计算历史回归百分比。

原 CLI 的 `[stats] prefill: 1 token` 表示首个输出 token 的等待时间，不能拿这个 1 当输入 token 数计算 prefill 吞吐。本报告也没有将 TTFT 折算值称为纯 prefill 速度。

## 交付文件

- [结构化结果](benchmark.json)：测试身份、协议、中位数与范围。
- [对比表 CSV](summary.csv)：两档场景，可作为看板手动导入源。
- [正式样本 CSV](samples.csv) 与 [全部样本 JSON](samples.json)：后者包含预热。
- `cycle-1.log` 至 `cycle-5.log`：五组正式执行原始日志。
- `SHA256SUMS`：每日程序、静态库、动态库、测试程序和源码校验值。
- [复跑说明](../../../scripts/edge_slm_bench/README.md)：源文件实际位于工作区 `scripts/edge_slm_bench`，远程参数写明在文档中。

服务器结果目录：`/home/zhugd/llm_validation/20261026-qwen25-05b-w4a16-9020`。模型只在设备上进行哈希和元数据检查，没有复制模型权重。尚未配置周期调度或上传到 MLflow。
