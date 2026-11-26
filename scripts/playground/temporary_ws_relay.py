import asyncio, json, urllib.request, urllib.error
from websockets.asyncio.server import serve

ALLOWED = {'https://msl-kanban.pages.dev', 'https://msl-kanban.vercel.app'}
QWEN35 = 'Qwen3.5 · 3001（临时）'
async def handle(ws):
    if ws.request.headers.get('Origin') not in ALLOWED:
        await ws.close(1008, 'Origin not allowed')
        return
    try:
        msg = json.loads(await asyncio.wait_for(ws.recv(), 10))
        path = msg.get('path')
        if path not in ('/v1/models', '/v1/chat/completions', '/v1/chat/cancel', '/v1/model/load', '/v1/model/status', '/v1/model/unload'):
            raise ValueError('Unsupported path')
        body = msg.get('body')
        if path.endswith('completions') and not isinstance(body, dict):
            raise ValueError('Invalid body')
        payload = json.dumps(body).encode() if body is not None else None
        port = 8083 if isinstance(body, dict) and body.get('model') == QWEN35 else 8081
        req = urllib.request.Request(f'http://127.0.0.1:{port}' + path, data=payload,
            headers={'Content-Type':'application/json', 'X-Phone-Type':msg.get('phone','mate80-pro')})
        queue = asyncio.Queue(maxsize=1024)
        loop = asyncio.get_running_loop()
        def put(item):
            asyncio.run_coroutine_threadsafe(queue.put(item), loop).result(timeout=10)
        def forward():
            try:
                with urllib.request.urlopen(req, timeout=930) as response:
                    put({'status':response.status, 'content_type':response.headers.get('Content-Type','')})
                    if path == '/v1/models':
                        models = json.load(response)
                        models['data'].append({'object':'model', 'id':QWEN35, 'owned_by':'mslite', 'created':0})
                        put({'data':json.dumps(models, ensure_ascii=False)})
                    else:
                        for line in response:
                            put({'data':line.decode('utf-8')})
                    put({'end':True})
                    return
            except urllib.error.HTTPError as error:
                put({'status':error.code, 'content_type':'application/json'})
                put({'data':error.read().decode('utf-8')})
                put({'end':True})
            except Exception:
                put({'error':'模型服务连接失败'})
        task = asyncio.create_task(asyncio.to_thread(forward))
        while True:
            event = await asyncio.wait_for(queue.get(), 935)
            await ws.send(json.dumps(event, ensure_ascii=False))
            if event.get('end') or event.get('error'):
                break
        await task
    except (ValueError, TypeError, json.JSONDecodeError):
        await ws.close(1008, 'Invalid request')
    except (TimeoutError, ConnectionError):
        await ws.close(1011, 'Request failed')

async def main():
    async with serve(handle, '127.0.0.1', 18083, max_size=65536, ping_interval=20):
        await asyncio.Future()
asyncio.run(main())
