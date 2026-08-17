'''
list_groups.py —— 导出当前登录微信的群聊名称
================================================

用于填写 wx_sender_config.json 中 targets 的 name（wxid→群名映射）。
在 wx_sender 部署机上运行（前置：NVDA 已运行 + 微信 UIA 已激活 + 已登录）。

用法:
    python list_groups.py          # 最近会话中的群聊（快，JSSZ/KXZJ 等活跃群都在里面）
    python list_groups.py --all    # 全部已加入群聊（群多时较慢）

输出对照模板的目标清单后，把群名填入 wx_sender_config.json 即可，无需重启服务。
'''

import sys

from pyweixin import Contacts
from pyweixin.Config import GlobalConfig

# 任务结束不关闭微信
GlobalConfig.close_weixin = False

# wx_sender_server.py 内 DEFAULT_CONFIG 的目标清单，便于人工对照
KNOWN_TARGETS = {
    '48123779466@chatroom': 'JSSZ 急速上涨',
    '43846025020@chatroom': 'KXZJ 快讯总结',
    '43258695223@chatroom': 'Thedefiant 交易所崩盘',
    '44177931368@chatroom': 'JYSZBJK 交易所指标监控',
    '44456629368@chatroom': 'Fangchengshi 方程式新闻',
    '50587746113@chatroom': 'Twitter 推特监控',
    '18743464752@chatroom': 'Aming 推特监控',
    '50603160956@chatroom': 'tgMoni AI 快讯',
    '49568875761@chatroom': 'FLJXGJH 封狼居胥冠军侯',
    'wxid_xerhivsxr9u6':    'Xiaokang 私聊',
}


def main():
    use_all = '--all' in sys.argv
    print('即将操作微信界面，请勿移动键鼠...')
    if use_all:
        print('[全量模式] 遍历所有已加入群聊（较慢）...')
        groups = Contacts.get_groups_info()
        items = [(g, '') for g in groups]
    else:
        print('[最近模式] 遍历最近会话群聊...')
        items = Contacts.get_recent_groups()

    print(f'\n共 {len(items)} 个群聊:')
    for item in items:
        # get_recent_groups 返回 (名称, 人数)；get_groups_info 补齐为 (名称, '')
        print(f'  {item[0]}  {item[1]}')

    print('\n请将以上群名对照填入 wx_sender_config.json 的 targets:')
    for wxid, desc in KNOWN_TARGETS.items():
        print(f'  "{wxid}": {{"name": "<填入群名>", "desc": "{desc}"}}')


if __name__ == '__main__':
    if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    main()
