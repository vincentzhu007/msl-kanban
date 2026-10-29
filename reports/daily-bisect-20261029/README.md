# Qwen2.5-0.5B：历史 daily 包回溯（2026-10-29）

## 结论

未找到可用于二分的成功边界，不能认定具体哪一天引入回退。在固定鸿蒙 DDK 6.1.1.0、Qwen2.5-0.5B-Instruct、Kirin9020、q4_0、上下文 2048、chunk 64 条件下，最早已实测复现相同错误的包为 **2026-09-29 / dc2bda546163**。这不是“首次引入日期”。

9 月 29 日、10 月 4 日、10 月 20 日、10 月 28 日，均完成前面的导出过程并在 DDK 算子编译中报同一个 tuple_impl.h 缺失。10 月 29 日原始失败记录见 ../daily-master-regeneration-20261029.md。此前成功的手机性能任务使用固定模型，不是模型导出成功基线。

## 实验结果

| Daily 日期 | master 提交 | 包版本 | 结果 |
|---|---|---|---|
| 2026-10-29 | e77e35f8f5bb | 0.2.0 | 原始失败记录：相同头文件缺失 |
| 2026-10-28 | f6cd160f2ce8 | 0.2.0 | 本次复现相同头文件缺失 |
| 2026-10-20 | e9edd6f1ae77 | 0.2.0 | 本次复现相同头文件缺失 |
| 2026-10-04 | 7ab4deba56d7 | 0.1.0 | 本次复现相同头文件缺失 |
| 2026-09-29 | dc2bda546163 | 0.1.0 | 本次复现相同头文件缺失 |
| 2026-09-24 | 04ea35a3a42e | 0.1.0 | 旧包布局，只有导出 wheel；不具备当前全链路所需的随包算子，不判成功/同类失败 |
| 2026-09-14 | 9ca4cb05ee42 | 0.1.0 | 同上 |

额外流式检查了 9 月 25～28 日：包包含导出 wheel 和 `custom_opp_ubuntu_x86_64.run`，未提供当前验证入口要求的独立 `mslite_llm_ops` wheel。未对这些版本执行完整导出，不能将其视为成功或同类失败，也不能由包装结构变化推导缺陷引入日期。9 月 2～13 日的最新 master 归档未找到同名 LLM 发布件。

## DDK 原始包证据

原始 `DDK-tools-next-6.1.1.0.zip` 同时包含：

- `tools/tools_ascendc/include/tikcpp/tikcfw/lib/std/tuple.h`
- `tools/tools_ascendc/include/tikcpp/api/lib/std/tuple.h`
- `tools/tools_ascendc/include/tikcpp/api/impl/std/tuple/tuple_impl.h`

`tikcfw/lib/std/tuple.h` 第 18 行引用 `../../impl/std/tuple/tuple_impl.h`，按其位置解析为 `tikcfw/impl/std/tuple/tuple_impl.h`，该文件不在原始压缩包中。实际编译报错正是上述 tikcfw 路径；api 下虽有实现，未被该相对引用命中。

这是跨版本共用 DDK 路径不一致的直接证据；尚未通过修正路径的对照实验验证其是否为唯一问题，也没有证明历史包在其他 DDK 或官方完整开发环境下失败。当前不应归因于 10 月 29 日 daily 新引入。

## 复现与归档

- 固定 runner 镜像：`msl-kanban-runner:daily-export`。
- 执行代码快照：`d0d4395`，dog `/home/zhugd/msl-kanban-ci/comparisons/daily-bisect-20261029/repo`。
- 原始实验目录：`/home/zhugd/msl-kanban-ci/comparisons/daily-bisect-20261029/<YYYYMMDD>/`。
- 每项保存 `result.json`、`daily-components.json`、`ddk-packages.json`、`source-model-manifest.json`、各安装日志、`export.log`（未进入导出阶段的项没有该日志）。
- 本地 `evidence.json` 保存发布 URL、包/组件/DDK/模型哈希、首个编译错误及完整日志 SHA256。
- 诊断入口 `export.py` 仅选择历史包并调用仓库既有 `discover/download/safe_extract/export_model`；0.1.0 包采用原有名称，未修改上游导出工具或算子。
- 缺失头文件触发仓库现有进程组清理；诊断容器自动删除。
- 未部署手机、未发布历史实验为正式性能成绩、未修改生产 daily 配置、未拉取或编译 PR。

## 下一步判据

若继续追求“首次引入日期”，必须先取得一个在同一 DDK 下可成功的历史完整导出配置，或适配旧官方导出入口并确认成功；不能把缺少组件、入口不兼容当作成功端点。当前更直接的定位方向是核对 DDK 官方安装与 include 布局，单变量验证其影响。
