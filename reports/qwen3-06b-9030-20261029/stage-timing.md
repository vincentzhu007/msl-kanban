# 独立阶段计时验证 · 2026-10-29

代码：56ab8e9。使用仓库 daily.py 在 dog Docker runner 中重编译探针、校验模型与探针哈希、自动前台保活、串行执行。Qwen3-0.6B / Kirin9030，ctx2048 / input1024 / output128，每组10次，无预热。

| 框架 | 初始化单次 s | Prefill P90 s | TTFT P90 s |
| --- | ---: | ---: | ---: |
| llama.cpp CPU Q4_K_M | 0.955156 | 11.540524 | 11.544947 |
| MSL-LLM NPU S16S4 | 0.776889 | 未暴露独立计时 | 0.752732 |

初始化为每进程一次，不是P90；文件缓存不受控，不能称为冷启动。TTFT不含初始化。CPU Prefill为分词之后的全部输入batch计算及同步，不含采样。MSL现有公共API和日志没有Prefill边界，需要运行库提供阶段计时后接入，不以TTFT代替。

代码快照：`/home/zhugd/msl-kanban-ci/comparisons/stage-timing-20261029/`。

- CPU任务：`/home/zhugd/msl-kanban-ci/tasks/daily-20261029-qwen3-06b-llama-q4km-kirin9030-ea270679b95b-1/`
- MSL任务：`/home/zhugd/msl-kanban-ci/tasks/daily-20261029-qwen3-06b-msl-s16s4-kirin9030-20c7b51342f6-1/`

各任务的archive.json定位原始运行目录；保存source.tar.gz、工具链、编译日志、recipe/环境锁、初始化事件、逐次Prefill（CPU）及内存原始采样。MSL排除了一条最终推理结束后进程已退出的终止内存采样，其余校验通过，稳定内存样本3个。
