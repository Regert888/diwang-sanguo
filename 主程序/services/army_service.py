"""
部队服务 - 处理部队相关业务逻辑
"""
from core.db_manager import db
from typing import Dict, List, Optional
import time


class ArmyService:
    """部队服务"""

    def get_army(self, army_id: str) -> Optional[Dict]:
        """获取部队信息"""
        return db.get_army(army_id)

    def get_player_armies(self, player_id: str) -> List[Dict]:
        """获取玩家的所有部队（投影层）"""
        from app.presenters import build_troops
        from services.player_service import PlayerService

        player_service = PlayerService()
        player = player_service.get_player(player_id)

        # 从原子数据投影
        伤兵表 = player.get("_伤兵表", {})
        兵种名表 = player.get("_兵种名表", {})

        return build_troops(伤兵表, 兵种名表)

    def create_army(self, player_id: str, general_id: str, troops: Dict,
                    start_x: int, start_y: int) -> Dict:
        """创建部队"""
        army_id = f"army_{player_id}_{int(time.time() * 1000)}"

        army = {
            "army_id": army_id,
            "player_id": player_id,
            "general_id": general_id,
            "troops": troops,  # {"infantry": 100, "cavalry": 50, ...}
            "position": {"x": start_x, "y": start_y},
            "status": "idle",  # idle, marching, fighting
            "march_data": None,
            "created_at": int(time.time())
        }

        db.save_army(army_id, army)
        return army

    def move_army(self, army_id: str, target_x: int, target_y: int) -> bool:
        """移动部队"""
        army = db.get_army(army_id)
        if not army:
            return False

        current_pos = army["position"]
        distance = abs(target_x - current_pos["x"]) + abs(target_y - current_pos["y"])
        arrival_time = int(time.time()) + distance * 10  # 每格10秒

        army["status"] = "marching"
        army["march_data"] = {
            "target": {"x": target_x, "y": target_y},
            "arrival_time": arrival_time
        }

        db.save_army(army_id, army)
        return True

    def update_army_position(self, army_id: str):
        """更新部队位置（检查是否到达目的地）"""
        army = db.get_army(army_id)
        if not army or army["status"] != "marching":
            return

        march_data = army["march_data"]
        if time.time() >= march_data["arrival_time"]:
            # 到达目的地
            army["position"] = march_data["target"]
            army["status"] = "idle"
            army["march_data"] = None
            db.save_army(army_id, army)

    def disband_army(self, army_id: str) -> bool:
        """解散部队"""
        army = db.get_army(army_id)
        if not army:
            return False

        db.delete_army(army_id)
        return True
