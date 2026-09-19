"""
玩家数据投影 - 将玩家业务数据转换为 API 响应格式
"""
from typing import Dict, List, Optional


class PlayerProjection:
    """玩家数据投影"""

    @staticmethod
    def project_player_info(player: Dict) -> Dict:
        """投影玩家基本信息"""
        return {
            "player_id": player.get("player_id"),
            "name": player.get("name"),
            "level": player.get("level"),
            "exp": player.get("exp"),
            "resources": player.get("resources", {})
        }

    @staticmethod
    def project_resources(player: Dict) -> Dict:
        """投影玩家资源"""
        resources = player.get("resources", {})
        return {
            "gold": resources.get("gold", 0),
            "food": resources.get("food", 0),
            "wood": resources.get("wood", 0),
            "iron": resources.get("iron", 0),
            "stone": resources.get("stone", 0)
        }

    @staticmethod
    def project_generals_list(generals: List[Dict]) -> Dict:
        """投影武将列表"""
        return {
            "generals": [
                PlayerProjection._project_general(g) for g in generals
            ],
            "count": len(generals)
        }

    @staticmethod
    def _project_general(general: Dict) -> Dict:
        """投影单个武将信息"""
        return {
            "id": general.get("id"),
            "name": general.get("name"),
            "level": general.get("level", 1),
            "attack": general.get("attack", 0),
            "defense": general.get("defense", 0),
            "intelligence": general.get("intelligence", 0)
        }
