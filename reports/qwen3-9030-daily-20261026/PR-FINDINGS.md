# 相关未合入 PR 核查

查询日期：2026-10-26。通过 GitCode API 枚举 mindspore/mindspore-lite 的45个 open PR，以及 mindspore/mslite_internal 的20个 open PR；读取候选文件差异。原始状态、SHA、差异与部分评论保存在 pr-check/。open 是 PR 状态，不证明分支全部改动均未以其他方式进入 master/daily。

## 最直接相关
- [mindspore-lite !1362](https://gitcode.com/mindspore/mindspore-lite/merge_requests/1362)，SHA a6cd83f6a6d4fc8afe426f153d63491fe4a7bb50：DFlash target_wrapper.py 中 MsTransRopeScatterNDUpdateFunctional 对输入 detach、克隆缓存，调用原始单输出算子，在导出时返回 Q/K/V，symbolic 使用 outputs=3，编译前 lower 为单输出。代码直接处理本次梯度及返回值契约问题；仅位于 DFlash 路径，普通 Qwen3 仍需适配，未验证它能消除 OMG 堆损坏。
- [mindspore-lite !1215](https://gitcode.com/mindspore/mindspore-lite/merge_requests/1215) + [mslite_internal !19](https://gitcode.com/mindspore/mslite_internal/merge_requests/19)：早期 Qwen3-4B 导出/算子配套。两侧都能看到三输出 RoPE/cache adapter，含 runtime、KV cache、S16S4/导出改动；TMP，不能直接当作当前 daily 的已验证修复。

## 其他相关
- [mslite_internal !58](https://gitcode.com/mindspore/mslite_internal/merge_requests/58)：PlanGemm 从反复对半 K 改为搜索 group 数的偶数约数，避免漏掉有效 tiling；不是 Q/K/V 返回值修复，也未看到修复 SaveWeightBufferToFile 崩溃的证据。
- [mslite_internal !59](https://gitcode.com/mindspore/mslite_internal/merge_requests/59)：WIP S16S4 Prefill 优化，涉及 Host tiling 和 L300/L31x kernel。
- [mslite_internal !62](https://gitcode.com/mindspore/mslite_internal/merge_requests/62)：Qwen3-4B packed decode layouts、紧凑 scale、输出形状融合。PR 明确说明本次 rebase 尚未进行编译/设备回归，18.8/18.9 tokens/s 来自上游基线，不是新路径收益。
- [mslite_internal !37](https://gitcode.com/mindspore/mslite_internal/merge_requests/37)：Group128 K 非512整除的尾块修复，主要用例 K=896/4864；Qwen3-4B 的2560/9728均可被512整除，优先级较低。
- [mindspore-lite !1345](https://gitcode.com/mindspore/mindspore-lite/merge_requests/1345)：运行时日志与 hilog，可帮助定位旧模型 Build status=2；不是已确认的加载修复。

## 结论
优先参考 !1362 的导出专用 functional adapter，保持设备算子 ABI 不变；然后独立诊断 OMG 保存外部权重时的 munmap_chunk(): invalid pointer。当前查询未发现明确覆盖该崩溃的已验证 PR，不能承诺套用候选即可跑通。此轮仅查询，没有合入或应用上述 PR。
