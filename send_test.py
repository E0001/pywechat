'''
UI 自动化发送消息验证脚本
发送目标: 文件传输助手(只发给自己,零风险)
运行期间请不要动键盘鼠标(pyautogui 会接管输入)
'''
from pyweixin import Messages
from pyweixin.Config import GlobalConfig

# 任务结束不要关闭微信
GlobalConfig.close_weixin = False

Messages.send_messages_to_friend(
    friend='文件传输助手',
    messages=['pywechat UI 自动化测试消息', '如果你能看到这条,说明发送链路正常 ✅'],
    close_weixin=False,
)
print('发送完成')
