#!/usr/bin/env python3
"""Temporary Qwen3.5 resident model API shared by both hosted Playgrounds."""
import json
import re
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from cancellation import Generations, GenerationStopped
from qwen35_resident import Resident, DEVICE

MODEL = 'Qwen3.5 · 3001（临时）'
GENERATIONS = Generations()
RESIDENT = Resident()
SLOT = threading.Lock()

STATS_MARKER = '\n\n---\n**本次推理性能（mslite-chat）**'


def performance_footer(output):
    prefill = re.search(r'^\[stats\] prefill: (\d+) token, ([0-9.eE+-]+) ms$', output, re.M)
    decode = re.search(r'^\[stats\] decode: (\d+) tokens, total ([0-9.eE+-]+) ms, avg ([0-9.eE+-]+) ms/token$', output, re.M)
    if not prefill and not decode:
        return ''
    rows = [STATS_MARKER]
    input_tokens = re.search(r'^\[stats\] input_tokens: (\d+)$', output, re.M)
    if prefill:
        rows.append(f'- Prefill / 首 token 耗时：{float(prefill[2]):.2f} ms（含首次采样）')
        if input_tokens and float(prefill[2]) > 0:
            count = int(input_tokens[1])
            rows.append(f'- Prefill 速度：{count * 1000 / float(prefill[2]):.2f} token/s · 输入 {count} tokens（含模板；不含模型加载）')
        else:
            rows.append('- Prefill 速度：未提供输入 token 数，无法计算')
    if decode:
        count, elapsed = int(decode[1]), float(decode[2])
        if count > 0 and elapsed > 0:
            rows.append(f'- Decode 速度：{count * 1000 / elapsed:.2f} token/s · {count} tokens · 平均 {elapsed / count:.2f} ms/token')
    return '\n'.join(rows) + '\n'

def normalize_messages(messages):
    if not isinstance(messages, list) or not 1 <= len(messages) <= 24:
        raise ValueError('对话格式不正确。')
    result = []
    for message in messages:
        if not isinstance(message, dict) or message.get('role') not in ('user','assistant','system') or not isinstance(message.get('content'), str) or not message['content'].strip():
            raise ValueError('对话格式不正确。')
        role, content = message['role'], message['content']
        if '\x00' in content:
            raise ValueError('输入不能包含空字符。')
        if role == 'system' and result:
            raise ValueError('系统消息只能位于对话开头。')
        if role == 'assistant':
            content = content.split(STATS_MARKER, 1)[0]
            if '</think>' in content:
                content = content.rsplit('</think>', 1)[1]
            content = re.sub(r'<think>.*?(?:</think>|$)', '', content, flags=re.S).strip()
            if not content:
                # A cancelled thinking-only answer isn't a completed conversation turn.
                if result and result[-1]['role'] == 'user':
                    result.pop()
                continue
        result.append({'role':role, 'content':content})
    if not result or result[-1]['role'] != 'user':
        raise ValueError('请以用户消息结束对话。')
    if result[0]['role'] != 'system':
        result.insert(0, {'role':'system','content':'You are a helpful assistant.'})
    if sum(len(m['content'].encode()) for m in result) > 24000:
        raise ValueError('输入超过临时体验版 24 KB 限制，请缩短内容。')
    return result

