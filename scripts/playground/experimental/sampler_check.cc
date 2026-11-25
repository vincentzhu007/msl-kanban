#include "sampler/sampler.h"
#include <iostream>
int main() {
  MSLlmGenerateConfig c{};
  c.temperature=1; c.top_k=2; c.top_p=0.1; c.repetition_penalty=1; c.seed=42;
  mslite_llm::Sampler s(c);
  int outside=0;
  for(int i=0;i<1000;++i) if(s.Sample(std::vector<float>{2,1,0})!=0) ++outside;
  std::cout << "outside top-p nucleus: " << outside << '\n';
  return outside?1:0;
}
