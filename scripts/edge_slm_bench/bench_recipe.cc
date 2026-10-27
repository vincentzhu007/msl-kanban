#include "../bench_common/probe_options.h"
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <vector>
#include <sys/resource.h>
#include <sys/stat.h>
#include <unistd.h>
#include <sys/prctl.h>
#include "llm/llm.h"

int model_context = -1;
using Clock = std::chrono::steady_clock;
double ms(Clock::time_point a, Clock::time_point b) {
  return std::chrono::duration<double, std::milli>(b-a).count();
}
long rss_kib() {
  FILE *f = fopen("/proc/self/status", "r");
  if (!f) return -1;
  char line[256]; long value = -1;
  while (fgets(line, sizeof(line), f)) {
    if (sscanf(line, "VmRSS: %ld kB", &value) == 1) break;
  }
  fclose(f); return value;
}
bool read_u32(FILE *f, uint32_t *v) { return fread(v, 4, 1, f) == 1; }
bool metadata(const char *path) {
  FILE *f = fopen(path, "rb");
  if (!f) return false;
  unsigned char hdr[24];
  if (fread(hdr, 1, 24, f) != 24 || memcmp(hdr, ".MSL", 4)) { fclose(f); return false; }
  uint32_t count; memcpy(&count, hdr+8, 4);
  if (count > 1024) { fclose(f); return false; }
  for (uint32_t i=0; i<count; ++i) {
    uint32_t n, type, size;
    if (!read_u32(f,&n) || n > 4096) { fclose(f); return false; }
    std::string key(n, '\0');
    if (fread(key.data(),1,n,f)!=n || !read_u32(f,&type) || !read_u32(f,&size) || size>1048576) { fclose(f); return false; }
    std::vector<unsigned char> v(size+1,0);
    if (fread(v.data(),1,size,f)!=size) { fclose(f); return false; }
    // Emit only deployment metadata, never resource payloads or tokenizer content.
    if (key == "npu.max_length" && type == 1 && size == 4) { uint32_t x; memcpy(&x,v.data(),4); model_context = static_cast<int>(x); }
    bool allowed = key.rfind("arch.",0)==0 || key.rfind("npu.",0)==0 || key=="model.name" || key=="model.dtype" || key=="model.version";
    if (!allowed) continue;
    if (type==4) printf("META %s=%s\n",key.c_str(),v.data());
    else if (type==1 && size==4) { uint32_t x; memcpy(&x,v.data(),4); printf("META %s=%u\n",key.c_str(),x); }
    else if (type==0 && size==1) printf("META %s=%u\n",key.c_str(),v[0]);
  }
  fclose(f); return true;
}
struct Sink {
  Clock::time_point start, first, last;
  int count=0, reason=-1;
};
void callback(const char *token, MSLLMFinishReason reason, void *opaque) {
  auto *s=static_cast<Sink*>(opaque);
  if (!token) { s->reason=reason; return; }
  auto now=Clock::now();
  if (!s->count) s->first=now;
  s->last=now; ++s->count;
}
int main(int argc,char **argv) {
  ProbeOptions options;
  if (!options.parse(argc, argv)) { fprintf(stderr, "Usage: model repetitions logfile context input output\n"); return 2; }
  if(argc>=4){
    pid_t pid=fork(); if(pid<0)return 10; if(pid>0){printf("WORKER_PID %d\n",pid);return 0;}
    setsid();prctl(PR_SET_NAME,"recipe-msl",0,0,0);alarm(1800);
    if(!freopen(argv[3],"w",stdout))_exit(11);dup2(fileno(stdout),2);setvbuf(stdout,nullptr,_IONBF,0);
  }
  if (argc<2 || !metadata(argv[1])) return 2;
  if (argc==2) return 0;
  const int repeats = options.repetitions;
  if (model_context != options.context) { printf("ERROR model context mismatch: %d vs %d\n", model_context, options.context); return 2; }
  options.report();
  struct stat st{}; if (stat(argv[1],&st)) return 2;
  printf("MODEL_BYTES %lld\n",static_cast<long long>(st.st_size));
  printf("PID %d MONOTONIC_MS %.6f\n", getpid(), ms(Clock::time_point{}, Clock::now())); fflush(stdout);
  printf("WALL_MS %.6f MONOTONIC_MS %.6f\n",std::chrono::duration<double,std::milli>(std::chrono::system_clock::now().time_since_epoch()).count(),ms(Clock::time_point{},Clock::now())); fflush(stdout);
  long before=rss_kib();
  auto model=MSLLMCreateModel(); if (!model) return 3;
  auto start=Clock::now(); auto status=MSLLMBuildModel(model,argv[1]);
  printf("BUILD status=%d ms=%.6f rss_before_kib=%ld rss_loaded_kib=%ld\n",status,ms(start,Clock::now()),before,rss_kib());
  if (status!=kMSLLM_SUCCESS) { MSLLMDestroyModel(&model); return 4; }
  MSLLMGenerationConfig cfg{}; cfg.max_new_tokens=options.output; cfg.do_sample=false;
  cfg.temperature=1; cfg.top_k=1; cfg.top_p=1; cfg.repetition_penalty=1;
  if (MSLLMSetGenerationConfig(model,cfg)!=kMSLLM_SUCCESS) { MSLLMDestroyModel(&model); return 5; }
  for (int words : {options.input}) {
    std::string prompt;
    for (int i=0;i<words;++i) prompt += " hello";
    // Raw synthetic prompt, no chat template; generation budget comes from the versioned recipe protocol.
    for (int run=1;run<=repeats;++run) {
      Sink s; s.start=Clock::now();
      printf("PHASE inference run=%d monotonic_ms=%.6f\n",run,ms(Clock::time_point{},s.start)); fflush(stdout);
      status=MSLLMStreamGenerate(model,prompt.c_str(),callback,&s);
      auto end=Clock::now();
      printf("PHASE end run=%d monotonic_ms=%.6f\n",run,ms(Clock::time_point{},end));
      struct rusage ru{}; int ru_status=getrusage(RUSAGE_SELF,&ru);
      double first=s.count ? ms(s.start,s.first) : -1;
      double decode=s.count>1 ? ms(s.first,s.last) : -1;
      printf("RESULT {\"hello_repetitions\":%d,\"prompt_bytes\":%zu,\"run\":%d,\"warmup\":%s,\"status\":%d,\"finish_reason\":%d,\"output_callbacks\":%d,\"ttft_ms\":%.6f,\"decode_ms\":%.6f,\"decode_tps\":%.6f,\"total_ms\":%.6f,\"rss_after_kib\":%ld,\"process_hwm_kib\":%ld}\n",words,prompt.size(),run,run==0?"true":"false",status,s.reason,s.count,first,decode,decode>0?(s.count-1)*1000.0/decode:0.0,ms(s.start,end),rss_kib(),ru_status==0?ru.ru_maxrss:-1L);
      fflush(stdout);
      if (status!=kMSLLM_SUCCESS || s.count!=options.output) { MSLLMDestroyModel(&model); return 6; }

    }
  }
  auto destroy=MSLLMDestroyModel(&model);
  printf("DESTROY status=%d\n",destroy);
  return destroy==kMSLLM_SUCCESS?0:7;
}
