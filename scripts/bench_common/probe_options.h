#pragma once
#include <cerrno>
#include <climits>
#include <cstdio>
#include <cstdlib>

struct ProbeOptions {
  int repetitions = 0, context = 0, input = 0, output = 0;
  int threads = 4, batch = 64;

  static bool positive(const char *text, int upper, int &value) {
    char *end = nullptr;
    errno = 0;
    const long parsed = std::strtol(text, &end, 10);
    if (errno || end == text || *end || parsed < 1 || parsed > upper) return false;
    value = static_cast<int>(parsed);
    return true;
  }

  bool parse(int argc, char **argv, bool llama = false) {
    if (argc != (llama ? 9 : 7)) return false;
    if (!positive(argv[2], 100, repetitions) || repetitions < 2 ||
        !positive(argv[4], 131072, context) ||
        !positive(argv[5], 131071, input) ||
        !positive(argv[6], 131071, output) || output < 2 || input + output > context)
      return false;
    return !llama || (positive(argv[7], 32, threads) && positive(argv[8], 4096, batch));
  }

  void report(bool llama = false) const {
    std::printf("SPEC {\"protocol_version\":1,\"context_tokens\":%d,\"input_tokens\":%d,"
                "\"output_tokens\":%d,\"repetitions\":%d,\"threads\":%d,\"batch\":%d,"
                "\"input_tokens_source\":\"%s\"}\n", context, input, output, repetitions,
                threads, batch, llama ? "runtime-tokenizer" : "recipe-verification-evidence");
  }
};
