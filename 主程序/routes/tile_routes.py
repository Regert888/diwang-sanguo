"""
地块相关路由
"""
from routes.router import router
from services.tile_service import TileService
from projections.tile_projection import TileProjection


tile_service = TileService()


@router.get("/api/tiles")
def get_tiles(query_params):
    """获取地块列表"""
    x = query_params.get("x")
    y = query_params.get("y")
    radius = query_params.get("radius", 10)

    if x is None or y is None:
        return 400, {"error": "Missing coordinates"}

    try:
        x = int(x)
        y = int(y)
        radius = int(radius)
    except ValueError:
        return 400, {"error": "Invalid coordinates"}

    tiles = tile_service.get_tiles_in_range(x, y, radius)
    return 200, TileProjection.project_map_area(tiles, x, y, radius)


@router.get("/api/tile")
def get_tile_info(query_params):
    """获取单个地块详情"""
    x = query_params.get("x")
    y = query_params.get("y")

    if x is None or y is None:
        return 400, {"error": "Missing coordinates"}

    try:
        x = int(x)
        y = int(y)
    except ValueError:
        return 400, {"error": "Invalid coordinates"}

    tile = tile_service.get_tile(x, y)
    if not tile:
        return 404, {"error": "Tile not found"}

    return 200, TileProjection.project_tile_detail(tile)
