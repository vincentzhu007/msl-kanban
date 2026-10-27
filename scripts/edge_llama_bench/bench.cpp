#include "llama.h"
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <string>
#include <vector>
#include <unistd.h>
#include <sys/prctl.h>
#include <sys/stat.h>
using Clock=std::chrono::steady_clock;
double ms(Clock::time_point a,Clock::time_point b){return std::chrono::duration<double,std::milli>(b-a).count();}
int main(int argc,char**argv){
 if(argc!=3)return 2;
 pid_t pid=fork();if(pid<0)return 3;if(pid>0){printf("WORKER_PID %d\n",pid);return 0;}
 setsid();prctl(PR_SET_NAME,"edge-llama",0,0,0);alarm(1800);
 if(!freopen(argv[2],"w",stdout))_exit(4);dup2(fileno(stdout),2);setvbuf(stdout,nullptr,_IONBF,0);
 printf("PID %d\nWALL_MS %.6f MONOTONIC_MS %.6f\n",getpid(),std::chrono::duration<double,std::milli>(std::chrono::system_clock::now().time_since_epoch()).count(),ms(Clock::time_point{},Clock::now()));
 llama_backend_init();auto begin=Clock::now();auto mp=llama_model_default_params();mp.n_gpu_layers=0;
 auto*model=llama_model_load_from_file(argv[1],mp);if(!model){printf("ERROR model\n");_exit(5);}
 auto cp=llama_context_default_params();cp.n_ctx=2048;cp.n_batch=64;cp.n_ubatch=64;cp.n_threads=4;cp.n_threads_batch=4;cp.offload_kqv=false;cp.op_offload=false;cp.flash_attn_type=LLAMA_FLASH_ATTN_TYPE_DISABLED;
 auto*ctx=llama_init_from_model(model,cp);if(!ctx){printf("ERROR context\n");_exit(6);}
 auto*vocab=llama_model_get_vocab(model);auto*sampler=llama_sampler_init_greedy();
 printf("BUILD ms=%.6f threads=4 n_ctx=%u n_batch=64 n_gpu_layers=0\n",ms(begin,Clock::now()),llama_n_ctx(ctx));
 std::string prompt;for(int i=0;i<1024;i++)prompt+=" hello";
 for(int run=1;run<=5;run++){
  llama_memory_clear(llama_get_memory(ctx),true);llama_sampler_reset(sampler);
  auto start=Clock::now();printf("PHASE inference run=%d monotonic_ms=%.6f\n",run,ms(Clock::time_point{},start));
  std::vector<llama_token> tokens(1100);int count=llama_tokenize(vocab,prompt.c_str(),prompt.size(),tokens.data(),tokens.size(),false,false);
  if(count!=1024){printf("ERROR input_tokens=%d\n",count);_exit(7);}
  for(int i=0;i<count;i+=64){auto batch=llama_batch_get_one(tokens.data()+i,64);if(llama_decode(ctx,batch)){printf("ERROR prefill\n");_exit(8);}}
  auto token=llama_sampler_sample(sampler,ctx,-1);llama_sampler_accept(sampler,token);auto first=Clock::now();int eog=llama_vocab_is_eog(vocab,token)?1:0;
  for(int i=1;i<128;i++){auto batch=llama_batch_get_one(&token,1);if(llama_decode(ctx,batch)){printf("ERROR decode\n");_exit(9);}token=llama_sampler_sample(sampler,ctx,-1);llama_sampler_accept(sampler,token);if(llama_vocab_is_eog(vocab,token))eog++;}
  auto end=Clock::now();double dec=ms(first,end);
  printf("PHASE end run=%d monotonic_ms=%.6f\n",run,ms(Clock::time_point{},end));
  printf("RESULT {\"run\":%d,\"input_tokens\":%d,\"output_callbacks\":128,\"status\":0,\"eog_tokens\":%d,\"ttft_ms\":%.6f,\"decode_ms\":%.6f,\"decode_tps\":%.6f,\"total_ms\":%.6f}\n",run,count,eog,ms(start,first),dec,127000/dec,ms(start,end));
 }
 llama_sampler_free(sampler);llama_free(ctx);llama_model_free(model);llama_backend_free();printf("DONE status=0\n");fflush(stdout);_exit(0);
}
