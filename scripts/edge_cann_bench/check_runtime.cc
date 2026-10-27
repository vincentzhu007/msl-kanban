// Runtime preflight only; no model execution and no performance result.
#include <cstdio>
#include <dlfcn.h>

int main(int argc, char **argv) {
  if (argc != 2) {
    std::fprintf(stderr, "usage: check-cann-runtime LIBRARY_PATH\n");
    return 2;
  }
  void *library = dlopen(argv[1], RTLD_NOW | RTLD_LOCAL);
  if (!library) {
    std::fprintf(stderr, "CANN_RUNTIME_LOAD_FAILED: %s\n", dlerror());
    return 1;
  }
  const char *symbols[] = {
      "LLMEngine_Executor_CreateFromJson", "LLMEngine_Executor_LLM_Generate",
      "LLMEngine_Executor_Deinit", "LLMEngine_Executor_Destroy",
      "LLMEngine_Context_CreateFromContextJson", "LLMEngine_Context_Destroy",
      "LLMEngine_Context_GetInputTokenCount", "LLMEngine_Context_GetOutputTokenCount",
      "LLMEngine_Context_SetOnSomeTokenGenerateDoneFunc",
      "LLMEngine_Context_GetTotalTimeMs", "LLMEngine_Context_GetPrefillTimeMs",
      "LLMEngine_Prompt_Create", "LLMEngine_Prompt_Destroy", "LLMEngine_Prompt_SetText"};
  bool valid = true;
  for (const char *symbol : symbols) {
    dlerror();
    dlsym(library, symbol);
    const char *error = dlerror();
    if (error) {
      std::fprintf(stderr, "CANN_RUNTIME_SYMBOL_MISSING: %s: %s\n", symbol, error);
      valid = false;
    }
  }
  dlclose(library);
  if (valid) std::puts("CANN_RUNTIME_API_AVAILABLE (model compatibility not verified)");
  return valid ? 0 : 1;
}
