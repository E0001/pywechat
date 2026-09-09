'''pywxwork 消息发送:坐标+剪贴板自动化(企业微信 UIA 树不暴露,此为唯一可行 UI 路线)'''
import subprocess
import time

import pyautogui

from . import Tools
from .Config import globalConfig


def _send_key():
    '''按当前设置按下"发送"键'''
    if globalConfig.enter_to_send:
        pyautogui.press('enter')
    else:
        pyautogui.hotkey('ctrl', 'enter')


def open_chat(group_name: str, search_wait: float = None):
    '''通过全局搜索打开指定群的聊天窗口(Ctrl+F → 粘贴 → Enter 第一个结果)'''
    hwnd, _ = Tools.find_wxwork_window()
    if not hwnd:
        raise RuntimeError('未找到企业微信主窗口(WeWorkWindow),请确认已登录')
    Tools.activate_window(hwnd)

    wait = search_wait or globalConfig.search_wait
    pyautogui.hotkey('ctrl', 'f')      # 全局搜索
    time.sleep(0.6)
    Tools.copy_to_clipboard(group_name)
    pyautogui.hotkey('ctrl', 'v')
    time.sleep(wait)                   # 等待搜索结果浮层出现
    pyautogui.press('enter')           # 进入第一个(最佳匹配)结果
    time.sleep(1.2)
    return hwnd


def send_messages_to_group(group_name: str, messages: list[str], send_delay: float = None,
                           clear: bool = False, close_wxwork: bool = None):
    '''
    向指定群发送多条文本消息
    :param group_name: 群聊名称(需与搜索结果精确匹配,建议含独特关键词)
    :param messages: 文本消息列表
    :param send_delay: 每条间隔秒数,默认取 GlobalConfig.send_delay
    :param clear: 发送前是否清空输入框(Ctrl+A+Delete)
    :param close_wxwork: 完成后是否关闭企业微信,默认取 GlobalConfig.close_wxwork
    运行期间不要动键盘鼠标。
    '''
    delay = send_delay or globalConfig.send_delay
    close = globalConfig.close_wxwork if close_wxwork is None else close_wxwork

    hwnd = open_chat(group_name)
    Tools.click_input_box(hwnd)

    if clear:
        pyautogui.hotkey('ctrl', 'a')
        pyautogui.press('delete')
        time.sleep(0.2)

    for msg in messages:
        Tools.copy_to_clipboard(msg)
        pyautogui.hotkey('ctrl', 'v')
        time.sleep(0.3)
        _send_key()
        time.sleep(delay)

    if close:
        subprocess.run(['taskkill', '/IM', 'WXWork.exe', '/F'], capture_output=True)