class Handler(BaseHTTPRequestHandler):
    def reply(self, status, body):
        payload = json.dumps(body, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Length', str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def emit(self, value):
        self.wfile.write(('data: '+json.dumps(value, ensure_ascii=False)+'\n\n').encode())
        self.wfile.flush()

    def do_POST(self):
        streaming = False
        try:
            if self.path not in ('/v1/chat/completions','/v1/chat/cancel','/v1/model/load','/v1/model/status','/v1/model/unload'):
                return self.reply(404, {'error':{'message':'Unknown endpoint'}})
            size = int(self.headers.get('Content-Length', '0'))
            if not 0 < size <= 65536:
                raise ValueError('请求内容超出限制。')
            body = json.loads(self.rfile.read(size))
            if not isinstance(body, dict) or body.get('model') != MODEL:
                raise ValueError('模型不正确。')
            key = body.get('request_id')
            GENERATIONS.validate(key)
            if self.path == '/v1/chat/cancel':
                result = GENERATIONS.cancel(key)
                if RESIDENT.loading_id == key:
                    RESIDENT.cancel(key)
                return self.reply(200, result)
            if self.path == '/v1/model/status':
                return self.reply(200, RESIDENT.status())
            if self.path == '/v1/model/load':
                if not key:
                    raise ValueError('Missing request_id')
                with GENERATIONS.track(key, DEVICE, lambda: RESIDENT.cancel(key)) as operation:
                    result = operation.submit(lambda: RESIDENT.load(key))
                return self.reply(200, result)
            if self.path == '/v1/model/unload':
                if not SLOT.acquire(blocking=False):
                    return self.reply(409, {'error':{'message':'请先停止当前生成，再卸载模型。'}})
                try:
                    if RESIDENT.status()['state'] in ('generating', 'loading'):
                        return self.reply(409, {'error':{'message':'模型正在使用，请稍后卸载。'}})
                    RESIDENT.stop()
                    return self.reply(200, RESIDENT.status())
                finally:
                    SLOT.release()
            messages = normalize_messages(body.get('messages'))
            limit = body.get('max_tokens',1024)
            if type(limit) is not int or not 1 <= limit <= 1024:
                raise ValueError('输出长度无效。')
            if not SLOT.acquire(blocking=False):
                return self.reply(429, {'error':{'message':'设备正在生成，请稍后重试。'}})
            try:
                old_client = key is None
                key = key or uuid.uuid4().hex
                with GENERATIONS.track(key, DEVICE, lambda: RESIDENT.cancel(key)) as generation:
                    # Keep already-open clients working during the frontend rollout.
                    if old_client and RESIDENT.status()['state']=='unloaded':
                        generation.submit(lambda: RESIDENT.load(key))
                        deadline = time.monotonic()+180
                        while RESIDENT.status()['state']=='loading' and time.monotonic()<deadline:
                            time.sleep(.5)
                    sock = generation.submit(lambda: RESIDENT.connect(key,messages,limit))
                    with sock, sock.makefile('rb') as source:
                        self.send_response(200)
                        self.send_header('Content-Type','text/event-stream; charset=utf-8')
                        self.send_header('Cache-Control','no-cache, no-transform')
                        self.send_header('Connection','close')
                        self.end_headers()
                        streaming = True
                        done = False
                        for raw in source:
                            event = json.loads(raw)
                            if event.get('error'):
                                raise RuntimeError(event['error'])
                            if 'content' in event:
                                self.emit({'choices':[{'delta':{'content':event['content']},'finish_reason':None}]})
                            if event.get('done'):
                                if event.get('finish_reason') != 'cancelled' and 'input_tokens' in event:
                                    stats = f"[stats] input_tokens: {event['input_tokens']}\n[stats] prefill: 1 token, {event['prefill_ms']} ms\n[stats] decode: {event['decode_tokens']} tokens, total {event['decode_ms']} ms, avg 0 ms/token"
                                    self.emit({'choices':[{'delta':{'content':performance_footer(stats)},'finish_reason':None}]})
                                self.emit({'choices':[{'delta':{},'finish_reason':event.get('finish_reason','stop')}]})
                                self.wfile.write(b'data: [DONE]\n\n'); self.wfile.flush()
                                done = True
                                break
                        if not done and not generation.stopped:
                            raise RuntimeError('模型连接已中断，请重新加载。')
            finally:
                SLOT.release()
        except (BrokenPipeError, ConnectionResetError):
            if 'key' in locals() and key:
                RESIDENT.cancel(key)
        except (ValueError, TypeError, RuntimeError, OSError, GenerationStopped) as error:
            message = '生成已停止。' if isinstance(error,GenerationStopped) else str(error)
            if streaming:
                self.emit({'error':{'message':message}})
            else:
                self.reply(409 if isinstance(error,GenerationStopped) else 400 if isinstance(error,(ValueError,TypeError)) else 503, {'error':{'message':message}})
        finally:
            if streaming:
                self.close_connection = True

if __name__ == '__main__':
    ThreadingHTTPServer(('127.0.0.1',8083),Handler).serve_forever()
