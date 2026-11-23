# 算子性能看板

从顶部「算子性能」进入 `/operators.html`。页面沿用 MSL Kanban 的布局，筛选顺序为算子、平台、场景、规格。初始数据包含 S8S8 在 Kirin 9030 上的 BooguImage 和 ViT 记录。Kirin 9050 已有 ViT、BooguImage Patch 和 Q 的首批实测，以及同版本的独立仿真流水。UT 规格保留在原始评测归档中。

## 本地运行

在 msl-kanban 仓库根目录执行。

```sh
# 安装并校验固定版本的 Perfetto UI
node scripts/kanban/install_perfetto.mjs

python3 kanban/server.py --host 127.0.0.1 --port 18765
```

打开 [本地算子性能页](http://127.0.0.1:18765/operators.html)。点选折线中的时间点，再点击「打开 Perfetto」下载并查看对应的流水。窗口从底部拉伸，也可聚焦分隔条后用上下方向键调整。包含指令事件的流水按 BUSY、pop、retire 排列。同版本的独立仿真可以从「仿真规格」切换，实机运行详情仍显示该实机规格的耗时。

`node scripts/kanban/build_vercel.mjs --prepare-perfetto` 将页面、数据和固定版本的 Perfetto UI 打包到 `build/vercel-kanban/`，也是 Vercel 的构建命令。构建按 SHA-256 校验入口、资源清单、查看器文件和许可证。已经本地安装时可直接运行 `node scripts/kanban/build_vercel.mjs`，复用现有文件。Python 服务和 Vercel 按路径设置算子页和查看器所需的响应头。

## 新增测试结果

实机采集继续使用算子仓已有的测试工具。编译产物、原始日志和 VCD 可留在评测机器的归档目录。将需要发布的结果转换成版本 1 的 JSON，流水可附带 Chrome Trace JSON 或 gzip 压缩的 JSON。新的算子和平台 ID 由导入器加入 catalog，页面据此生成选项。

```sh
# 首次迁移旧 S8S8 档案，重复执行时同一结果只保留一份
python3 scripts/operator_bench.py migrate-s8s8 ../op-performance-board

# 导入一条或多条准备好的记录
python3 scripts/operator_bench.py import /path/to/run.json
```

将 `kanban/operator-data/` 中新增的内容和更新后的 catalog 一起提交即持久更新。Python 服务从目录读取数据，页面可见时每 15 分钟检查更新，也可以手动刷新。Vercel 随 main 的数据提交重新构建。持续采集可由后续单独的算子任务调用相同导入命令，并与模型 Daily 共用设备租约。

## 记录格式

| 字段 | 内容 |
|---|---|
| `schema_version`, `id` | 格式版本 1。同一算子和平台内使用唯一运行 ID。ID 一旦发布保持不变 |
| `operator`, `platform` | 算子注册名和芯片 ID。如 `MsMatmulS8S8`、`kirin9030` |
| `date`, `commit` | 实测日期（YYYY-MM-DD）、被测算子源码的完整 Git 提交号。开发快照填写 `source_sha256`，可记录 `base_commit` |
| `device`, `system`, `mode`, `protocol` | 设备别名、系统、运行模式、采样协议名称。可选 `environment` 记录 DDK、运行库及其他影响比较的设置 |
| `statistic` | `hot-samples-median` 为全部热样本取中位数，`round-medians-median` 为各轮中位数再取中位数 |
| `cases[]` | 每个规格含 `id`、`group`、`label`、`spec` 和 `runs`。同一算子使用稳定的规格 ID |
| `spec` | 可填写 `dimensions`（如 `{"M":1024,"K":768,"N":768}`）、`inputs`（对象列表，每项含 `name`、`shape`、`dtype`、`layout`）、`attrs`（对象）。按算子实际接口填写 |
| `runs[]` | 每轮记录 `round`、`warmup` 和 `hot`。热样本按 `[采样时间, NPU微秒, RunSync微秒]` 保存。缺失指标填 null |
| `accuracy` | 规格级可选字段。可填 `summary`、误差指标及输出与参考哈希 |
| `trace` | 规格级可选附件。包含仿真 `platform`、`date`、`cycles`、`scope`（full 或 prefix）、`source`、`file`，可补充 `lanes`、`lifecycle.file` 和 `instructions.file`。导入前附件路径相对于结果 JSON 所在目录 |
| `simulations[]` | 运行记录可附同版本的独立仿真。每项含 `id`、`label`、`spec` 和 `trace`，按自身规格供 CAModel 查看，不参与实机趋势 |

导入器检查格式、运行 ID、样本和附件，按 SHA-256 保存流水。同名结果内容冲突时更换运行 ID。发布目录属于看板数据，避免放入真实设备序列号、凭据和采集机内部路径。

趋势按所选算子、平台、场景和规格展示。S8S8 历史档案里两种设备名称指向同一台 Kirin 9030，导入时统一为 Mate 80 Pro · SGT-AL00。按日期取当日最后导入的有效实测，按版本取该版本最新的实测，按运行展开热样本。S8S8 历史记录沿用各归档的汇总方法。实机 NPU 时间、RunSync 墙钟时间及 CAModel 周期分别使用独立指标。
