"""
地块服务 - 处理地块相关业务逻辑
"""
from core.db_manager import db
from typing import Dict, List, Optional


class TileService:
    """地块服务"""

    # 地块类型
    TILE_TYPES = {
        "plain": {"name": "平原", "defense_bonus": 0},
        "forest": {"name": "森林", "defense_bonus": 10},
        "mountain": {"name": "山地", "defense_bonus": 20},
        "water": {"name": "水域", "defense_bonus": -10},
        "city": {"name": "城市", "defense_bonus": 30}
    }

    def get_tile(self, x: int, y: int) -> Dict:
        """获取地块信息"""
        tile = db.get_tile(x, y)
        if not tile:
            # 创建默认地块
            tile = self._create_default_tile(x, y)
            db.save_tile(x, y, tile)

        tile['x'] = x
        tile['y'] = y
        return tile

    def _create_default_tile(self, x: int, y: int) -> Dict:
        """创建默认地块"""
        # 简单的地形生成逻辑
        tile_type = "plain"
        if (x + y) % 5 == 0:
            tile_type = "forest"
        elif (x * y) % 7 == 0:
            tile_type = "mountain"

        return {
            "type": tile_type,
            "owner": None,
            "building": None,
            "resources": {}
        }

    def get_tiles_in_range(self, center_x: int, center_y: int, radius: int) -> List[Dict]:
        """获取范围内的地块"""
        return db.get_tiles_in_range(center_x, center_y, radius)

    def occupy_tile(self, x: int, y: int, player_id: str) -> bool:
        """占领地块"""
        tile = self.get_tile(x, y)
        tile["owner"] = player_id
        db.save_tile(x, y, tile)
        return True

    def build_on_tile(self, x: int, y: int, building_type: str) -> bool:
        """在地块上建造建筑"""
        tile = self.get_tile(x, y)
        tile["building"] = {
            "type": building_type,
            "level": 1
        }
        db.save_tile(x, y, tile)
        return True
