'''在 WXWork 二进制中搜索无障碍/读屏器相关字符串(ASCII + UTF-16LE)'''
import os

FILES = [
    r'C:\Program Files (x86)\WXWork\WXWork.exe',
    r'C:\Program Files (x86)\WXWork\5.0.9.6029\WXWorkResources.dll',
    r'C:\Program Files (x86)\WXWork\5.0.9.6029\WXWorkStrings.dll',
]

KEYWORDS = [
    'narrator', 'Narrator',
    'screenreader', 'screen_reader', 'ScreenReader',
    'nvda', 'NVDA', 'nvdahelper',
    'outhelper',
    'accessible', 'Accessible', 'accessibility', 'Accessibility',
    'a11y', 'A11y',
    'UIAutomation', 'UiaClients',
    'clicfg',
    'ScreenReaderRunning',
    'SPI_GETSCREENREADER',
]

for path in FILES:
    if not os.path.exists(path):
        print(f'[skip] {path} 不存在')
        continue
    size = os.path.getsize(path) / 1048576
    print(f'\n=== {path} ({size:.1f}MB) ===')
    data = open(path, 'rb').read()
    for kw in KEYWORDS:
        hits = []
        # ASCII
        off = data.find(kw.encode('ascii'))
        n_ascii = 0
        while off != -1 and n_ascii < 3:
            hits.append(f'ascii@0x{off:x}')
            n_ascii += 1
            off = data.find(kw.encode('ascii'), off + 1)
        # UTF-16LE
        off = data.find(kw.encode('utf-16-le'))
        n_utf = 0
        while off != -1 and n_utf < 3:
            hits.append(f'u16@0x{off:x}')
            n_utf += 1
            off = data.find(kw.encode('utf-16-le'), off + 1)
        # 统计总数
        total = data.count(kw.encode('ascii')) + data.count(kw.encode('utf-16-le'))
        if total:
            print(f'  {kw!r}: 总计 {total} 处  {", ".join(hits[:4])}')
