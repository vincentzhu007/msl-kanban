// Included after mslite-chat helpers; temporary single-model phone service.
#include <arpa/inet.h>
#include <sys/socket.h>
#include <sys/time.h>
#include <unistd.h>
#include <atomic>
#include <sstream>
#include <unordered_set>

extern "C" size_t MSLLMKanbanInputTokens();
extern "C" void MSLLMKanbanPresencePenalty(MSLLMModelHandle, float);
namespace {
std::mutex kanban_mutex;
std::string kanban_active;
std::unordered_set<std::string> kanban_cancelled;
std::atomic<bool> kanban_cancel{false};

std::string JsonString(const std::string &s) {
  std::string out = "\"";
  const char *hex = "0123456789abcdef";
  for (unsigned char c : s) {
    if (c == '\\' || c == '"') { out += '\\'; out += c; }
    else if (c < 32) { out += "\\u00"; out += hex[c >> 4]; out += hex[c & 15]; }
    else out += c;
  }
  return out + '"';
}
bool SendLine(int fd, const std::string &s) {
  std::string wire = s + '\n'; size_t pos = 0;
  while (pos < wire.size()) {
    auto n = send(fd, wire.data() + pos, wire.size() - pos, MSG_NOSIGNAL);
    if (n <= 0) return false;
    pos += n;
  }
  return true;
}
std::string HexBytes(const std::string &bytes) {
  const char *hex = "0123456789abcdef";
  std::string out;
  out.reserve(bytes.size() * 2);
  for (unsigned char c : bytes) { out += hex[c >> 4]; out += hex[c & 15]; }
  return out;
}
bool ReadBytes(int fd, char *p, size_t size) {
  while (size) { auto n = recv(fd, p, size, 0); if (n <= 0) return false; p += n; size -= n; }
  return true;
}
void KanbanClient(int fd, MSLLMModelHandle model, double load_ms) {
  struct CloseSocket { int fd; ~CloseSocket() { close(fd); } } close_socket{fd};
  timeval timeout{30, 0};
  setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &timeout, sizeof(timeout));
  setsockopt(fd, SOL_SOCKET, SO_SNDTIMEO, &timeout, sizeof(timeout));
  std::string header; char c;
  while (header.size() < 128 && ReadBytes(fd, &c, 1) && c != '\n') header += c;
  std::istringstream in(header); std::string op, id; int limit = 0; size_t size = 0;
  in >> op >> id >> limit >> size;
  if (op == "status") {
    std::lock_guard<std::mutex> lock(kanban_mutex);
    SendLine(fd, "{\"state\":" + JsonString(kanban_active.empty() ? "ready" : "generating") +
      ",\"request_id\":" + JsonString(kanban_active) + ",\"load_ms\":" + std::to_string(load_ms) + "}");
    return;
  }
  if (op == "cancel") {
    std::lock_guard<std::mutex> lock(kanban_mutex);
    if (id == kanban_active && !id.empty()) { kanban_cancel.store(true); MSLLMAbort(model); }
    else { if (kanban_cancelled.size() > 1024) kanban_cancelled.clear(); kanban_cancelled.insert(id); }
    SendLine(fd, "{\"stopping\":true}"); return;
  }
  if (op != "chat" || id.size() != 32 || id.find_first_not_of("0123456789abcdef") != std::string::npos ||
      limit < 1 || limit > 1024 || size == 0 || size > 25) {
    SendLine(fd, "{\"error\":\"Invalid request\"}"); return;
  }
  std::vector<std::string> contents; std::vector<MSLLMChatMessage> messages;
  contents.reserve(size); messages.reserve(size); size_t total = 0;
  for (size_t i = 0; i < size; ++i) {
    std::string part; char ch;
    while (part.size() < 64 && ReadBytes(fd, &ch, 1) && ch != '\n') part += ch;
    std::istringstream fields(part); std::string role; size_t length = 0;
    fields >> role >> length;
    if ((role != "system" && role != "user" && role != "assistant") || !length || length > 24000 || total + length > 24000) {
      SendLine(fd, "{\"error\":\"Invalid message\"}"); return;
    }
    total += length; contents.emplace_back(length, '\0');
    if (!ReadBytes(fd, &contents.back()[0], length)) return;
    messages.push_back({role == "system" ? MSLLM_ROLE_SYSTEM : role == "user" ? MSLLM_ROLE_USER : MSLLM_ROLE_ASSISTANT, contents.back().c_str()});
  }
  {
    std::lock_guard<std::mutex> lock(kanban_mutex);
    if (!kanban_active.empty()) { SendLine(fd, "{\"error\":\"Device busy\"}"); return; }
    if (kanban_cancelled.erase(id)) { SendLine(fd, "{\"done\":true,\"finish_reason\":\"cancelled\"}"); return; }
    kanban_active = id; kanban_cancel.store(false);
  }
  struct Finish {
    ~Finish() { std::lock_guard<std::mutex> lock(kanban_mutex); kanban_active.clear(); }
  } finish;
  std::string prompt;
  std::vector<char> rendered(65536);
  if (MSLLMApplyChatTemplate(model, messages.data(), static_cast<int>(messages.size()), rendered.data(), rendered.size()) != kMSLLM_SUCCESS) {
    SendLine(fd, "{\"error\":\"Template failed\"}"); return;
  }
  prompt = rendered.data();
  // This runtime renders with add_generation_prompt=false. Append the official
  // Qwen3.5 enable_thinking=false suffix without altering prior assistant turns.
  prompt += "<|im_start|>assistant\n<think>\n\n</think>\n\n";
  MSLLMGenerationConfig config = {};
  config.max_new_tokens = limit; config.do_sample = true; config.temperature = 0.7f;
  config.top_k = 20; config.top_p = 0.8f; config.repetition_penalty = 1;
  if (MSLLMSetGenerationConfig(model, config) != kMSLLM_SUCCESS) {
    SendLine(fd, "{\"error\":\"Configuration failed\"}"); return;
  }
  MSLLMKanbanPresencePenalty(model, 1.5f);
  StreamSink sink;
  sink.t_start = sink.t_last = std::chrono::steady_clock::now();
  std::atomic<bool> worker_done{false};
  std::thread worker([&] {
    sink.generate_status = MSLLMStreamGenerate(model, prompt.c_str(), OnStreamToken, &sink);
    { std::lock_guard<std::mutex> lock(sink.mtx); sink.done = true; }
    worker_done.store(true); sink.cv.notify_one();
  });
  // Abort is a no-op before PrepareGeneration; retry until the worker exits.
  std::thread canceller([&] {
    while (!worker_done.load()) {
      if (kanban_cancel.load()) MSLLMAbort(model);
      std::this_thread::sleep_for(std::chrono::milliseconds(20));
    }
  });
  bool connected = true;
  for (;;) {
    std::string token;
    {
      std::unique_lock<std::mutex> lock(sink.mtx);
      sink.cv.wait(lock, [&] { return !sink.tokens.empty() || sink.done; });
      if (sink.tokens.empty()) break;
      token = std::move(sink.tokens.front()); sink.tokens.pop_front();
    }
    auto now = std::chrono::steady_clock::now();
    double ms = std::chrono::duration<double, std::milli>(now - sink.t_last).count();
    if (!sink.prefill_tokens) { sink.prefill_tokens = 1; sink.prefill_ms = ms; }
    else { ++sink.decode_tokens; sink.decode_ms += ms; }
    sink.t_last = now;
    if (connected && !SendLine(fd, "{\"content_hex\":\"" + HexBytes(token) + "\"}")) {
      connected = false; kanban_cancel.store(true);
    }
  }
  worker.join(); canceller.join();
  if (sink.generate_status != kMSLLM_SUCCESS) {
    SendLine(fd, "{\"error\":\"Runtime error " + std::to_string(sink.generate_status) + "\"}"); return;
  }
  std::string reason = kanban_cancel.load() ? "cancelled" :
    (sink.final_reason == kMSLLM_FINISHED_BY_MAX_OUTPUT_LENGTH ? "length" : "stop");
  SendLine(fd, "{\"done\":true,\"input_tokens\":" + std::to_string(MSLLMKanbanInputTokens()) +
    ",\"prefill_ms\":" + std::to_string(sink.prefill_ms) + ",\"decode_tokens\":" + std::to_string(sink.decode_tokens) +
    ",\"decode_ms\":" + std::to_string(sink.decode_ms) + ",\"finish_reason\":" + JsonString(reason) + "}");
}
int KanbanServe(MSLLMModelHandle model, double load_ms) {
  int fd = socket(AF_INET, SOCK_STREAM, 0); int reuse = 1;
  setsockopt(fd, SOL_SOCKET, SO_REUSEADDR, &reuse, sizeof(reuse));
  sockaddr_in address{}; address.sin_family = AF_INET; address.sin_port = htons(18947);
  address.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
  if (bind(fd, reinterpret_cast<sockaddr *>(&address), sizeof(address)) || listen(fd, 8)) return 1;
  std::cout << "[kanban] model ready load_ms=" << load_ms << std::endl;
  while (true) {
    int client = accept(fd, nullptr, nullptr);
    if (client < 0) break;
    std::thread(KanbanClient, client, model, load_ms).detach();
  }
  close(fd); return 1;
}
}
