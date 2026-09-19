"""
玩家相关路由
"""
from routes.router import router
from services.player_service import PlayerService
from services.army_service import ArmyService
from projections.player_projection import PlayerProjection
from projections.army_projection import ArmyProjection


player_service = PlayerService()
army_service = ArmyService()


@router.get("/api/player")
def get_player_info(query_params):
    """获取玩家信息"""
    player_id = query_params.get("id")
    if not player_id:
        return 400, {"error": "Missing player id"}

    player = player_service.get_player(player_id)
    if not player:
        return 404, {"error": "Player not found"}

    return 200, PlayerProjection.project_player_info(player)


@router.get("/api/player/resources")
def get_player_resources(query_params):
    """获取玩家资源"""
    player_id = query_params.get("id")
    if not player_id:
        return 400, {"error": "Missing player id"}

    player = player_service.get_player(player_id)
    if not player:
        return 404, {"error": "Player not found"}

    return 200, PlayerProjection.project_resources(player)


@router.get("/api/player/generals")
def get_player_generals(query_params):
    """获取玩家武将列表"""
    player_id = query_params.get("id")
    if not player_id:
        return 400, {"error": "Missing player id"}

    generals = player_service.get_generals(player_id)
    return 200, PlayerProjection.project_generals_list(generals)


@router.get("/api/player/armies")
def get_player_armies(query_params):
    """获取玩家部队列表"""
    player_id = query_params.get("id")
    if not player_id:
        return 400, {"error": "Missing player id"}

    armies = army_service.get_player_armies(player_id)
    return 200, ArmyProjection.project_army_list(armies)
