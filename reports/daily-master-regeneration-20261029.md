# Master daily 全链路模型生成验证（2026-10-29）

## 已部署

北京时间每天03:00，三个MSL任务使用当日最新master归档中的导出wheel、算子wheel和算子安装包重新生成模型，成功后再部署手机并连续推理10次。失败不回退旧模型。原始权重只读，模型/组件哈希、DDK包哈希、源码快照和日志按任务归档。

Dog runner镜像：`msl-kanban-runner:daily-export`，ID `sha256:3edd27d7496ce1b954b4c34a51fc50c11ef29529bc0a97494f918a6bf6553e9d`。runner 2.338.2 已重新连接GitHub并显示 Listening for Jobs。当前导出依赖 torch 2.13.0+cpu、transformers 4.57.1、onnxslim 0.1.96、gguf 0.17.1。DDK使用用户已有的原始6.1.1.0工具与平台zip，每任务隔离初始化。

每日包master提交 `e77e35f8f5bb46165231d5b44b7c41f1dc7c175d`，SHA256 `aec5349fc33de936165f89f5ba5246efbfd07a0a12f43d9d11c3d1d96e56fc57`。包未公开mslite_internal独立Git SHA；以随包实际算子及插件SHA256追溯，不宣称已核实独立仓库最新HEAD。

## 本次结果：均未生成新的有效性能结果

| 任务 | 归档任务后缀 | 结果 |
| --- | --- | --- |
| Qwen3-0.6B / 9030 | 1b81e3d238e9-1 | 原样master导出报 Mutable KV-cache operator is inference-only; detach inputs first |
| Qwen3-4B / 9030 | 6781c86181ef-1 | 同一Q/K/V导出边界错误 |
| Qwen2.5-0.5B / 9020 | 14d89db7bce9-1 | 导出和量化完成，DDK算子编译失败；头文件引用的tikcfw/impl/std/tuple/tuple_impl.h不存在，而原始zip中该文件位于api/impl/std/tuple/tuple_impl.h |

Qwen3两项执行代码a524264；Qwen2.5最终验证代码fd4bc8e（已补齐DDK官方install/env步骤）。此前解压器和镜像依赖问题属于执行环境问题，已修复并测试，不作为这三项失败根因。没有应用PR adapter、修改daily包或复用旧模型。Qwen2.5编译器在明确报错后仍等待队列，人工终止本次OMG子进程，仓库流程记录FAILED并退出验证容器；后续代码增加了确认缺失头文件错误后的自动终止和超时进程组清理。

## 复现与定位

- 执行仓库：`/home/zhugd/msl-kanban-ci/comparisons/daily-export-20261029`。
- 原始任务：`/home/zhugd/msl-kanban-ci/tasks/daily-20261029-<recipe-id>-<上表后缀>/`。
- 查看 `export.log`、`install-ddk.log`、`install-operators.log`、`daily-components.json`、`source-model-manifest.json`、`source.tar.gz`。
- 配置：仓库 `config/daily/*.json`，部署副本 `/home/zhugd/msl-kanban-runner-deploy/tasks/`。

需要上游修复Qwen3原样导出契约，以及提供头文件引用完整一致的DDK后，才能验证成功生成、部署及新模型的手机性能。当前已完成自动化切换和失败路径验证，尚未完成新模型成功链路验证。
