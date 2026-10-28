# CANN Kit LLM 接入预检

状态：未接入性能评测；只有运行时预检工具。不要把本目录当作已通过的 benchmark backend。

`check_runtime.cc` 在目标应用进程中使用 RTLD_NOW 加载指定动态库，检查大模型推理和计时所需的公开 C API。退出 0 只证明加载和符号可见，不代表模型可运行、参数正确或测量协议合格；退出 1 为加载/符号失败，退出 2 为参数错误。

## dog 编译及设备预检

```sh
NATIVE=/home/zhugd/tool/hmos-ndk/command-line-tools/sdk/default/openharmony/native
"$NATIVE/llvm/bin/clang++" --target=aarch64-linux-ohos --sysroot="$NATIVE/sysroot" \
  -std=c++17 -O2 -static-libstdc++ scripts/edge_cann_bench/check_runtime.cc \
  -ldl -o /tmp/check-cann-runtime
cd /home/zhugd/code/ohos/BinRunner
python3 -m binrunner -t 127.0.0.1:2000 -p 18888 push /tmp/check-cann-runtime
# LIBRARY 为待验证、允许在应用内加载的鸿蒙原生 CANN LLM 库。
python3 -m binrunner -t 127.0.0.1:2000 -p 18888 push "$LIBRARY"
python3 -m binrunner -t 127.0.0.1:2000 -p 18888 run "check-cann-runtime @/bin/libhiai_llm_engine.so" --timeout 30
```

若目录加载被系统拒绝，应按 SDK 官方应用集成方式打包部署。不能把权限失败直接解释为模型不支持，也不应尝试关闭设备安全策略。

## 正式对比准入条件

- 鸿蒙原生 LLM SDK 的接口、应用打包要求和模型转换工具已确认。
- 原始 Qwen2.5-0.5B-Instruct 权重和 tokenizer 与已有对比一致；记录量化算法、分组、混合精度和全部资源文件 SHA256/字节数。
- 确认上下文 2048，原始 ` hello` 重复 1024 的 tokenizer 实际输入计数为 1024；greedy 输出实际达到 128，不注入聊天模板。
- 同进程连续 5 次，无预热；每次重置会话/KV 并关闭历史 prompt cache；记录实际输入/输出计数和完成状态。
- 外部单调时钟记录调用到首 token 的 TTFT、首 token 到末 token 的 decode 和 E2E。SDK prefill 时间单列，不等同 TTFT；回调可能包含多个 token，必须核对实际 token 数。
- 复用仓库 hidumper 采样和统计口径：P90 最近秩，推理 2–5 的 decode 完整采样区间计算 Total PSS 稳定中位值，另报峰值及 Graph；不重复累加 Graph。
- 在 recipe/planner/execution/results 中实现经过验证的 CANN backend 后，才运行并写入 kanban 数据。当前 validator 仍只接受 MSL/llama，防止预检记录混入性能结果。

详细证据见 `docs/CANN_KIT_LLM.md`。
