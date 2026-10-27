# Qwen2.5-0.5B / Kirin9020 daily Recipe v1 E2E

结论：未通过，阻塞在设备模型 SHA256 校验，尚未进入推理。本次没有新的性能数据。

## 执行约束

使用仓库现有 `scripts/bench.py validate`、`resolve`、`run` 以及 `bench_recipe.cc`。未修改或生成脚本。只填写 environment.json，编译现有源码、部署二进制，并使用既有工具读取诊断信息。远端源码与本地源码逐文件 SHA256 全部一致，见 SOURCE_SHA256SUMS 与 source-content-verify.log。

## 环境与产物

- dog 目录：`/home/zhugd/llm_validation/msllm-dev-ci-9020-e2e-v1`
- 设备：`127.0.0.1:2000` / PLR-AL00 / Kirin9020 / OpenHarmony-6.1.1.120。
- daily commit：`5501731a356ffb4ec017a4dc37c3f5631be79489`。
- 模型：Qwen2.5-0.5B-Instruct W4A16，context2048/input1024/output128，连续5次。
- 源码快照 SHA256：`1b44822250fa369169f797e3a4a18f279ea9d8f14d05c8e4de87b7b56280be94`。
- 模型/daily 包/probe SHA256 见 artifact-sha256.txt；探针从归档 daily 包完整编译链接。

## 阶段结果

1. `validate` 成功。
2. `resolve` 成功，主机文件校验通过，生成 resolved-recipe.json。
3. `run` 失败：`model: could not verify app sandbox SHA256; deployment must match host artifacts`。
4. 原样重放仓库的校验命令，发现 app 未部署 sha256sum，返回 `not readable: .../bin/sha256sum`。
5. 将设备已有 `/system/bin/toybox` 原样取回并以 sha256sum 名称部署到 app（没有生成新程序/脚本）。该二进制 SHA256 为 `d8badd88a726d5cc7f1f7d6c8b07485104941054647c45c0a459ce4c01f04d89`。
6. 再次校验返回 `toybox: Unknown command @13`，说明当前系统工具与启动方式不兼容。
7. 使用同一锁定清单重跑原仓库入口仍失败。没有跳过校验、调用探针绕行或发布看板成绩。

此失败不能推断模型 SHA 不匹配，实际是未能执行设备 SHA 校验。应在后续允许修改代码或提供兼容校验二进制后修复依赖，再重新执行全流程。source-verify.log 的 Uid/Gid 差异来自跨机器文件属主；实际内容一致性以 source-content-verify.log 为准。
