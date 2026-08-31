# -*- coding: utf-8 -*-
"""diag_alias_discovery — 验证微信号两段式发现: 搜微信号读出联系人当前显示名"""
import sys
for _s in (sys.stdout, sys.stderr):
    if not _s.isatty() and hasattr(_s, 'reconfigure'):
        _s.reconfigure(encoding='utf-8')
sys.path.insert(0, r'C:\Users\kk\Desktop\xx\pywechat')
import wx_listener as L
L.Cfg.aliases = {'wxid_xerhivsxr9u622': 'crypto_kang', 'litiantianss': 'litiantianss'}
for wxid, alias in [('wxid_xerhivsxr9u622', 'crypto_kang'), ('litiantianss', 'litiantianss')]:
    print(f'{alias!r} -> {L._discover_name_by_alias(alias)!r}')
