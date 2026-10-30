# msl-kanban

当前看板发布版本：v0.2（2026-10-30）。看板版本与 lite_llm 框架版本独立管理。

MindSpore Lite 端侧 LLM 开发者看板。看板内容包括：LLM模型评测、业界框架性能对比（llama.cpp、hisi lm_engine）、性能Profiling。

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

公开静态看板：[msl-kanban.vercel.app](https://msl-kanban.vercel.app/)，由 GitHub 仓库 `vincentzhu007/msl-kanban` 的 `main` 分支更新，详见 [Vercel 部署说明](docs/VERCEL.md)。

## 评测与复现

见 [运行说明](docs/RUNBOOK.md)、[数据口径](docs/MEASUREMENT.md)、[归档索引](docs/ARCHIVES.md)。

- 正式规格：上下文 2048、输入 1024、输出 128，同进程连续 10 次（历史记录保留原始次数）。
- P90 使用 nearest-rank，10 次测量取升序第 9 个值；历史 5 次测量取最大值。
- 看板第四个指标及框架对比使用总 PSS 稳定中位数；Graph 代表 NPU 内存。
- PR 验证为 daily 运行库 + !1362 导出适配 + !62 分支重编译算子，默认 `decode_layout=0`。
- 手机执行脚本保留已验证的 dog 路径、设备及模型名。运行前核对这些配置；它们不是开箱即用的跨环境 CI。
- Daily 已提供 GitHub Actions 手动/定时入口，覆盖 Qwen2.5-0.5B、Qwen3-4B、Qwen3-0.6B 的 MSL 评测及固定版本 llama.cpp CPU 每日对照；CANN Kit 单独记录依赖阻塞；部署与运行方式见 [Daily 说明](docs/DAILY.md)。weekly 竞品和回退告警尚未接入。

模型、GGUF、SDK、DDK、daily 包和编译产物不入 Git，完整复现资产在 dog 归档。量化精度、温度锁定和 PR 新性能路径 A/B 不在已有验证范围内。

## Recipe v1 扩展入口

新增模型优先添加 `recipes/*.json`，设备与文件路径放在独立 environment 中。统一命令为 `python3 scripts/bench.py validate|resolve|run|summarize`。详见 [Recipe 使用说明](docs/RECIPE_V1.md)。当前支持 frozen model，daily 编排负责更新运行库和探针；基线批准和回退告警尚未实现。

## 迭代进展

顶部导航按「迭代进展 / 性能评测」分组。`/iteration.html` 展示分类特性清单及关键组合验证区域，`/iteration.html#models` 展示模型支持；Daily 总览和评测详情保留原入口。

维护者通过 `kanban/static/iteration-config.js` 修改版本归属、特性分类和模型部署配置，随仓库发布生效。同一模型的多种配置会合并为一行，芯片平台去重显示；悬停量化方式可查看对应芯片。v0.2 模型列表包含 v0.1 已有配置。

当前特性状态按已确认版本范围展示：v0.1 已完成、v0.2 开发中。PR/Bug、验收证据和关键组合仍是待录入区域，尚未接入自动同步；`combinations` 为预留配置，当前未实现其数据渲染。设计第一稿保存在 `design/llm-iteration-v1/`。

本地运行仍使用上述 Python 服务；静态发布运行 `node scripts/kanban/build_vercel.mjs`，会一并打包迭代页面及配置。图标来源见 `design/llm-iteration-v1/assets/SOURCE.md`。
