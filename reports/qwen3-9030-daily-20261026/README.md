# Qwen3-4B S16S4 / Kirin 9030 daily 验证（2026-10-26）

状态：未跑通，无有效时延或内存成绩。

目标：context 2048，raw input 1024 tokens (` hello`重复1024次)，max output128，连续5次，P90 nearest-rank；hidumper采集总PSS和Graph峰值、稳定中位数。
设备：dog连接的5JV0226127000651，SGT-AL00 / Kirin9030。
Daily：master_20261026010016_5501731a356ffb4ec017a4dc37c3f5631be79489_newest。
HF源模型：/home/zhugd/code/llm/model/Qwen3-4B。

## 已确认阻塞
1. 旧qwen3-4b-s16s4-9030-2048-unfused.msl在daily静态运行库上Build返回2（MODEL_LOAD），未进入推理。原因尚未进一步确定。
2. 原始daily导出器先报inference-only梯度错误；禁用梯度后，Qwen3 wrapper要求Q/K/V三个输出，而配套MsTransRopeScatterNDUpdate仅返回Q，报expected3 got1。
3. 隔离环境仅适配导出时Python reference三输出接口，后续daily lower_inplace_cache仍生成原始单输出设备算子。小张量校验Q/K/V与daily原始reference完全一致。该路径属于修改后的导出器，不是原始daily直接通过。
4. 适配后完成ONNX、S16S4量化和图契约校验。补齐DDK PYTHONPATH后，OMG在SaveWeightBufferToFile/OpenFile阶段报munmap_chunk(): invalid pointer，exit134。该堆损坏的根因未确认，不能归因于某一具体算子。

## 复现
容器：edge-qwen3-daily-20261026；镜像qwen3-4b-s16s4-perf-env:pr37。
中间产物（保留）：/home/zhugd/llm_validation/20261026-qwen3-4b-s16s4-9030/.msl_export_cgetg_ne。
编译重试：容器内source /opt/ddk/tools/tools_ascendc/set_ascendc_env.sh；将/out/daily-python前置到原PYTHONPATH，保留DDK的package/python；LD_LIBRARY_PATH追加kirin9030/lib64及customize/op_impl/ai_core/tbe/op_tiling；运行python3 /out/resume_compile.py。
Daily运行库和设备算子未修改。未更新看板成绩。
