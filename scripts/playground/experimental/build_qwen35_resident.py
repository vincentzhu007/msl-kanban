"""Build using the already verified S2 backend archive produced by build_qwen35_stats.py."""
from pathlib import Path
import re, shlex, subprocess
root = Path('/agents/hf-agent-qwen35-moe-s4/mindspore-lite/mindspore-lite/lite_llm')
b = root / 'build'
out = Path('/tmp/kanban-q35-stats')
def remap(s): return s.replace('/repos/hf-agent-qwen35-moe-s4', '/agents/hf-agent-qwen35-moe-s4')
link = shlex.split(remap((b/'examples/CMakeFiles/qwen35-phone-chat.dir/link.txt').read_text()))
compiler = link[0]
native = Path(compiler).parents[2]
def compile(source, dest, flagfile, extra=()):
    flags = remap(flagfile.read_text())
    args = [compiler, '--target=aarch64-linux-ohos', '--sysroot='+str(native/'sysroot')]
    for key in ('CXX_DEFINES', 'CXX_INCLUDES', 'CXX_FLAGS'):
        args += shlex.split(re.search('^'+key+r' = (.*)$', flags, re.M)[1])
    subprocess.run(args+list(extra)+['-c', str(source), '-o', str(dest)], check=True)
llm = (root/'src/pipeline/llm.cc').read_text()
assert llm.count('*input_ids = e->tokenizer->Encode(prompt);') == 1
llm = '#include <atomic>\nstatic std::atomic<size_t> kanban_input_tokens{0};\nextern "C" size_t MSLLMKanbanInputTokens() { return kanban_input_tokens.load(); }\n' + llm.replace('*input_ids = e->tokenizer->Encode(prompt);', '*input_ids = e->tokenizer->Encode(prompt);\n  kanban_input_tokens.store(input_ids->size());')
llm = llm.replace('#include "../llm_types_internal.h"', '#include "llm_types_internal.h"')
llm += '\nextern "C" void MSLLMKanbanPresencePenalty(MSLLMModelHandle model, float penalty) {\n  auto *engine = reinterpret_cast<InternalEngine *>(model);\n  engine->sampler->SetPresencePenalty(penalty);\n}\n'
(out/'llm-resident.cc').write_text(llm)
compile(out/'llm-resident.cc', out/'llm.cc.o', b/'src/CMakeFiles/mslite_llm_static.dir/flags.make')
sampler = (root/'src/sampler/sampler.cc').read_text()
old = '} else if (strategy_ == MSLLM_SAMPLER_TOP_P && top_p_ > 0.0f && top_p_ < 1.0f) {'
assert sampler.count(old) == 1
sampler = sampler.replace(old, '}\n  if ((strategy_ == MSLLM_SAMPLER_TOP_K || strategy_ == MSLLM_SAMPLER_TOP_P) && top_p_ > 0.0f && top_p_ < 1.0f) {')
(out/'sampler.cc').write_text(sampler)
compile(out/'sampler.cc', out/'sampler.cc.o', b/'src/CMakeFiles/mslite_llm_static.dir/flags.make')
# Preserve the verified backend objects while replacing the pipeline and sampler.
subprocess.run([str(Path(compiler).parent/'llvm-ar'), 'r', str(out/'libstats.a'), str(out/'llm.cc.o'), str(out/'sampler.cc.o')], check=True)
chat = (root/'examples/mslite-chat.cc').read_text()
chat = chat.replace('int main(int argc, char **argv) {', '#include "resident_server.inc"\n\nint main(int argc, char **argv) {')
chat = chat.replace('  MSLLMStatus status = MSLLMBuildModel(model, model_path);', '  auto load_start = std::chrono::steady_clock::now();\n  MSLLMStatus status = MSLLMBuildModel(model, model_path);')
chat = chat.replace('  std::string rendered_prompt;', '  if (std::getenv("KANBAN_RESIDENT")) return KanbanServe(model, std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - load_start).count());\n  std::string rendered_prompt;')
(out/'mslite-chat.cc').write_text(chat)
wrapper = (root/'examples/qwen35-phone-chat.cc').read_text()
wrapper = wrapper.replace('int main(int argc, char **argv) {', 'int main(int argc, char **argv) {\n  setenv("KANBAN_RESIDENT", "1", 1);')
(out/'qwen35-phone-chat.cc').write_text(wrapper)
compile(out/'qwen35-phone-chat.cc', out/'resident.o', b/'examples/CMakeFiles/qwen35-phone-chat.dir/flags.make', ['-DQWEN35_Q2_EXPERIMENT'])
link = [str(out/'resident.o') if a=='CMakeFiles/qwen35-phone-chat.dir/qwen35-phone-chat.cc.o' else str(out/'libstats.a') if a=='../src/libmindspore-lite-llm.a' else a for a in link]
link[link.index('-o')+1] = str(out/'hf-q35-kanban-resident-v3')
subprocess.run(link, cwd=b/'examples', check=True)
