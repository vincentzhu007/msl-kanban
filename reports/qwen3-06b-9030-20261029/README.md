# Qwen3-0.6B · Kirin9030 CPU/NPU 对照（2026-10-29）

## 实测结果

协议：OpenHarmony 6.0.2.130，ctx2048 / input1024 / output128，同进程连续10次，无预热，raw hello、greedy。两组串行执行，通过仓库 `scripts/bench.py run --lock` 完成；未使用临时替代测量脚本。

| 部署方案 | ROM MiB | 总PSS稳定中位 / 采样峰值 MiB | TTFT P90 s | TOPT P90 ms/token | Decode P90 token/s | 稳定内存采样数 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| llama.cpp CPU / Q4_K_M | 461.79 | 998.60 / 998.92 | 11.337 | 49.91 | 22.09 | 15 |
| MSL-LLM NPU / S16S4 | 338.77 | 645.24 / 645.65 | 0.753 | 14.79 | 69.22 | 4 |

最近秩 P90 取10次升序第9个值。TOPT按每次decode_ms/(output_callbacks-1)计算；Decode P90不是其倒数。TTFT包含分词、Prefill及首次采样，未独立测量Prefill。总PSS已包含Graph。ROM不包含运行库。系统温度和频率未锁定，性能基线资格未批准；不同量化部署方案不能视作等精度框架比较。

## 版本与来源

- llama.cpp：07822bddf80d73f1168e592c52e69caaff820f9c，Release/O3、armv8.2-a+dotprod、静态库，OpenMP/KleidiAI关闭。CPU 4线程，batch=ubatch64，GPU layers=0，FP16 KV，Flash Attention关闭。
- Q4_K_M模型：[bartowski/Qwen_Qwen3-0.6B-GGUF](https://huggingface.co/bartowski/Qwen_Qwen3-0.6B-GGUF/tree/60b85c0e3d8fe0f6474f406922a26d12aca4550d)，上游Qwen/Qwen3-0.6B，imatrix量化，混合tensor类型。文件484220320字节，SHA256 `9acfc1e001311f34b4252001b626f2e466d592a42065f66571bff3790d4e1b14`。
- NPU使用20261029 master daily `e77e35f8f5bb`及固定归档S16S4模型，group128/layout0。模型355225088字节，SHA256 `b817f3bd7e28db5774615822e4fcb41b8f36bf3e5074adf1e76cb56b6e4a7141`。
- 探针与模型均经host/手机沙箱SHA256校验；实际输入1024及输出128 token、10个连续run及探针SPEC均校验通过。

## 自动化和失败记录

直接亮屏并不足够：鸿蒙锁屏会使后台BinRunner进入 `freezer:/Frozen`。仓库已加入正常上滑、前台确认、屏幕保活和冻结检测；不输入密码或绕过认证，受认证锁阻挡时失败退出。测量结束恢复屏幕超时。CPU有效测量使用自动唤醒/前台确认；NPU最终复测进一步启用10秒周期唤醒。两组有效采样均处于Thawed/top-app，未发现冻结。

以下记录被排除，未发布性能数字：首次新模型未部署的校验失败 `f8ea9c309c51`；系统冻结影响的CPU测量 `51fac522a879`、`2765786d5e53`；冻结检测拦截的NPU测量 `3895174b9b0a`。失败现场保留在dog。第一次通过的NPU十次结果 `5e5bd158fcde`保留为历史记录，最终对照采用下面的最新复测。

## dog 可复现归档

- 模型和来源元数据：`/home/zhugd/msl-kanban-ci/models/qwen3-06b-q4km/`
- 固定源码、编译配置、工具链、探针及原始lock：`/home/zhugd/msl-kanban-ci/tasks/daily-20261029-qwen3-06b-llama-q4km-kirin9030-2fa4038fad83-1/`
- CPU有效原始日志和内存采样：`/home/zhugd/msl-kanban-ci/runs/qwen3-06b-llama-q4km-kirin9030-f4ddb98cf4a0/`
- NPU有效原始日志和内存采样：`/home/zhugd/msl-kanban-ci/runs/qwen3-06b-msl-s16s4-kirin9030-bb7c9d49b6a9/`
- 仓库执行快照：`/home/zhugd/msl-kanban-ci/comparisons/qwen3-06b-20261029/`。CPU采集代码commit `6d50224`，NPU最终采集代码commit `76f1f5a`；探针编译源commit `a475ee8`。
- 每个有效run保存 `resolved-recipe.json`、`inference.log`、`samples.json`、内存文件、原始 `kanban-result.json` 及脱敏的 `public-kanban-result.json`/`public-job.json`。

CPU复现（runner容器中，前提为归档模型和探针已部署）：

```sh
cd /data/comparisons/qwen3-06b-20261029
python3 scripts/bench.py run --lock /data/tasks/daily-20261029-qwen3-06b-llama-q4km-kirin9030-2fa4038fad83-1/resolved-recipe.json
```

本次新增CPU recipe为手动对照任务，未自动加入每日工作流矩阵。
