// One BinRunner invocation owns the model and generation state for one request.
#include <cstdio>
#include <cstdlib>
#include <string>
#include <type_traits>
#include <unistd.h>
#include "llm/llm.h"

struct Output {
  std::string text;
  MSLLMFinishReason reason = kMSLLM_RUNNING;
};

void append(const char *piece, MSLLMFinishReason reason, void *context) {
  auto *out = static_cast<Output *>(context);
  if (piece && *piece) {
    out->text += piece;
    std::fputs("MSL_PIECE ", stdout);
    for (const unsigned char *p = reinterpret_cast<const unsigned char *>(piece); *p; ++p) std::printf("%02x", *p);
    std::putchar('\n');
    std::fflush(stdout);
  }
  out->reason = reason;
}

// Release packages expose either the value or address form of this API.
template <class Handle>
void destroy(MSLLMStatus (*fn)(Handle), MSLLMModelHandle model) {
  if constexpr (std::is_same_v<Handle, MSLLMModelHandle>) fn(model);
  else fn(&model);
}

int main(int argc, char **argv) {
  if (argc != 4) return 2;
  alarm(85);
  std::string hex(argv[3]), prompt;
  if (hex.empty() || hex.size() % 2 || hex.find_first_not_of("0123456789abcdef") != std::string::npos) return 2;
  for (size_t i = 0; i < hex.size(); i += 2)
    prompt.push_back(static_cast<char>(std::strtoul(hex.substr(i, 2).c_str(), nullptr, 16)));
  auto model = MSLLMCreateModel();
  if (!model) return 3;
  MSLLMGenerationConfig config{};
  config.max_new_tokens = std::atoi(argv[2]);
  config.do_sample = true;
  config.temperature = 0.7f;
  config.top_k = 20;
  config.top_p = 0.8f;
  config.repetition_penalty = 1.0f;
  Output out;
  auto status = MSLLMBuildModel(model, argv[1]);
  if (status == kMSLLM_SUCCESS) status = MSLLMSetGenerationConfig(model, config);
  if (status == kMSLLM_SUCCESS) status = MSLLMStreamGenerate(model, prompt.c_str(), append, &out);
  destroy(MSLLMDestroyModel, model);
  if (status != kMSLLM_SUCCESS) return 4;
  bool length = out.reason == kMSLLM_FINISHED_BY_MAX_CONTEXT_LENGTH || out.reason == kMSLLM_FINISHED_BY_MAX_OUTPUT_LENGTH;
  if (!length && out.reason != kMSLLM_FINISHED_BY_EOS) return 5;
  std::printf("MSL_REPLY %s ", length ? "length" : "stop");
  for (unsigned char c : out.text) std::printf("%02x", c);
  std::puts("");
}
