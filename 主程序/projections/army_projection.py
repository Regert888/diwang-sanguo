"""
部队数据投影 - 将部队业务数据转换为 API 响应格式
"""
from typing import Dict, List
import time


class ArmyProjection:
    """部队数据投影"""

    @staticmethod
    def project_army_list(armies: List[Dict]) -> Dict:
        """投影部队列表"""
        return {
            "armies": [
                ArmyProjection._project_army(army) for army in armies
            ],
            "count": len(armies)
        }

    @staticmethod
    def project_army_detail(army: Dict) -> Dict:
        """投影部队详细信息"""
        base_info = ArmyProjection._project_army(army)

        # 添加更多详细信息
        if army.get("march_data"):
            base_info["march_progress"] = ArmyProjection._calculate_march_progress(army)

        return base_info

    @staticmethod
    def _project_army(army: Dict) -> Dict:
        """投影单个部队基本信息"""
        return {
            "army_id": army.get("army_id"),
            "player_id": army.get("player_id"),
            "general_id": army.get("general_id"),
            "troops": army.get("troops", {}),
            "position": army.get("position", {}),
            "status": army.get("status", "idle"),
            "march_data": army.get("march_data"),
            "created_at": army.get("created_at")
        }

    @staticmethod
    def _calculate_march_progress(army: Dict) -> Dict:
        """计算行军进度"""
        march_data = army.get("march_data")
        if not march_data:
            return {}

        current_time = int(time.time())
        arrival_time = march_data.get("arrival_time", 0)

        return {
            "remaining_seconds": max(0, arrival_time - current_time),
            "target": march_data.get("target", {}),
            "is_arrived": current_time >= arrival_time
        }
