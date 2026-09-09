'''列出 WXWork.exe 加载的 UI/框架相关 DLL'''
import os
import psutil

pid = next(p.pid for p in psutil.process_iter(['name'])
           if p.info['name'] and p.info['name'].lower() == 'wxwork.exe')
p = psutil.Process(pid)
print(f'WXWork.exe PID={pid}')
dlls = sorted({m.path for m in p.memory_maps() if m.path.lower().endswith('.dll')})
for d in dlls:
    base = os.path.basename(d).lower()
    if any(k in base for k in ('perry', 'wxwork', 'wework', 'mmui', 'common', 'util', 'business', 'frame')):
        try:
            sz = os.path.getsize(d) / 1048576
            print(f'{sz:8.1f}MB  {d}')
        except OSError:
            print(f'{"?":>8}     {d}')
print('--- total dlls:', len(dlls))
