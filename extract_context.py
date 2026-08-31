'''提取关键偏移周围的字符串上下文'''
import re

PATH = r'C:\Program Files (x86)\WXWork\WXWork.exe'
data = open(PATH, 'rb').read()

OFFSETS = [
    0xb72dc74,  # narrator
    0xb4f2e9d,  # nvda
    0xb827c08,  # nvda
    0xb6fa02c,  # clicfg
    0xb6fa050,  # clicfg
    0xac4d75d,  # accessibility
]

def show_ascii(off, span=160):
    lo, hi = max(0, off - span), min(len(data), off + span)
    chunk = data[lo:hi]
    found = re.findall(rb'[\x20-\x7e]{6,}', chunk)
    return [s.decode('ascii') for s in found]

def show_u16(off, span=160):
    lo, hi = max(0, off - span), min(len(data), off + span)
    chunk = data[lo:hi]
    found = re.findall(rb'(?:[\x20-\x7e]\x00){5,}', chunk)
    return [s.decode('utf-16-le') for s in found]

for off in OFFSETS:
    print(f'\n=== offset 0x{off:x} ===')
    for s in show_ascii(off):
        print(f'  A: {s}')
    for s in show_u16(off):
        print(f'  U: {s}')
