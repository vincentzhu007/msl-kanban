from pathlib import Path
import re,shlex,subprocess,shutil
root=Path('/agents/hf-agent-qwen35-moe-s4')
b=root/'mindspore-lite/mindspore-lite/lite_llm/build'
out=Path('/tmp/kanban-q35-stats');out.mkdir(exist_ok=True)
def remap(s):return s.replace('/repos/hf-agent-qwen35-moe-s4','/agents/hf-agent-qwen35-moe-s4')
flags=remap((b/'src/CMakeFiles/mslite_llm_static.dir/flags.make').read_text())
link=remap((b/'examples/CMakeFiles/qwen35-phone-chat.dir/link.txt').read_text())
compiler=shlex.split(link)[0]; native=Path(compiler).parents[2]
src=(b.parent/'src/pipeline/llm.cc').read_text()
assert src.count('*input_ids = e->tokenizer->Encode(prompt);')==1
src= '#include <cstdio>\n'+src.replace('*input_ids = e->tokenizer->Encode(prompt);','*input_ids = e->tokenizer->Encode(prompt);\n  std::fprintf(stderr, "[stats] input_tokens: %zu\\n", input_ids->size());')
src=src.replace('#include "../llm_types_internal.h"','#include "llm_types_internal.h"')
(out/'llm.cc').write_text(src)
args=[compiler,'--target=aarch64-linux-ohos','--sysroot='+str(native/'sysroot')]
for key in ['CXX_DEFINES','CXX_INCLUDES','CXX_FLAGS']:
 args+=shlex.split(re.search('^'+key+r' = (.*)$',flags,re.M)[1])
subprocess.run(args+['-c',str(out/'llm.cc'),'-o',str(out/'llm.cc.o')],check=True)
shutil.copy2(b/'src/libmindspore-lite-llm.a',out/'libstats.a')
subprocess.run([str(Path(compiler).parent/'llvm-ar'),'r',str(out/'libstats.a'),str(out/'llm.cc.o')],check=True)

make=(b/'src/backend/nnrt/CMakeFiles/mslite_llm_nnrt_backend.dir/build.make').read_text()
backendflags=remap((b/'src/backend/nnrt/CMakeFiles/mslite_llm_nnrt_backend.dir/flags.make').read_text())
args=[compiler,'--target=aarch64-linux-ohos','--sysroot='+str(native/'sysroot')]
for key in ['CXX_DEFINES','CXX_INCLUDES','CXX_FLAGS']:
 args+=shlex.split(re.search('^'+key+r' = (.*)$',backendflags,re.M)[1])
sources=sorted(set(re.findall(r'-c ([^\s]+\.cc)',make)))
for source in sources:
 source=Path(remap(source)); obj=out/(source.name+'.o')
 custom=re.search(r'^# Custom options: .*?/'+re.escape(source.name)+r'\.o_OPTIONS = (.*)$',backendflags,re.M)
 extra=shlex.split(custom[1]) if custom else []
 command=args+extra+['-DQWEN35_Q2_EXPERIMENT','-c',str(source),'-o',str(obj)]
 subprocess.run(command,check=True)
 subprocess.run([str(Path(compiler).parent/'llvm-ar'),'r',str(out/'libstats.a'),str(obj)],check=True)
print('Recompiled S2 sources:',len(sources),flush=True)
flags2=remap((b/'examples/CMakeFiles/qwen35-phone-chat.dir/flags.make').read_text())
args2=[compiler,'-DQWEN35_Q2_EXPERIMENT','--target=aarch64-linux-ohos','--sysroot='+str(native/'sysroot')]
for key in ['CXX_DEFINES','CXX_INCLUDES','CXX_FLAGS']:
 args2+=shlex.split(re.search('^'+key+r' = (.*)$',flags2,re.M)[1])
subprocess.run(args2+['-c',str(b.parent/'examples/qwen35-phone-chat.cc'),'-o',str(out/'chat.o')],check=True)
args=shlex.split(link);args=[str(out/'chat.o') if a=='CMakeFiles/qwen35-phone-chat.dir/qwen35-phone-chat.cc.o' else a for a in args];args[args.index('-o')+1]=str(out/'hf-q35-kanban-stats')
args=[str(out/'libstats.a') if a=='../src/libmindspore-lite-llm.a' else a for a in args]
subprocess.run(args,cwd=b/'examples',check=True)
print(out/'hf-q35-kanban-stats')
