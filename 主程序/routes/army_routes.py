"""
部队相关路由
"""
from routes.router import router
from services.army_service import ArmyService
from projections.army_projection import ArmyProjection


army_service = ArmyService()


@router.post("/api/army/move")
def move_army(query_params, body):
    """移动部队"""
    army_id = body.get("army_id")
    target_x = body.get("target_x")
    target_y = body.get("target_y")

    if not all([army_id, target_x is not None, target_y is not None]):
        return 400, {"error": "Missing required fields"}

    try:
        result = army_service.move_army(army_id, target_x, target_y)
        return 200, result
    except Exception as e:
        return 400, {"error": str(e)}


@router.post("/api/army/attack")
def attack_target(query_params, body):
    """攻击目标"""
    attacker_id = body.get("attacker_id")
    defender_id = body.get("defender_id")

    if not all([attacker_id, defender_id]):
        return 400, {"error": "Missing required fields"}

    try:
        result = army_service.attack(attacker_id, defender_id)
        return 200, result
    except Exception as e:
        return 400, {"error": str(e)}


@router.get("/api/army")
def get_army_info(query_params):
    """获取部队信息"""
    army_id = query_params.get("id")
    if not army_id:
        return 400, {"error": "Missing army id"}

    army = army_service.get_army(army_id)
    if not army:
        return 404, {"error": "Army not found"}

    return 200, ArmyProjection.project_army_detail(army)
