# msl-kanban

端侧 LLM 真机评测与性能看板。整理自 2026-10-26 dog / Kirin 9020、9030 实测代码；包含 MSL-LLM NPU、llama.cpp CPU，以及 Qwen3-4B PR 组合验证。

## 目录

| 目录 | 内容 |
|---|---|
| `kanban/` | Python 标准库服务、网页、Docker Compose、实测数据 |
| `scripts/edge_slm_bench/` | MSL C++ 探针、hidumper 采集、统计、PR 导出/编译适配 |
| `scripts/edge_llama_bench/` | llama.cpp CPU 探针、OHOS 兼容头、采集和统计 |
| `reports/edge-slm/` | 9020 原始测量、模型身份核对和统计结果 |
| `reports/qwen3-9030-daily-20261026/` | 原始 daily 失败记录、PR 筛选、成功验证及原始测量 |
| `docs/` | 运行说明、测量口径、归档索引与业界调研 |

## 启动看板

自托管服务默认不要求登录，仅在本机监听 18765 端口：

```sh
docker compose -f kanban/compose.yaml up -d --build
```

也可以直接运行 `python3 kanban/server.py --host 127.0.0.1`。默认 Docker 镜像为 `python:3.11-slim`；dog 已有镜像可用 `KANBAN_BASE_IMAGE=mini-lite-llm:latest`。数据只读挂载，新增结果 JSON 放入 `kanban/data/`，页面每 60 秒刷新。网页手动导入仅存于当前浏览器；持久发布需要将 JSON 写入该目录。

公开静态看板：[msl-kanban.vercel.app](https://msl-kanban.vercel.app/)，由 GitHub 仓库 `vincentzhu007/msl-kanban` 的 `main` 分支更新，详见 [Vercel 部署说明](docs/VERCEL.md)。已有 dog 服务目录：`/home/zhugd/llm-infra/dashboard`。

## 评测与复现

见 [运行说明](docs/RUNBOOK.md)、[数据口径](docs/MEASUREMENT.md)、[归档索引](docs/ARCHIVES.md)。

- 正式规格：上下文 2048、输入 1024、输出 128，同进程连续 5 次。
- P90 使用 nearest-rank，5 次测量对应最大值。
- 看板第四个指标及框架对比使用总 PSS 稳定中位数；Graph 代表 NPU 内存。
- PR 验证为 daily 运行库 + !1362 导出适配 + !62 分支重编译算子，默认 `decode_layout=0`。
- 手机执行脚本保留已验证的 dog 路径、设备及模型名。运行前核对这些配置；它们不是开箱即用的跨环境 CI。
- Daily/weekly 自动调度尚未接入；本仓提供评测、统计和展示代码。不能将页面自动刷新理解为定时评测。

模型、GGUF、SDK、DDK、daily 包和编译产物不入 Git，完整复现资产在 dog 归档。量化精度、温度锁定和 PR 新性能路径 A/B 不在已有验证范围内。

## Recipe v1 扩展入口

新增模型优先添加 `recipes/*.json`，设备与文件路径放在独立 environment 中。统一命令为 `python3 scripts/bench.py validate|resolve|run|summarize`。详见 [Recipe 使用说明](docs/RECIPE_V1.md)。当前支持预部署 frozen model，自动调度、基线批准和回退告警尚未实现；新参数化探针需经过真机验证后再正式使用。
