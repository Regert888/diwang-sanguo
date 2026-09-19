"""协议解析模块 —— 登录、武将、部队、山贼、副本"""

from .packets import *
from .login import (
    取区服列表, 匹配区服, 会话探活, 进入游戏,
    检查踢下线, KICK_OPS, KICK_MSG,
    enter_game, game_login
)
from .generals import (
    解析国家, 解析登录信息, 解析登录包武将,
    解析登录包完整, 解析武将列表
)
from .troop import (
    解析配兵应答, 解析部队实时, 格式化部队
)
from .thief import (
    解析山贼应答, 格式化山贼
)
from .dungeon import (
    解析副本应答
)

__all__ = [
    # packets
    "LOGIN_URL", "VALIDATE_URL", "CHANNEL_ID", "C_VERSION", "C_TYPE", "TARGET_ALL",
    "pack_packet", "unpack_packet",
    # login
    "取区服列表", "匹配区服", "会话探活", "进入游戏",
    "检查踢下线", "KICK_OPS", "KICK_MSG",
    "enter_game", "game_login",
    # generals
    "解析国家", "解析登录信息", "解析登录包武将",
    "解析登录包完整", "解析武将列表",
    # troop
    "解析配兵应答", "解析部队实时", "格式化部队",
    # thief
    "解析山贼应答", "格式化山贼",
    # dungeon
    "解析副本应答",
]
