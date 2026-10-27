# 历史实验说明（非正式 2K 协议）

正式评测入口及 PR 验证请先阅读 [RUNBOOK](../../docs/RUNBOOK.md)。下面保留早期 1K、多进程预热实验说明，仅用于追溯。

# Kirin 9020 daily runtime benchmark

This probe uses the public C API and the unmodified static library from the
2026-10-26 MindSpore Lite LLM 0.2.0 daily archive. It does not re-export the
existing phone model. This is a runtime regression baseline, not a validation of
the daily compiler and operator package.

## Files

- `daily_bench.cc`: device-side metadata inspection and timing probe.
- `run_daily.py`: five independent processes, each with a warmup and measured
  generation for each input length; preserves logs and JSON results on dog.

## Existing environment

- Server: SSH alias `dog`, `/home/zhugd`.
- Phone: `127.0.0.1:2000`, Mate 70 Pro, Kirin 9020.
- Model: BinRunner `@/bin/st3_qwen25.msl`, W4A16, group 32, context 1024,
  prefill chunk 64. Full identity is in the result JSON.
- BinRunner: `/home/zhugd/code/ohos/BinRunner`.
- Test directory: `/home/zhugd/llm_validation/20261026-qwen25-05b-w4a16-9020`.
- Dedicated transfer: host TCP 18888 to target phone TCP 8888. BinRunner's
  default 8888 mapping was associated with another phone; check `hdc fport ls`.

## Build on dog

Run inside the test directory after extracting the specified archive:

```sh
/home/zhugd/tool/hmos-ndk/command-line-tools/sdk/default/openharmony/native/llvm/bin/clang++ \
  --target=aarch64-linux-ohos \
  --sysroot=/home/zhugd/tool/hmos-ndk/command-line-tools/sdk/default/openharmony/native/sysroot \
  -std=c++17 -O2 -static-libstdc++ \
  -I mindspore-lite-llm-linux-x64-0.2.0/include daily_bench.cc \
  -Wl,--whole-archive mindspore-lite-llm-linux-x64-0.2.0/lib/libmindspore-lite-llm.a \
  -Wl,--no-whole-archive -ldl -pthread -o daily-bench
```

`--whole-archive` is necessary to preserve the NPU backend's static registration,
as in the project's own example build. Plain static linking produces an empty
backend registry and a model-load error.

Push `daily-bench` as `daily-20261026-bench` using the existing BinRunner CLI,
then run `python3 run_daily.py` on dog. The deployed BinRunner has a 30-second
device execution limit, so each process performs four generations. The host
`--timeout` only controls how long the CLI waits for logs.

## Measurement boundaries

The prompt is the raw string ` hello` repeated 64 or 512 times. The existing HF
tokenizer confirms 64 and 512 input tokens; the public runtime API does not
expose an input-token count. No chat template is added. Generation is greedy,
with a 128-token limit. The runner requires all 128 callbacks and the
max-output-length finish reason before accepting a sample.

TTFT runs from entry into `MSLLMStreamGenerate` to its first token callback;
model loading is reported separately. Decode throughput counts the following
127 callbacks. No token text is printed during measurement.

Memory reports process VmRSS and `getrusage(RUSAGE_SELF).ru_maxrss`, including
the memory inherited from the BinRunner parent. It does not measure complete
NPU/service/device memory. Hardware temperature and frequency are not locked.
This is a synthetic latency benchmark, not a model-quality evaluation.

Only deployment metadata is returned from the device. The model remains on the
phone; its SHA-256 was computed there with the system utility.
