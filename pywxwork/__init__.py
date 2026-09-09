'''pywxwork: 企业微信(WeCom)桌面端自动化工具

企业微信 Perry 框架不暴露 UIA 树(无读屏器检测通道),
故采用 窗口坐标 + 剪贴板 + 键盘模拟 的自动化路线。

用法:
    from pywxwork import Messages
    from pywxwork.Config import GlobalConfig
    GlobalConfig.close_wxwork = False
    Messages.send_messages_to_group('群名', ['消息1', '消息2'])
'''
from .Config import GlobalConfig, globalConfig
from . import Tools, Messages

__all__ = ['Tools', 'Messages', 'Config', 'GlobalConfig']
