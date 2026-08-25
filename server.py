import asyncio
import json
import os
from aiohttp import web

DIR = os.path.dirname(os.path.abspath(__file__))
HISTORY_FILE = os.path.join(DIR, 'chat_history.jsonl')
PORT = int(os.environ.get('PORT', 8080))

CONNS = {}  # ws -> name


def load_history():
    msgs = []
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        msgs.append(json.loads(line))
                    except Exception:
                        pass
        except Exception:
            pass
    return msgs


def append_msg(m):
    with open(HISTORY_FILE, 'a', encoding='utf-8') as f:
        f.write(json.dumps(m, ensure_ascii=False) + '\n')


def now_stamp():
    from datetime import datetime
    now = datetime.now()
    return now.strftime('%Y-%m-%d %H:%M:%S'), now.strftime('%H:%M')


async def index_handler(request):
    return web.FileResponse(os.path.join(DIR, 'index.html'))


async def broadcast(text, exclude=None):
    dead = []
    for c in list(CONNS.keys()):
        if c is exclude or not CONNS.get(c):
            continue
        try:
            await c.send_str(text)
        except Exception:
            dead.append(c)
    for c in dead:
        CONNS.pop(c, None)


async def ws_handler(request):
    ws = web.WebSocketResponse()
    await ws.prepare(request)

    CONNS[ws] = ''
    name = ''
    try:
        async for msg in ws:
            if msg.type != web.WSMsgType.TEXT:
                continue
            try:
                d = json.loads(msg.data)
            except Exception:
                continue
            t = d.get('type')
            if t == 'join':
                name = str(d.get('name', '')).strip()[:20] or '匿名'
                CONNS[ws] = name
                await ws.send_str(json.dumps({
                    'type': 'init',
                    'history': load_history()
                }, ensure_ascii=False))
                ts, hm = now_stamp()
                append_msg({'ts': ts, 'hm': hm, 'x': name + ' 加入了聊天室', 'k': 'sys'})
                await broadcast(json.dumps({'type': 'sys', 'x': name + ' 加入了聊天室', 'hm': hm}, ensure_ascii=False), exclude=ws)
            elif t == 'msg' and name:
                text = str(d.get('text', '')).strip()[:500]
                if not text:
                    continue
                ts, hm = now_stamp()
                m = {
                    'ts': ts,
                    'hm': hm,
                    'n': name,
                    'x': text,
                }
                append_msg(m)
                await broadcast(json.dumps({'type': 'new', 'msg': m}, ensure_ascii=False))
            elif t == 'pat' and name:
                target = str(d.get('target', '')).strip()[:20]
                if target and target in CONNS.values():
                    ts, hm = now_stamp()
                    append_msg({'ts': ts, 'hm': hm, 'from': name, 'to': target, 'k': 'pat'})
                    await broadcast(json.dumps({'type': 'pat', 'from': name, 'to': target, 'hm': hm}, ensure_ascii=False))
    except Exception:
        pass
    finally:
        CONNS.pop(ws, None)
        if name:
            ts, hm = now_stamp()
            append_msg({'ts': ts, 'hm': hm, 'x': name + ' 退出了聊天室', 'k': 'sys'})
            await broadcast(json.dumps({'type': 'sys', 'x': name + ' 退出了聊天室', 'hm': hm}, ensure_ascii=False))

    return ws


async def main():
    app = web.Application()
    app.router.add_get('/', index_handler)
    app.router.add_get('/ws', ws_handler)

    print('Orca的本地聊天室 · 服务器已启动，监听端口 ' + str(PORT), flush=True)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', PORT)
    await site.start()

    await asyncio.Future()


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print('\n已停止')
    except Exception as e:
        print('\n出错: ' + str(e))
        import traceback
        traceback.print_exc()
