# Qwen3-4B / Kirin9030 PR 组合验证

## 结果
通过：使用 20261026 daily 运行库，复用 mindspore-lite !1362 的导出专用 functional adapter，并使用从 mslite_internal !62 固定提交构建的算子包。未合入上游仓库。

- Runtime: `5501731a356ffb4ec017a4dc37c3f5631be79489`，保持原始 daily 静态库。
- !1362: `a6cd83f6a6d4fc8afe426f153d63491fe4a7bb50`，仅复用 MsTransRopeScatterNDUpdateFunctional 到普通 Qwen3OpSet，不启用 DFlash。
- !62: `abaea09acf6a4cb1e0cf8b6af4ef84f415925941`，构建 MsMatmulS16S4、MsAttention、MsRmsNorm、MsAddRmsNorm、MsTransRopeScatterNDUpdate、MsFloatCastInt。
- 使用默认 `decode_layout=0`，未开启新增布局 1/2/3、output_head_dim、output_bsh；不是新布局提速验证。
- 模型 SHA256: `60056f613c4d5ff5721d92f46486f01fd0b4bf573aefd41e40954f642111ea17`。

## 测试协议
SGT-AL00 / Kirin9030，设备 5JV0226127000651；context2048，raw synthetic prompt 为 ` hello` 重复1024次（已核对为1024 token），greedy生成128 token。相同进程连续5次，无间隔，无进程内预热；P90采用nearest-rank，5个样本时为最大值。此前有烟测及一轮5次测量，因日志拉取超时导致内存采样提前结束，保留全部首轮结果，补测本轮。温度与频率未锁定，同步内存采样开销未扣除。

## 指标
| 指标 | 结果 |
|---|---:|
| 总时延 P90 | 10.536 s |
| 首token P90 | 3.445 s |
| Decode 中位速度 | 18.537 token/s |
| 总PSS采样峰值 | 2605.809 MiB |
| 总PSS稳定中位数 | 2604.691 MiB |
| Graph/NPU峰值及稳定中位数 | 2471.328 MiB |
| 模型ROM | 2179.530 MiB |

5/5 status=0、finish_reason=3、output_callbacks=128。50份 hidumper 样本，20份稳定样本（完整落在第2–5次Decode内），采样间隔中位数约1.138秒。总PSS包含Graph，二者不相加；离散采样可能漏掉短峰。

## 验证与故障定位
1. 原始 daily reference 梯度错误复现；!1362 adapter 在真实普通 Qwen3OpSet 调用边界通过，Q/K/V与原参考计算一致，输入cache不变。
2. !1362完整模型导出和S16S4量化通过。相同量化图配daily算子仍出现编译退出134；配!62分支在同版本DDK内重新构建的算子包则编译、打包正常退出，并通过真机推理。
3. gdb定位daily编译器异常实际发生在进程退出时：`libcustom_op.so` 内 `optiling::TilingDataStructBase::~TilingDataStructBase()` → `std::_Rb_tree::_M_erase` → free → SIGABRT。不是先前按日志末行推断的权重写入函数内崩溃。具体堆损坏起点尚未确定。
4. gdb保留的旧适配图产物可以加载，但首个prefill返回失败；该诊断模型未计为成功成绩。
5. !58 Host分块对照：K=12800基线失败、PR通过；普通Qwen3的K=2560/9728两侧均通过且分块相同。因此没有叠加!58。!59及!62新增性能路径未进行本轮设备A/B；旧!1215/!19没有混入当前链路。
6. 成功结果只能归于本次完整PR分支构建组合，尚未拆分!62新增改动、其基线提交以及重新构建的各自影响。未验证语义质量或量化精度，验证范围为导出、编译、加载、固定token生成和性能/内存采集。

## 归档与看板
Dog归档：`/home/zhugd/llm_archive/20261026-qwen3-4b-s16s4-kirin9030-pr1362-pr62`，包括模型、源码快照、算子包、导出适配、固定版本、测量原始数据和SHA256清单。
看板新增 `Qwen3-4B / MSL-LLM NPU · PR验证 / Kirin9030`，原有成绩保持不变。
