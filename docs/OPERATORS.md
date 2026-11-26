# 算子性能看板

从顶部「算子性能」进入 `/operators.html`。页面沿用 MSL Kanban 的布局，筛选顺序为算子、平台、场景、规格。初始数据包含 S8S8 在 Kirin 9030 上的 BooguImage 和 ViT 记录。Kirin 9050 已有 ViT 和 BooguImage 的五个典型投影规格实测，以及对应形状的 CAModel 流水。UT 规格保留在原始评测归档中。

## 本地运行

在 msl-kanban 仓库根目录执行。

```sh
python3 kanban/server.py --host 127.0.0.1 --port 18765
```

打开 [本地算子性能页](http://127.0.0.1:18765/operators.html)。点选折线中的时间点，再点击「打开 Perfetto」在看板内查看流水，或点击「在新标签页打开」将当前流水载入独立的 Perfetto 标签页。内嵌窗口可以从底部拉伸，也可聚焦分隔条后用上下方向键调整。包含指令事件的流水按 BUSY、pop、retire 排列。流水随当前实机规格和运行记录切换，完整仿真和起始窗口在详情中标明。

`node scripts/kanban/build_vercel.mjs` 将页面、数据和流水打包到 `build/vercel-kanban/`，也是 Vercel 的构建命令。查看器由浏览器从 [ui.perfetto.dev](https://ui.perfetto.dev/) 加载。看板读取并解压所选流水，再在浏览器内传给查看器。首次从公网地址打开时，若出现信任提示，可选择「Yes」查看当次流水，或选择「Always trust」记住看板来源。

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
| `date`, `commit` | 看板日期（YYYY-MM-DD）、被测算子源码的完整 Git 提交号。看板日期通常是实测日期，也可按版本发布日期归档，此时用 `measured_date` 保留实测日期。开发快照填写 `source_sha256`，可记录 `base_commit` |
| `device`, `system`, `mode`, `protocol` | 设备别名、系统、运行模式、采样协议名称。可选 `environment` 记录 DDK、运行库及其他影响比较的设置 |
| `statistic` | `hot-samples-median` 为全部热样本取中位数，`round-medians-median` 为各轮中位数再取中位数 |
| `cases[]` | 每个规格含 `id`、`group`、`label`、`spec` 和 `runs`。同一算子使用稳定的规格 ID |
| `spec` | 可填写 `dimensions`（如 `{"M":1024,"K":768,"N":768}`）、`inputs`（对象列表，每项含 `name`、`shape`、`dtype`、`layout`）、`attrs`（对象）。按算子实际接口填写 |
| `runs[]` | 每轮记录 `round`、`warmup` 和 `hot`。热样本按 `[采样时间, NPU微秒, RunSync微秒]` 保存。缺失指标填 null |
| `accuracy` | 规格级可选字段。可填 `summary`、误差指标及输出与参考哈希 |
| `trace` | 规格级可选附件。包含仿真 `platform`、`date`、`cycles`、`scope`（full 或 prefix）、`source`、`file`，可补充 `lanes`、`lifecycle.file` 和 `instructions.file`。导入前附件路径相对于结果 JSON 所在目录 |
| `simulations[]` | 旧运行记录可保留独立仿真附件。每项含 `id`、`label`、`spec` 和 `trace`。页面从当前实机规格的 `cases[].trace` 读取流水 |

导入器检查格式、运行 ID、样本和附件，按 SHA-256 保存流水。同名结果内容冲突时更换运行 ID。发布目录属于看板数据，避免放入真实设备序列号、凭据和采集机内部路径。

趋势按所选算子、平台、场景和规格展示，同一设备、同一规格的数据连成趋势线。运行模式和采样协议可在详情查看。S8S8 历史档案里两种设备名称指向同一台 Kirin 9030，导入时统一为 Mate 80 Pro · SGT-AL00。按日期取当日最后导入的有效实测，按版本取该版本最新的实测，按运行展开热样本。S8S8 历史记录沿用各归档的汇总方法。实机 NPU 时间、RunSync 墙钟时间及 CAModel 周期分别使用独立指标。
