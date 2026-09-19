"""
地块数据投影 - 将地块业务数据转换为 API 响应格式
"""
from typing import Dict, List


class TileProjection:
    """地块数据投影"""

    @staticmethod
    def project_tile_list(tiles: List[Dict]) -> Dict:
        """投影地块列表"""
        return {
            "tiles": [
                TileProjection._project_tile(tile) for tile in tiles
            ],
            "count": len(tiles)
        }

    @staticmethod
    def project_tile_detail(tile: Dict) -> Dict:
        """投影地块详细信息"""
        return TileProjection._project_tile(tile)

    @staticmethod
    def _project_tile(tile: Dict) -> Dict:
        """投影单个地块信息"""
        return {
            "tile_id": tile.get("tile_id"),
            "x": tile.get("x"),
            "y": tile.get("y"),
            "type": tile.get("type"),
            "level": tile.get("level"),
            "owner_id": tile.get("owner_id"),
            "resources": tile.get("resources", {}),
            "defense": tile.get("defense", 0)
        }

    @staticmethod
    def project_map_area(tiles: List[Dict], center_x: int, center_y: int, radius: int) -> Dict:
        """投影地图区域数据"""
        return {
            "center": {"x": center_x, "y": center_y},
            "radius": radius,
            "tiles": [
                TileProjection._project_tile(tile) for tile in tiles
            ],
            "count": len(tiles)
        }
