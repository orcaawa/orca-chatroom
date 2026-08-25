# -*- coding: utf-8 -*-
"""Orca的本地聊天室 - 聊天记录清理工具（请先关闭服务器后运行）"""
import json
import os
import socket
from datetime import datetime

DIR = os.path.dirname(os.path.abspath(__file__))
FILE = os.path.join(DIR, 'chat_history.jsonl')
CHECK_PORTS = [8080, 8767]


def server_running():
    for p in CHECK_PORTS:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(0.3)
        try:
            s.connect(('127.0.0.1', p))
            s.close()
            return True
        except Exception:
            try:
                s.close()
            except Exception:
                pass
    return False


def load():
    if not os.path.exists(FILE):
        return []
    out = []
    with open(FILE, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except Exception:
                pass
    return out


def save(msgs):
    with open(FILE, 'w', encoding='utf-8') as f:
        for m in msgs:
            f.write(json.dumps(m, ensure_ascii=False) + '\n')


def main():
    print('=' * 40)
    print('   Orca的本地聊天室 · 记录清理')
    print('=' * 40)

    if server_running():
        print('\n[!] 检测到服务器正在运行，请先关闭服务器窗口，再运行本脚本。')
        input('按回车键退出...')
        return

    msgs = load()
    total = len(msgs)
    if total == 0:
        print('\n当前没有聊天记录。')
        input('按回车键退出...')
        return

    while True:
        print('\n当前共 %d 条记录' % total)
        print('-' * 40)
        print(' 1. 清空所有')
        print(' 2. 清空最早的 N 条')
        print(' 3. 清空最早的 N% 条')
        print(' 4. 清空 xx年xx月xx日xx时 之前的')
        print(' 0. 退出')
        c = input('\n请选择: ').strip()

        will = 0
        keep = msgs

        if c == '0':
            break
        elif c == '1':
            keep = []
            will = total
        elif c == '2':
            n = input('删除最早多少条: ').strip()
            if not n.isdigit() or int(n) < 1 or int(n) > total:
                print('无效数字（范围 1~%d）' % total)
                continue
            n = int(n)
            keep = msgs[n:]
            will = n
        elif c == '3':
            p = input('删除最早百分之多少 (1~100): ').strip()
            try:
                p = float(p)
            except Exception:
                print('无效数字')
                continue
            if p <= 0 or p > 100:
                print('超出范围')
                continue
            n = round(total * p / 100)
            keep = msgs[n:]
            will = n
        elif c == '4':
            try:
                y = int(input('年 (如 2026): '))
                mo = int(input('月 (1~12): '))
                d = int(input('日 (1~31): '))
                h = int(input('时 (0~23): '))
                limit = '%04d-%02d-%02d %02d:00:00' % (y, mo, d, h)
                datetime.strptime(limit, '%Y-%m-%d %H:%M:%S')
            except Exception:
                print('日期无效')
                continue
            keep = [m for m in msgs if m.get('ts', '') >= limit]
            will = total - len(keep)
        else:
            continue

        if will == 0:
            print('\n没有符合条件的记录。')
            continue

        left = total - will
        ok = input('\n将删除 %d 条，剩余 %d 条，确认？(y/n): ' % (will, left)).strip().lower()
        if ok == 'y':
            save(keep)
            print('已完成。')
            msgs = keep
            total = len(msgs)
            if total == 0:
                print('记录已全部清空。')
                break
        else:
            print('已取消。')

    input('\n按回车键退出...')


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        pass
