# -*- coding: utf-8 -*-
'''诊断: 分别枚举「小康」独立聊天小窗 与 主窗口聊天区 的按钮/元素，找语音通话入口。
输出写 UTF-8 文件避免控制台乱码。只读不点击。'''
import sys
from pywinauto import Desktop

OUT = open('diag_voice2_out.txt', 'w', encoding='utf-8')

desktop = Desktop(backend='uia')


def dump(window, label):
    OUT.write(f'===== {label} class={window.class_name()} title={window.window_text()!r} =====\n')
    try:
        btns = window.descendants(control_type='Button')
    except Exception as e:
        OUT.write(f'枚举按钮失败: {e}\n')
        return
    OUT.write(f'按钮总数: {len(btns)}\n')
    for b in btns:
        t = (b.window_text() or '').strip()
        auto_id = ''
        try:
            auto_id = b.element_info.automation_id or ''
        except Exception:
            pass
        OUT.write(f'  Button: {t!r} auto_id={auto_id!r}\n')
    # 关键词元素（含非 Button 控件）
    OUT.write('--- 含 语音/视频/通话/电话 关键词的元素 ---\n')
    try:
        for elem in window.descendants():
            try:
                t = (elem.window_text() or '').strip()
            except Exception:
                continue
            if any(k in t for k in ('语音', '视频', '通话', '电话')):
                OUT.write(f'  {elem.control_type()}: {t!r}\n')
    except Exception as e:
        OUT.write(f'关键词枚举失败: {e}\n')
    OUT.write('\n')


# 1) 独立小窗（listener 已开着小康的小窗，直接复用，不导航）
wins = desktop.windows()
found = 0
for w in wins:
    try:
        if w.class_name() == 'mmui::ChatSingleWindow' and w.window_text() == '小康':
            dump(w, '独立小窗-小康')
            found += 1
    except Exception:
        continue
if not found:
    OUT.write('!! 未找到「小康」独立小窗\n\n')

# 2) 主窗口聊天区
for w in wins:
    try:
        if w.class_name() == 'mmui::MainWindow':
            dump(w, '主窗口')
    except Exception:
        continue

OUT.close()
print('done')
