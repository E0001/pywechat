'''pywxwork 全局配置(仿 pyweixin.Config)'''


class GlobalConfig:
    '''全局配置单例,在导入 Messages 前可修改字段'''

    def __init__(self):
        self.close_wxwork: bool = True          # 任务完成后是否关闭企业微信
        self.maximize_window: bool = True       # 操作前是否最大化窗口
        self.send_delay: float = 1.2            # 每条消息发送间隔(秒)
        self.search_wait: float = 2.0           # 搜索结果等待(秒)
        self.enter_to_send: bool = True         # 企业微信设置为 Enter 发送(默认);Ctrl+Enter 模式改 False
        self.input_box_x_ratio: float = 0.55    # 输入框点击点:窗口宽度比例
        self.input_box_y_offset: int = 70       # 输入框点击点:距窗口底部像素


globalConfig = GlobalConfig()
