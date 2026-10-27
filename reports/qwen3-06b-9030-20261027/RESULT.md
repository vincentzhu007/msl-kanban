# Qwen3-0.6B S16S4 / Kirin 9030

2026-10-27 真机实测，复用 Qwen3-4B 验证发布栈。使用仓库 `export_pr1362.py` 完整导出、`bench_recipe.cc` 探针以及 `bench.py resolve/run/summarize`，无临时性能测量实现。

- runtime daily: 5501731a356ffb4ec017a4dc37c3f5631be79489
- export adapter !1362: a6cd83f6a6d4fc8afe426f153d63491fe4a7bb50
- operators !62: abaea09acf6a4cb1e0cf8b6af4ef84f415925941
- S16S4 group 128，decode layout 0，embedding 同为 S16S4；chunk 64。
- 上下文 2048，原始 hello 输入 1024 token，greedy 输出 128，同进程连续 5 次，无预热。
- Mate 80 Pro SGT-AL00 / 5JV0226127000651 / OpenHarmony-6.0.2.130。
- 该系统版本与 4B 历史记录不同，不能将两者当成严格同环境的模型规模对照。

| 指标 | 实测 |
| --- | ---: |
| 总时延 P90 | 2616.443125 ms |
| TTFT P90 | 703.603282 ms |
| Decode 时延 P90 | 2007.056875 ms |
| Decode 速度中位数 | 69.685372 token/s |
| Total PSS 稳定中位数 | 685.196289 MiB |
| Total PSS 采样峰值 | 685.634766 MiB |
| Graph 稳定中位数/采样峰值 | 560.105469 MiB |
| 模型 ROM | 338.769043 MiB / 355225088 bytes |

5/5 status=0、finish_reason=3、output_callbacks=128。P90 最近秩，即五次中的最大值；decode token/s 用首 token 后的127个 token 计算。Total PSS 已含 Graph。

内存有效样本13个，稳定期4个，采样开始时间间隔中位数1000.907ms。峰值为离散采样观测值，可能遗漏瞬时峰值；温度与频率未锁定，未扣除采样开销。

## 汇总校验与审阅

初始 `bench.py run` 完成推理后，在汇总阶段因 `memory-0013.txt` 不完整而失败。该文件明确为 `hidumper: No such process: 19367`，采样始于最后一次推理结束后490.189ms；不是推理阶段数据缺失。

原始 runs 目录保持不变。复制至 results-reviewed 后，仅将该文件移入 excluded/，再通过仓库 summarize 严格校验生成结果，未启用全局 skip_invalid。原始失败文件和排除原因随报告保存。模型/探针的主机与设备哈希验证通过；环境未被标记为正式基线。

## 可复现归档

- dog: `/home/zhugd/llm_archive/20261027-qwen3-06b-s16s4-kirin9030-pr1362-pr62`
- 工作目录: `/home/zhugd/llm_validation/20261027-qwen3-06b-s16s4-9030`
- 导出中间产物: `/home/zhugd/llm_validation/20261026-qwen3-4b-s16s4-9030/qwen3-06b-validation`
- recipe: `recipes/qwen3-06b-msl-s16s4-kirin9030.json`
- environment: `config/dog-qwen3-06b-9030.json`
- MSL SHA256: b817f3bd7e28db5774615822e4fcb41b8f36bf3e5074adf1e76cb56b6e4a7141

看板已发布 `20261027-qwen3-06b-kirin9030.json`，API 已确认可读。原始模型留在 dog，仓库保留配置、日志和结果。
