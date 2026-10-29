# 对照 ms-pipeline 定位 Qwen2.5-0.5B 导出失败

## 门禁代码依据

读取 `https://gitcode.com/mindspore/ms-pipeline`，HEAD `8803de62b2298b13a6c5bb162131cfe1aae38f9b`。

- `pipeline/mindspore/mindspore-lite/scripts/smoke.sh:270-319`：调用 install-ddk.sh，安装发布件中的导出与算子 wheel、算子 .run，配置环境，调用 run_llm_st.sh。调用没有传 `--msl`，因此按该脚本会执行导出，不复用成品模型。未获取 Jenkins 实际运行日志，不宣称某次门禁执行成功。
- `pipeline/mindspore/mindspore-lite/scripts/install-ddk.sh:42-50`：备份 DDK 压缩包中的实体 `tikcfw/lib`，恢复 `tikcfw/lib -> ../api/lib` 软链接。文件头注释明确说明这是修复 DDK 6.1.x 打包造成的相对 include 失效。
- `docker/dockerfile/ci/compile/ubuntu_2204_x86/Dockerfile:220-246`：同样修复软链接，注释点名 `../../impl/std/tuple/tuple_impl.h` 缺失错误。

## 与看板 daily 的差异

| 项目 | ms-pipeline ST | 此前 kanban daily |
|---|---|---|
| DDK 头文件目录 | 恢复 tikcfw/lib -> ../api/lib | 原样解压实体目录，遗漏恢复步骤 |
| OMG ELF 加载器 | 改为 DDK 自带 loader，避免 /tmp 权限冲突 | 原厂安装/环境脚本，仍可能出现 /tmp 链接告警 |
| C++ 头文件 | GCC 9.5.0 include 显式设置 | 容器默认环境 |
| 动态库 | source 之后补 platform/lib64，LD_PRELOAD 指向 DDK libstdc++ | source 会覆盖事先传入的 LD_LIBRARY_PATH |
| Python 算子路径 | 增加 platform/kirin9020/ops/impl | 独立 daily wheel + DDK Python 路径 |
| TeFusion | TE_PARALLEL_COMPILER=1 | 未显式设置 |
| 原始模型 | 已量化 Qwen2.5-0.5B-Instruct Q4_0 GGUF | HF Qwen2.5-0.5B-Instruct，导出时 q4_0 |
| 上下文 / chunk | 1024 / 64 | 2048 / 64 |

上述环境差异不是全部已证实的根因。先只恢复头文件软链接，其他变量保持原样，以验证当前明确的编译报错。

## 单变量实验

固定原失败任务的 2026-10-29 01:00 发布件，而非后来更新的同日 16:00 包：

- master：`e77e35f8f5bb46165231d5b44b7c41f1dc7c175d`
- 发布件 SHA256：`aec5349fc33de936165f89f5ba5246efbfd07a0a12f43d9d11c3d1d96e56fc57`
- DDK 6.1.1.0 原始工具和 Kirin9020 plugin zip 不变。
- HF 原始权重、q4_0、2048 上下文、chunk 64、Python 依赖和 runner 镜像不变。
- 仅在任务私有 DDK 目录恢复头文件软链接，保留原实体目录作为备份。
- 不修改 daily 导出 wheel、算子 wheel 或算子安装包；不使用 PR、不自行编译替代组件。
- 目录：dog `/home/zhugd/msl-kanban-ci/comparisons/ddk-st-alignment-20261029/20261029-pinned/`。
- 初次自动发现了同日新增 16:00 包，已取消该次实验；它不作为单变量对照证据。

回归测试覆盖缺失相对 include 的目录结构、恢复后的实际目标、原目录备份和重复调用。Python 测试 39 项通过。

## 实验结果：导出成功

原失败任务与本次的发布件组件、DDK zip 和原始模型 manifest 均完全一致。仅恢复软链接后，导出退出成功、OMG 报告离线模型生成成功，最终 `.msl` 魔数检查及 recipe 校验通过。

- 模型 SHA256：`c09e6262b4eb335d984227500076ad0fad75afc77088e274d391f3f23ec7347b`
- 文件大小：295225856 bytes
- 新模型尚未进行手机推理或性能测量，不替换已有正式性能记录。

这证实当前 tuple_impl.h 失败的直接原因是看板 DDK 初始化遗漏门禁的软链接恢复步骤；不是该 daily 导出工具在当前 HF/2K 配置下必然失败。其余环境差异仍可能影响后续设备推理，不能由导出成功推断整条 ST 或性能评测成功。
