# 模型 Playground

从看板顶部进入 Playground。网页和命令行共用 dog 上的 mslite-serve。手机持有模型权重并执行推理，访问者只需浏览器或 HTTP 客户端。

| 入口 | 用户操作 | 真机路径 |
|---|---|---|
| 模型对话 | 选择已登记模型、发送多轮文本 | dog 渲染 Qwen ChatML，BinRunner 启动手机上的 mslite-generate，Lite LLM 回调返回生成内容 |
| API 调用 | 复制当前模型的 curl 示例，或配置 OpenAI 客户端的 base_url | GET /v1/models 和 POST /v1/chat/completions |
| 真机 App | 进入设备、点击、拖动、通过屏幕键盘输入、释放设备 | dog 启动指定 Ability，循环获取截图，并将浏览器坐标换算为 UITest 点击或滑动 |

## 在 dog 上启动

使用与部署模型匹配的 OHOS Lite LLM 包。以下命令从仓库根目录运行。DEVICE、BR_PORT、BINRUNNER 和 MODEL_PATH 取自设备 environment，MODEL_PATH 使用手机端的 @/bin/ 路径。RUNTIME 指向包含 include 和 lib 的解压目录，NATIVE 指向 OHOS SDK 的 native 目录。

```sh
"$NATIVE/llvm/bin/clang++" --target=aarch64-linux-ohos --sysroot="$NATIVE/sysroot" \
  -std=c++17 -O2 -static-libstdc++ -I "$RUNTIME/include" scripts/playground/generate.cc \
  -Wl,--whole-archive "$RUNTIME/lib/libmindspore-lite-llm.a" -Wl,--no-whole-archive \
  -ldl -pthread -o /tmp/mslite-generate
(cd "$BINRUNNER" && python3 -m binrunner -t "$DEVICE" -p "$BR_PORT" push /tmp/mslite-generate)
scripts/playground/mslite-serve --device "$DEVICE" --port "$BR_PORT" --binrunner "$BINRUNNER" \
  --model-id Qwen3-4B --model-path "$MODEL_PATH" --context 2048
```

在本机运行 `ssh -L 18081:127.0.0.1:8081 dog -N`，打开 `http://127.0.0.1:18081/playground.html`。页面自动加载部署模型，默认选中第一项。模型列表展示服务的启动配置，首次聊天会实际加载权重。

```sh
curl http://127.0.0.1:18081/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"Qwen3-4B","messages":[{"role":"user","content":"用一句话解释 KV Cache。"}],"max_tokens":128}'
```

