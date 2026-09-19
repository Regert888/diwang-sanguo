"""
战斗服务 - 处理战斗相关业务逻辑
"""
from typing import Dict, Optional
import random


class BattleService:
    """战斗服务"""

    def calculate_battle(self, attacker: Dict, defender: Dict) -> Dict:
        """计算战斗结果

        Args:
            attacker: 攻击方数据 {"troops": {...}, "general": {...}}
            defender: 防守方数据 {"troops": {...}, "general": {...}, "terrain_bonus": 0}

        Returns:
            战斗结果 {"winner": "attacker/defender", "casualties": {...}}
        """
        # 计算战力
        attacker_power = self._calculate_power(attacker)
        defender_power = self._calculate_power(defender)

        # 地形加成
        terrain_bonus = defender.get("terrain_bonus", 0)
        defender_power = defender_power * (1 + terrain_bonus / 100)

        # 随机因素
        attacker_power *= random.uniform(0.9, 1.1)
        defender_power *= random.uniform(0.9, 1.1)

        # 判断胜负
        if attacker_power > defender_power:
            winner = "attacker"
            casualties = self._calculate_casualties(attacker, defender, 0.3, 0.7)
        else:
            winner = "defender"
            casualties = self._calculate_casualties(attacker, defender, 0.7, 0.3)

        return {
            "winner": winner,
            "casualties": casualties,
            "attacker_power": int(attacker_power),
            "defender_power": int(defender_power)
        }

    def _calculate_power(self, army: Dict) -> float:
        """计算军队战力"""
        troops = army.get("troops", {})
        power = 0

        # 不同兵种的战力值
        troop_power = {
            "infantry": 10,
            "cavalry": 15,
            "archer": 12,
            "siege": 8
        }

        for troop_type, count in troops.items():
            power += count * troop_power.get(troop_type, 10)

        # 武将加成
        general = army.get("general", {})
        general_bonus = general.get("command", 0) * 10
        power += general_bonus

        return power

    def _calculate_casualties(self, attacker: Dict, defender: Dict,
                             attacker_loss_rate: float, defender_loss_rate: float) -> Dict:
        """计算伤亡"""
        attacker_troops = attacker.get("troops", {})
        defender_troops = defender.get("troops", {})

        attacker_casualties = {}
        defender_casualties = {}

        for troop_type, count in attacker_troops.items():
            loss = int(count * attacker_loss_rate * random.uniform(0.8, 1.2))
            attacker_casualties[troop_type] = min(loss, count)

        for troop_type, count in defender_troops.items():
            loss = int(count * defender_loss_rate * random.uniform(0.8, 1.2))
            defender_casualties[troop_type] = min(loss, count)

        return {
            "attacker": attacker_casualties,
            "defender": defender_casualties
        }
