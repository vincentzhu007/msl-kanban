# 2026-10-27 校验修复与 9020 E2E

结论：通过。修复已进入 msllm-dev-ci 仓库；执行使用同步到 dog 的仓库快照，没有临时替代推理或汇总脚本。

## 修复

BinRunner 启动程序时 argv[0] 可能变成 @13，导致重命名后的 Toybox 无法选择 sha256sum applet。新增 `scripts/device_tools/sha256sum.cc` 独立流式校验工具，不依赖 argv[0]。主机执行入口保留失败即停止的规则，并保存设备校验 stdout/stderr。

14 项测试通过，包含空输入、abc、百万字符、SHA 填充边界、读缓冲边界、argv[0]=@13 和缺失文件。设备编译产物 SHA256 为 `ef94b21be2a1ca8420dff2be681d8ad3730bedae629c95ec05aaf8ee0d24ee4c`。

## 真机 E2E

执行仓库现有 `bench.py validate` → `resolve` → `run`，由 run 调用仓库探针并自动汇总。

- daily commit：5501731a356ffb4ec017a4dc37c3f5631be79489（20261026 已归档包）。
- 模型：Qwen2.5-0.5B-Instruct W4A16 / Kirin9020 / PLR-AL00。
- 规格：上下文2048、输入1024、输出128、同进程连续5次、无预热。
- 模型和 probe 的设备 SHA256 均与主机归档匹配。
- 5/5 status=0、finish_reason=3、output_callbacks=128。
- 25份内存样本，其中11份完整处于第2–5次Decode稳定区间。

| 指标 | 实测 |
|---|---:|
| 总时延 P90 | 5121.964843 ms |
| TTFT P90 | 1602.628906 ms |
| Decode 速度中位数 | 36.122194 token/s |
| 总PSS稳定中位数 | 444022 KiB / 433.615 MiB |
| 总PSS采样峰值 | 508796 KiB / 496.871 MiB |
| Graph稳定中位数及峰值 | 319664 KiB / 312.172 MiB |

本次证明校验与评测链路能够走通，不自动批准性能基线。温度、频率等环境资格尚未自动核验，baseline_eligible 保持 false。结果中的 date 为设备采样时间转换的 UTC 日期；本文日期采用 Asia/Shanghai（2026-10-27）。

## 证据

- dog 验证根目录：`/home/zhugd/llm_validation/msllm-dev-ci-9020-e2e-v2`。
- 运行目录：`runs/qwen25-05b-msl-w4a16-kirin9020-85fdc246798b`。
- 结果 JSON：本目录对应运行子目录的 `dashboard-result.json`。
- 原始推理与内存日志、配置、锁定清单、CSV 均已随结果归档。
- `verification/` 保存模型和 probe 的设备校验原始输出。
- 运行源码包 SHA256：`1513a20aa87c5b9e2bee8332d6bbd25930a7fc0d03d5b92ee8007c971c2bb185`。

未更新线上看板，未 commit/push。上一轮失败证据保留在相邻的 `e2e-qwen25-9020-recipe-v1` 目录。