远程用户可经 HTTPS 反向代理访问该服务。若现有网关设置了 MSLITE_API_KEY，由受信反向代理注入 Authorization 请求头。若沿用 Vercel 静态页面，需由部署方将同源 /v1/* 与 /device/* 路由到可达的 dog 网关，保留 X-Device-Session 请求头。仓库的默认静态构建只发布界面。聊天网关固定监听 dog 回环地址，每个进程服务一台手机、一个模型，并发请求返回 429。使用同一台手机的 daily 评测应安排在其他时段。

## 手机类型

页面默认选择 Mate 80 Pro（kirin9030），也可切换为 Mate 70 Pro（kirin9202）。浏览器通过 X-Phone-Type 请求头指定手机，切换后重新读取该机型的模型列表。投屏期间先释放设备即可切换。

同时接入两台手机时，在 dog 上分别启动两个服务实例，指定各自的设备、模型路径、投屏设备以及监听端口。为第二个实例传入 `--phone-type mate70-pro --listen-port 8082`。在现有同源反向代理中按下表转发 /v1/* 和 /device/*，保留 X-Phone-Type 和 X-Device-Session 请求头。

| X-Phone-Type | dog 目标实例 |
|---|---|
| mate80-pro 或省略 | 127.0.0.1:8081 |
| mate70-pro | 127.0.0.1:8082 |

## 真机 App

在 dog 上用 hdc 确认专用体验设备在线，并安装待体验的 HAP。启动服务时追加以下参数，bundle 和 ability 取自应用的 module.json5。

```sh
--screen-device "$DEMO_DEVICE" --bundle "$APP_BUNDLE" --ability "$APP_ABILITY"
```

首次进入会拉起指定 App 并分配独占会话。网页收到上一张截图后间隔约 900 ms 请求下一张，实际帧率受截屏与传输耗时影响。切换入口或点击释放会结束会话，关闭页面后租约在最后一次成功操作后 60 秒到期。此模式允许操作整台设备，适用于受信测试者及无个人数据的专用手机。启动 Ability 会保留应用已有状态。对外开放前需在设备侧限制离开体验 App，并在访客交接时清理历史会话。

高级版体验 App 的首屏建议直接展示部署模型和输入框，用户可点示例问题或通过软键盘输入。点发送后，App 在手机内调用 Lite LLM，逐步展示输出，完成后给出实测首 token 时延和生成速度。当前网关可连接已安装的 App，专属 HAP、视频流及访客数据重置属于后续开发。

## 接口范围和真机验收

- 文本接口支持 system、user、assistant 多轮消息，采用 Qwen ChatML 与 Qwen3 非思考模式采样（temperature 0.7、top-p 0.8、top-k 20）。单次输出上限为 1024 token。配置 `--tokenizer` 后按模型 tokenizer 计算输入长度，并根据剩余上下文自动缩减输出预算。未配置 tokenizer 时采用 UTF-8 字节数保守估算。
- 每次请求独立加载模型并收集完整结果。首版尚未提供 SSE、工具调用和常驻模型。参考接口为 [llama.cpp server](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md)。
- 在目标机上发送两轮中文问答，核对第二轮能使用前文；以 max_tokens=1 验证截断原因；拔掉设备后核对 503，再恢复连接重试。
- 打开 App 后点击输入框，用屏幕键盘输入并提交，拖动查看输出。用第二个浏览器验证占用提示、手动释放和过期回收，并核对旋转后触点映射。
- 本地接口测试用替身替代 BinRunner 与 HDC。运行 `python3 -m unittest discover -s tests -p test_playground.py`。物理设备的推理质量、模型加载时延和投屏手感需要在 dog 上验收。

## 临时双站连接

Cloudflare Pages 与 Vercel 的网页通过临时 WebSocket 中继访问 dog 上的模型服务。中继使用 `websockets==15.0.1`，仅转发模型列表及聊天接口，`Origin` 限定为两个看板地址。当前体验不启用账号认证。临时隧道地址重启后变化，需要更新 `playground.mjs` 后重新部署网站。中继地址在 `scripts/playground/temporary_ws_relay.py` 中指定的 18083 端口上启动，连接同机的 8081 模型服务。`mslite-serve` 使用 `--lease-dir /home/zhugd/msl-kanban-ci/leases` 与 Daily 评测共享设备锁。

临时隧道和模型服务当前需要分别保持运行。临时地址并非长期稳定服务，WebSocket 入口的 Origin 限制不是用户认证。不要将真机 App 控制接口暴露给该中继。

Qwen3 服务使用与模型匹配的 tokenizer：安装 `tokenizers==0.22.2`，启动时传入 `--tokenizer /path/to/Qwen3-0.6B/tokenizer.json`。

## Qwen3.5 临时常驻服务（2026-11-25）

Playground 的 Qwen3.5 入口提供“加载模型／卸载模型”和“停止生成”。加载后保留手机模型句柄，后续请求重置生成状态并复用模型。停止请求使用随机请求 ID，只取消对应生成；优先调用 `MSLLMAbort`，超过约 3 秒仍未退出则终止 BinRunner 并卸载模型。取消加载同样会释放设备。其他模型目前仍按请求加载。

`qwen35-preview.py` 提供 `/v1/model/load`、`/v1/model/status`、`/v1/model/unload` 和 `/v1/chat/cancel`，经共享 WebSocket 接口供 Cloudflare 与 Vercel 使用。生成时携带 `request_id`（32 位随机十六进制字符串）。停止不会清空聊天记录；网页保留已显示的内容。

常驻程序通过 `experimental/build_qwen35_resident.py` 构建，依赖已验证的 S2 后端归档。手机仅监听回环端口 18947，dog 通过 HDC 的 28947 端口转发访问；避免占用已有手机转发端口。模型加载耗时与 Prefill / Decode 指标分别展示。性能计时不包含模型加载。

本次临时服务部署到 dog 的 `/var/tmp/msl-kanban-playground-20261125`，运行日志也写入该目录；`/home` 分区已满，需要单独维护磁盘容量。现有模型与 BinRunner 路径保持原位置。常驻模型持有 3001 设备租约，卸载后释放；服务重启或手机应用退出后需重新加载。


### 3001 专用与对话恢复

3001 暂时专供 Playground，不在同一手机并行启动 FLUX 或其他 BinRunner 任务。设备租约只能协调遵守租约的调用方，绕过租约启动的任务仍会重启应用并中断服务。

Qwen3.5 临时常驻程序使用真实的 system/user/assistant 消息角色构造多轮模板，剔除历史回答中的思考区段与性能附注；仅包含未完成思考的轮次不重放。当前运行库的模板接口固定 `add_generation_prompt=false`，服务在完整消息之后追加官方非思考回答前缀，不截断已有 assistant 历史。默认直接回答，采样使用 temperature=0.7、top_p=0.8、top_k=20、presence_penalty=1.5、repetition_penalty=1.0，输出上限 1024 tokens。参数来源：[Qwen3.5-35B-A3B 模型说明](https://huggingface.co/Qwen/Qwen3.5-35B-A3B)。

加载超时仅适用于首次加载阶段。模型就绪后暂时断联显示“模型连接异常／重试连接”；进程退出则提示连接断开并允许重新加载，不再按原加载时间误判为超时并强制卸载。

手机模型端口已消失而 BinRunner 等待进程尚未退出时，服务通过手机侧监听端口确认退出，仅清理自身的 dog 等待进程和租约，返回“模型服务已退出，请重新加载”。HDC 探测失败视为状态未知，不据此卸载模型；转发丢失时先尝试恢复转发。网页“重试连接”确认模型已退出后直接进入加载流程。
