"""
玩家服务 - 处理玩家相关业务逻辑
"""
from core.db_manager import db
from typing import Dict, List, Optional


class PlayerService:
    """玩家服务"""

    def get_player(self, player_id: str) -> Optional[Dict]:
        """获取玩家信息"""
        player = db.get_player(player_id)
        if not player:
            # 创建默认玩家数据
            player = self._create_default_player(player_id)
            db.save_player(player_id, player)
        return player

    def _create_default_player(self, player_id: str) -> Dict:
        """创建默认玩家数据"""
        return {
            "player_id": player_id,
            "name": f"玩家{player_id}",
            "level": 1,
            "exp": 0,
            "resources": {
                "gold": 10000,
                "food": 10000,
                "wood": 5000,
                "iron": 5000,
                "stone": 5000
            },
            # 原子数据（投影层需要）
            "_武将原始A4": [],
            "_部队表": {},
            "_伤兵表": {},
            "_兵种名表": {}
        }

    def get_resources(self, player_id: str) -> Dict:
        """获取玩家资源"""
        player = self.get_player(player_id)
        return player.get("resources", {})

    def get_generals(self, player_id: str) -> List[Dict]:
        """获取玩家武将列表（投影层）"""
        from app.presenters import build_generals
        player = self.get_player(player_id)

        # 从原子数据投影
        raw_a4 = player.get("_武将原始A4", [])
        部队表 = player.get("_部队表", {})
        兵种名表 = player.get("_兵种名表", {})

        return build_generals(raw_a4, 部队表, 兵种名表)

    def update_resources(self, player_id: str, resources: Dict):
        """更新玩家资源"""
        player = self.get_player(player_id)
        player["resources"].update(resources)
        db.save_player(player_id, player)

    def add_general(self, player_id: str, general: Dict):
        """添加武将"""
        player = self.get_player(player_id)
        player["generals"].append(general)
        db.save_player(player_id, player)
