"""
数据库管理器 - 提供数据访问接口
"""
import json
import os
from typing import Dict, List, Optional


class DatabaseManager:
    """数据库管理器"""

    def __init__(self, data_dir: str = "data"):
        """初始化数据库管理器

        Args:
            data_dir: 数据目录路径
        """
        self.data_dir = data_dir
        os.makedirs(data_dir, exist_ok=True)

        # 数据文件路径
        self.players_file = os.path.join(data_dir, "players.json")
        self.tiles_file = os.path.join(data_dir, "tiles.json")
        self.armies_file = os.path.join(data_dir, "armies.json")

        # 确保数据文件存在
        self._init_data_files()

    def _init_data_files(self):
        """初始化数据文件"""
        if not os.path.exists(self.players_file):
            self._save_json(self.players_file, {})

        if not os.path.exists(self.tiles_file):
            self._save_json(self.tiles_file, {})

        if not os.path.exists(self.armies_file):
            self._save_json(self.armies_file, {})

    def _load_json(self, filepath: str) -> Dict:
        """加载 JSON 文件"""
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def _save_json(self, filepath: str, data: Dict):
        """保存 JSON 文件"""
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    # ========== 玩家数据接口 ==========

    def get_player(self, player_id: str) -> Optional[Dict]:
        """获取玩家数据"""
        players = self._load_json(self.players_file)
        return players.get(player_id)

    def save_player(self, player_id: str, player_data: Dict):
        """保存玩家数据"""
        players = self._load_json(self.players_file)
        players[player_id] = player_data
        self._save_json(self.players_file, players)

    def get_all_players(self) -> Dict[str, Dict]:
        """获取所有玩家数据"""
        return self._load_json(self.players_file)

    # ========== 地块数据接口 ==========

    def get_tile(self, x: int, y: int) -> Optional[Dict]:
        """获取地块数据"""
        tiles = self._load_json(self.tiles_file)
        key = f"{x},{y}"
        return tiles.get(key)

    def save_tile(self, x: int, y: int, tile_data: Dict):
        """保存地块数据"""
        tiles = self._load_json(self.tiles_file)
        key = f"{x},{y}"
        tiles[key] = tile_data
        self._save_json(self.tiles_file, tiles)

    def get_tiles_in_range(self, center_x: int, center_y: int, radius: int) -> List[Dict]:
        """获取范围内的地块"""
        tiles = self._load_json(self.tiles_file)
        result = []

        for key, tile_data in tiles.items():
            x, y = map(int, key.split(','))
            distance = abs(x - center_x) + abs(y - center_y)
            if distance <= radius:
                tile_data['x'] = x
                tile_data['y'] = y
                result.append(tile_data)

        return result

    # ========== 部队数据接口 ==========

    def get_army(self, army_id: str) -> Optional[Dict]:
        """获取部队数据"""
        armies = self._load_json(self.armies_file)
        return armies.get(army_id)

    def save_army(self, army_id: str, army_data: Dict):
        """保存部队数据"""
        armies = self._load_json(self.armies_file)
        armies[army_id] = army_data
        self._save_json(self.armies_file, armies)

    def delete_army(self, army_id: str):
        """删除部队数据"""
        armies = self._load_json(self.armies_file)
        if army_id in armies:
            del armies[army_id]
            self._save_json(self.armies_file, armies)

    def get_player_armies(self, player_id: str) -> List[Dict]:
        """获取玩家的所有部队"""
        armies = self._load_json(self.armies_file)
        result = []

        for army_id, army_data in armies.items():
            if army_data.get('player_id') == player_id:
                army_data['army_id'] = army_id
                result.append(army_data)

        return result


# 全局数据库实例
db = DatabaseManager()
