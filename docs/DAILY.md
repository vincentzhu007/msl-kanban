# v0.2 Daily 评测

首条链路：官方 master daily 发布件 → dog Runner 容器 → Qwen2.5-0.5B / Kirin9020 真机评测 → GitHub 结果提交 → Vercel 静态看板。

## 触发与配置

工作流 `.github/workflows/daily-qwen25-9020.yml` 支持手动输入 YYYYMMDD（留空按北京时间当天）和 force 重跑。仅允许 main 分支执行。定时为北京时间每天 09:17，必须设置仓库变量 `DAILY_ENABLED=true` 才执行；首次手动端到端验证完成后启用。GitHub schedule 可能延迟或漏发，v0.2 不承诺严格准点；可手动补跑指定日期。

Runner 使用 `infra/github-runner/compose.yaml` 加 `compose.daily.yaml` 启动。按 `config/daily-qwen25-9020.example.json` 配置设备、已归档模型和 BinRunner 路径，再把实际配置挂载为 `/config/daily.json`。构建新的探针，复用固定模型，不重新导出模型。模型及探针均需通过 host 和手机沙箱 SHA256 校验；手机需事先部署独立 sha256sum 工具。

```sh
python3 scripts/daily.py --config /config/daily.json --date 20261028
```

任务只调用仓库中的评测逻辑。生成的 recipe/environment 是锁定数据，不生成替代评测脚本。daily 包必须提供官方 `.sha256`；没有当天 master 构建时记录 NO_BUILD，不使用旧包顶替。下载/编译/设备/采样校验失败记录 FAILED。Archive 解包拒绝链接、特殊文件和路径越界。

## 归档与互斥

`/data` 挂载 dog 的持久化归档目录：

- `packages/<sha256>/`：已验证发布件缓存。
- `tasks/<run_id>/`：任务状态、构建信息、源码快照、编译日志、编译器身份、配置、原始错误及测量目录索引。
- `runs/<recipe-run-id>/`：现有 recipe 生成的锁、原始日志、内存采样、CSV 和看板结果。
- `completed/`：成功结果索引；发布件、recipe、评测代码 commit 和设备环境均相同才去重。force 可以显式复测。
- `leases/`：整个准备/部署/评测阶段共享的设备锁。其他人工任务也需遵守同一设备使用约定；不强制终止未知进程。

工作流串行使用 9020，不取消正在进行的评测。发现仍在运行的 recipe-msl 时拒绝覆盖探针。模型不会从发布件自动替换。异常退出后应检查残留 worker，再重跑。

## 发布和指标

通过校验的指标写入 `kanban/data`；成功、失败、无新构建、去重的任务记录写入 `kanban/jobs`。模型内部来源路径、真实设备序列号和详细错误不写入新公开结果。完整证据只保留在 dog；任务记录链接到私有 GitHub Actions 日志。

工作流将结果与任务状态提交回 GitHub。推送失败会使 Actions 失败，dog 归档仍在；重跑会复用已成功归档的结果。GitHub 数据提交成功与 Vercel 部署成功是两个独立状态，部署失败不能被解释成测量失败。

固定规格：上下文2048、输入1024、输出128，同进程5次、无预热；P90 最近秩法，5次对应最大值。采集总PSS与Graph峰值、推理期峰值及第2–5次Decode稳定中位数。看板增加任务记录与按设备比较指纹分组的历史趋势。

当前不自动批准基线或判定回退；温度、频率未锁定，系统版本与配置不符时拒绝运行。尚未接入多设备队列、weekly竞品、模型重导出、告警和漏跑补偿。
