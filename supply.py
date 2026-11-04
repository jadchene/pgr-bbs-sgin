"""战双每日补给：自动发现绑定角色，以官方签到状态确认领取结果。"""

import re

from community import AlreadySigned, CommunityError, LOGGER, TokenExpired

INIT_PATH = "/encourage/signIn/initSignInV2"
SIGN_PATH = "/encourage/signIn/v2"


def identifier(value):
    """只接受接口中的非空数字标识，拒绝缺失值和布尔值。"""
    if type(value) not in (str, int) or not re.fullmatch(r"[0-9]+", str(value)):
        raise CommunityError("战双角色或用户标识无效，请检查库街区绑定信息")
    return str(value)


def bound_roles(client):
    """查询当前库街区用户和战双绑定角色，保留实际服务器并去重。"""
    user = client.post("/user/mineV2")
    if not isinstance(user, dict) or not isinstance(user.get("mine"), dict):
        raise CommunityError("库街区用户信息响应格式异常")
    user_id = identifier(user["mine"].get("userId"))
    roles = client.post("/user/role/findRoleList", {"gameId": "2"})
    if not isinstance(roles, list):
        raise CommunityError("战双角色列表响应格式异常")
    result, seen = [], set()
    for role in roles:
        if not isinstance(role, dict):
            raise CommunityError("战双角色信息响应格式异常")
        # 请求已限定战双，若响应额外提供游戏标识，则进一步核验。
        if "gameId" in role and str(role["gameId"]) != "2":
            continue
        role_id = identifier(role.get("roleId"))
        server_id = identifier(role.get("serverId"))
        if (role_id, server_id) not in seen:
            result.append({"gameId": "2", "roleId": role_id,
                           "serverId": server_id, "userId": user_id})
            seen.add((role_id, server_id))
    if not result:
        raise CommunityError("未找到已绑定的战双角色，请先在库街区 App 绑定角色")
    return result


def sign_status(client, role):
    """读取官方页面使用的 isSigIn 状态，缺失字段不能视为未签到。"""
    status = client.post(INIT_PATH, role)
    if not isinstance(status, dict) or str(status.get("isSigIn")) not in ("True", "False", "0", "1"):
        raise CommunityError("每日补给签到状态响应格式异常")
    return status


def is_signed(status):
    """兼容布尔值及数字形式的签到状态。"""
    return str(status["isSigIn"]) in ("True", "1")


def sign_role(client, role):
    """领取当日补给，使用服务端活动月份并再次确认签到状态。"""
    before = sign_status(client, role)
    if is_signed(before):
        LOGGER.info("战双每日补给：今日已签到，跳过")
        return
    start = before.get("eventStartTimes")
    if not isinstance(start, str) or not re.match(r"^\d{4}-(0[1-9]|1[0-2])-\d{2}", start):
        raise CommunityError("每日补给活动月份无效，未发起签到")
    try:
        client.post(SIGN_PATH, {**role, "reqMonth": start[5:7]})
    except AlreadySigned:
        pass
    if not is_signed(sign_status(client, role)):
        raise CommunityError("每日补给请求已返回，但服务端尚未确认今日签到")
    LOGGER.info("战双每日补给：签到已确认，请到游戏邮箱查收奖励")


def run_supply(client):
    """遍历已绑定的战双角色，一个角色失败不影响其他角色。"""
    roles = bound_roles(client)
    failed = False
    for index, role in enumerate(roles, 1):
        LOGGER.info("每日补给角色 %d/%d", index, len(roles))
        try:
            sign_role(client, role)
        except TokenExpired:
            raise
        except CommunityError as error:
            LOGGER.warning("每日补给角色 %d：%s", index, error)
            failed = True
    if failed:
        raise CommunityError("部分战双角色的每日补给尚未完成")
