#include "../bench_common/probe_options.h"
#include <algorithm>
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
 ProbeOptions options;
 if (!options.parse(argc, argv, true)) { fprintf(stderr,"Usage: model repetitions logfile context input output threads batch\n"); return 2; }
 pid_t pid=fork();if(pid<0)return 3;if(pid>0){printf("WORKER_PID %d\n",pid);return 0;}
 setsid();prctl(PR_SET_NAME,"recipe-llama",0,0,0);alarm(1800);
 if(!freopen(argv[3],"w",stdout))_exit(4);dup2(fileno(stdout),2);setvbuf(stdout,nullptr,_IONBF,0);
 printf("PID %d\nWALL_MS %.6f MONOTONIC_MS %.6f\n",getpid(),std::chrono::duration<double,std::milli>(std::chrono::system_clock::now().time_since_epoch()).count(),ms(Clock::time_point{},Clock::now()));
 auto init_start=Clock::now();llama_backend_init();auto begin=Clock::now();auto mp=llama_model_default_params();mp.n_gpu_layers=0;
 auto*model=llama_model_load_from_file(argv[1],mp);if(!model){printf("ERROR model\n");_exit(5);}
 auto cp=llama_context_default_params();cp.n_ctx=options.context;cp.n_batch=options.batch;cp.n_ubatch=options.batch;cp.n_threads=options.threads;cp.n_threads_batch=options.threads;cp.offload_kqv=false;cp.op_offload=false;cp.flash_attn_type=LLAMA_FLASH_ATTN_TYPE_DISABLED;
 auto*ctx=llama_init_from_model(model,cp);if(!ctx){printf("ERROR context\n");_exit(6);}
 auto*vocab=llama_model_get_vocab(model);auto*sampler=llama_sampler_init_greedy();
 if (llama_n_ctx(ctx) != static_cast<unsigned>(options.context)) { printf("ERROR actual context mismatch\n"); _exit(6); }
 printf("INIT {\"model_init_ms\":%.6f}\n",ms(init_start,Clock::now()));
 options.report(true);
 printf("BUILD ms=%.6f threads=%d n_ctx=%u n_batch=%d n_gpu_layers=0\n",ms(begin,Clock::now()),options.threads,llama_n_ctx(ctx),options.batch);
 std::string prompt;for(int i=0;i<options.input;i++)prompt+=" hello";
 for(int run=1;run<=options.repetitions;run++){
  llama_memory_clear(llama_get_memory(ctx),true);llama_sampler_reset(sampler);
  auto start=Clock::now();printf("PHASE inference run=%d monotonic_ms=%.6f\n",run,ms(Clock::time_point{},start));
  std::vector<llama_token> tokens(options.input + 16);int count=llama_tokenize(vocab,prompt.c_str(),prompt.size(),tokens.data(),tokens.size(),false,false);
  if(count!=options.input){printf("ERROR input_tokens=%d\n",count);_exit(7);}
  auto prefill_start=Clock::now();
  for(int i=0;i<count;i+=options.batch){auto batch=llama_batch_get_one(tokens.data()+i,std::min(options.batch,count-i));if(llama_decode(ctx,batch)){printf("ERROR prefill\n");_exit(8);}}
  llama_synchronize(ctx);auto prefill_end=Clock::now();
  auto token=llama_sampler_sample(sampler,ctx,-1);llama_sampler_accept(sampler,token);auto first=Clock::now();int eog=llama_vocab_is_eog(vocab,token)?1:0;
  for(int i=1;i<options.output;i++){auto batch=llama_batch_get_one(&token,1);if(llama_decode(ctx,batch)){printf("ERROR decode\n");_exit(9);}token=llama_sampler_sample(sampler,ctx,-1);llama_sampler_accept(sampler,token);if(llama_vocab_is_eog(vocab,token))eog++;}
  auto end=Clock::now();double dec=ms(first,end);
  printf("PHASE end run=%d monotonic_ms=%.6f\n",run,ms(Clock::time_point{},end));
  printf("RESULT {\"run\":%d,\"input_tokens\":%d,\"output_callbacks\":%d,\"status\":0,\"eog_tokens\":%d,\"prefill_ms\":%.6f,\"ttft_ms\":%.6f,\"decode_ms\":%.6f,\"decode_tps\":%.6f,\"total_ms\":%.6f}\n",run,count,options.output,eog,ms(prefill_start,prefill_end),ms(start,first),dec,(options.output-1)*1000.0/dec,ms(start,end));
 }
 llama_sampler_free(sampler);llama_free(ctx);llama_model_free(model);llama_backend_free();printf("DONE status=0\n");fflush(stdout);_exit(0);
}
