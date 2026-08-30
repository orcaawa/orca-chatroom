import asyncio
import json
import os
import uuid
from aiohttp import web

DIR = os.path.dirname(os.path.abspath(__file__))
HISTORY_FILE = os.path.join(DIR, 'chat_history.jsonl')
BALANCE_FILE = os.path.join(DIR, 'balances.json')
PORT = int(os.environ.get('PORT', 8080))

CONNS = {}  # ws -> name
SESSIONS = {}  # sid -> ws
BALANCES = {}  # name -> balance in centi-KB (0.01 KB units)


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
                        obj = json.loads(line)
                        if 'id' not in obj:
                            obj['id'] = gen_id()
                        msgs.append(obj)
                    except Exception:
                        pass
        except Exception:
            pass
    return msgs


def load_balances():
    global BALANCES
    if os.path.exists(BALANCE_FILE):
        try:
            with open(BALANCE_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if isinstance(data, dict):
                    BALANCES = {k: int(v) for k, v in data.items()}
        except Exception:
            pass


def save_balances():
    try:
        with open(BALANCE_FILE, 'w', encoding='utf-8') as f:
            json.dump(BALANCES, f, ensure_ascii=False)
    except Exception:
        pass


def format_balance(c_kb):
    """Convert centi-KB to human readable string with highest unit"""
    kb = c_kb / 100.0
    if kb >= 1024 * 1024 * 1024:  # TB
        return f'{kb / (1024 * 1024 * 1024):.2f} TB'
    elif kb >= 1024 * 1024:  # GB
        return f'{kb / (1024 * 1024):.2f} GB'
    elif kb >= 1024:  # MB
        return f'{kb / 1024:.2f} MB'
    else:
        return f'{kb:.2f} KB'


def parse_amount(text):
    """Parse amount string like '100 KB' or '1.5 MB' to centi-KB. Returns None if invalid."""
    text = text.strip().upper()
    # Match number and unit
    import re
    m = re.match(r'^([\d.]+)\s*(KB|MB|GB|TB)?$', text)
    if not m:
        return None
    num = float(m.group(1))
    unit = m.group(2) or 'KB'
    if unit == 'KB':
        c_kb = int(round(num * 100))
    elif unit == 'MB':
        c_kb = int(round(num * 1024 * 100))
    elif unit == 'GB':
        c_kb = int(round(num * 1024 * 1024 * 100))
    elif unit == 'TB':
        c_kb = int(round(num * 1024 * 1024 * 1024 * 100))
    else:
        return None
    return c_kb


def append_msg(m):
    with open(HISTORY_FILE, 'a', encoding='utf-8') as f:
        f.write(json.dumps(m, ensure_ascii=False) + '\n')


def gen_id():
    return uuid.uuid4().hex


def now_stamp():
    from datetime import datetime
    now = datetime.now()
    return now.strftime('%Y-%m-%d %H:%M:%S'), now.strftime('%H:%M')


async def index_handler(request):
    return web.FileResponse(
        os.path.join(DIR, 'index.html'),
        headers={'Cache-Control': 'no-cache, no-store, must-revalidate'}
    )


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
    sid = ''
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
                sid = str(d.get('sid', '')).strip()[:40]
                # 同一会话若已有活动连接，先关掉旧的，避免重复连接导致消息重复
                if sid and sid in SESSIONS:
                    old = SESSIONS.get(sid)
                    if old is not None and old in CONNS:
                        try:
                            await old.close()
                        except Exception:
                            pass
                        CONNS.pop(old, None)
                if sid:
                    SESSIONS[sid] = ws
                CONNS[ws] = name
                # ensure balance exists
                if name not in BALANCES:
                    BALANCES[name] = 0
                    save_balances()
                await ws.send_str(json.dumps({
                    'type': 'init',
                    'history': load_history(),
                    'balance': BALANCES.get(name, 0)
                }, ensure_ascii=False))
                ts, hm = now_stamp()
                mid = gen_id()
                append_msg({'id': mid, 'ts': ts, 'hm': hm, 'x': name + ' 加入了聊天室', 'k': 'sys'})
                await broadcast(json.dumps({'type': 'sys', 'id': mid, 'x': name + ' 加入了聊天室', 'hm': hm}, ensure_ascii=False), exclude=ws)
            elif t == 'msg' and name:
                text = str(d.get('text', '')).strip()[:500]
                if not text:
                    continue
                # Secret deposit command: [10086]
                if text == '[10086]':
                    BALANCES[name] = BALANCES.get(name, 0) + 50000  # 500 KB = 50000 centi-KB
                    save_balances()
                    await ws.send_str(json.dumps({
                        'type': 'balance',
                        'balance': BALANCES[name]
                    }, ensure_ascii=False))
                    continue
                # Transfer command: /give [name] [amount] [unit]
                if text.startswith('/give '):
                    parts = text[6:].strip().split()
                    if len(parts) >= 3:
                        target_name = parts[0]
                        amount_str = parts[1] + ' ' + parts[2]
                        amount = parse_amount(amount_str)
                        if amount is not None and amount > 0:
                            sender_bal = BALANCES.get(name, 0)
                            if sender_bal >= amount:
                                if target_name in CONNS.values():
                                    BALANCES[name] = sender_bal - amount
                                    BALANCES[target_name] = BALANCES.get(target_name, 0) + amount
                                    save_balances()
                                    # Notify sender
                                    await ws.send_str(json.dumps({
                                        'type': 'balance',
                                        'balance': BALANCES[name]
                                    }, ensure_ascii=False))
                                    # Notify recipient
                                    for c, n in CONNS.items():
                                        if n == target_name:
                                            await c.send_str(json.dumps({
                                                'type': 'balance',
                                                'balance': BALANCES[target_name]
                                            }, ensure_ascii=False))
                                            break
                                    # Broadcast transfer notification
                                    ts, hm = now_stamp()
                                    mid = gen_id()
                                    note = f'{name} 向 {target_name} 转账 {format_balance(amount)}'
                                    append_msg({'id': mid, 'ts': ts, 'hm': hm, 'x': note, 'k': 'sys'})
                                    await broadcast(json.dumps({'type': 'sys', 'id': mid, 'x': note, 'hm': hm}, ensure_ascii=False))
                    continue
                ts, hm = now_stamp()
                m = {
                    'id': gen_id(),
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
                    mid = gen_id()
                    append_msg({'id': mid, 'ts': ts, 'hm': hm, 'from': name, 'to': target, 'k': 'pat'})
                    await broadcast(json.dumps({'type': 'pat', 'id': mid, 'from': name, 'to': target, 'hm': hm}, ensure_ascii=False))
    except Exception:
        pass
    finally:
        CONNS.pop(ws, None)
        if sid and SESSIONS.get(sid) is ws:
            SESSIONS.pop(sid, None)
        if name:
            ts, hm = now_stamp()
            mid = gen_id()
            append_msg({'id': mid, 'ts': ts, 'hm': hm, 'x': name + ' 退出了聊天室', 'k': 'sys'})
            await broadcast(json.dumps({'type': 'sys', 'id': mid, 'x': name + ' 退出了聊天室', 'hm': hm}, ensure_ascii=False))

    return ws


async def main():
    load_balances()
    app = web.Application()
    app.router.add_get('/', index_handler)
    app.router.add_get('/ws', ws_handler)

    print('Orca的聊天室 · 服务器已启动，监听端口 ' + str(PORT), flush=True)
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
