"""库街区战双任务与 HTTP 客户端；请求仅允许发送到固定的官方接口。"""

import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request

LOGGER = logging.getLogger("pgr-sign")
BASE_URL = "https://api.kurobbs.com"
COMMUNITY_PATHS = frozenset({
    "/user/signIn",
    "/forum/list",
    "/forum/getPostDetail",
    "/forum/like",
    "/encourage/level/getTaskProcess",
    "/encourage/level/shareTask",
    "/encourage/gold/getTotalGold",
})
SUPPLY_PATHS = frozenset({
    "/user/mineV2",
    "/user/role/findRoleList",
    "/encourage/signIn/initSignInV2",
    "/encourage/signIn/v2",
})
PATHS = COMMUNITY_PATHS | SUPPLY_PATHS
TASK_NAMES = ("用户签到", "浏览3篇帖子", "点赞5次", "分享1次帖子")


class CommunityError(Exception):
    """可安全写入日志的错误。作者：chenjd；创建时间：2026-11-04 11:30:00。"""


class TokenExpired(CommunityError):
    """登录凭据失效。作者：chenjd；创建时间：2026-11-04 11:30:00。"""


class AlreadySigned(CommunityError):
    """补给接口提示已签到，仍需查询确认。作者：chenjd；创建时间：2026-11-04 11:33:00。"""


class NoRedirect(urllib.request.HTTPRedirectHandler):
    """阻止凭据通过重定向外传。作者：chenjd；创建时间：2026-11-04 11:30:00。"""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        """拒绝所有重定向，由调用方报告 HTTP 错误。"""
        return None


class CommunityClient:
    """仅访问库街区指定接口的客户端。作者：chenjd；创建时间：2026-11-04 11:30:00。"""

    def __init__(self, account, stop=None):
        """保存账号凭据，禁用环境代理，不记录请求头或响应原文。"""
        self.headers = {
            "token": account["token"],
            "Cookie": "user_token=" + account["token"],
            "devCode": account["devcode"],
            "distinct_id": account["distinct_id"],
            "source": "ios",
            "lang": "zh-Hans",
            "version": "2.2.0",
            "channelId": "1",
            "channel": "appstore",
            "model": "iPhone15,2",
            "osVersion": "17.3",
            "User-Agent": "KuroGameBox/48 CFNetwork/1492.0.1 Darwin/23.3.0",
            "Content-Type": "application/x-www-form-urlencoded; charset=utf-8",
        }
        self.opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}), NoRedirect()
        )
        self.stop = stop
        self.last_request = 0.0

    def post(self, path, data=None):
        """校验接口白名单，限速并解析响应；凭据及服务端原文不进入异常。"""
        if path not in PATHS:
            raise CommunityError("拒绝访问未授权接口")
        if path in SUPPLY_PATHS - {"/user/mineV2"} and str((data or {}).get("gameId")) != "2":
            raise CommunityError("每日补给仅允许战双账号")
        delay = max(0.0, 1.0 - (time.monotonic() - self.last_request))
        if self.stop is not None:
            if self.stop.wait(delay):
                raise CommunityError("任务已停止")
        else:
            time.sleep(delay)
        request = urllib.request.Request(
            BASE_URL + path,
            data=urllib.parse.urlencode(data or {}).encode("utf-8"),
            headers=self.headers,
            method="POST",
        )
        self.last_request = time.monotonic()
        try:
            with self.opener.open(request, timeout=30) as response:
                raw = response.read(2_000_001)
            if len(raw) > 2_000_000:
                raise CommunityError("接口响应过大")
            result = json.loads(raw)
        except urllib.error.HTTPError as error:
            raise CommunityError(f"HTTP 请求失败（{error.code}）") from None
        except (OSError, ValueError, urllib.error.URLError):
            raise CommunityError("网络、证书或响应格式异常") from None
        if not isinstance(result, dict):
            raise CommunityError("接口响应格式异常")
        code = result.get("code")
        if code in (220, 221, 222, 230):
            raise TokenExpired("Token 已失效，请手动重新获取并更新配置")
        if path == "/encourage/signIn/v2" and code == 1511:
            raise AlreadySigned("每日补给接口提示今日已签到")
        if code != 200:
            safe_code = str(code) if type(code) is int else "未知"
            raise CommunityError(f"接口返回失败（业务码 {safe_code}）")
        return result.get("data")


def daily_tasks(client):
    """读取社区每日任务；gameId=0 是原项目使用的社区全局任务查询。"""
    result = client.post("/encourage/level/getTaskProcess", {"gameId": "0"})
    if not isinstance(result, dict) or not isinstance(result.get("dailyTask"), list):
        raise CommunityError("每日任务响应格式异常")
    tasks = result["dailyTask"]
    if any(not isinstance(task, dict) for task in tasks):
        raise CommunityError("每日任务响应格式异常")
    if not all(any(task.get("remark") == name for task in tasks) for name in TASK_NAMES):
        raise CommunityError("每日任务缺失或名称已变化，需要检查接口适配")
    return tasks


def completed(task):
    """兼容接口返回的数字或字符串完成状态。"""
    return str(task.get("process")) == "1"


def pgr_posts(client):
    """读取战双推荐板块，过滤其他游戏、缺失标识及重复帖子。"""
    result = client.post("/forum/list", {
        "gameId": "2", "forumId": "2", "pageIndex": "1",
        "pageSize": "20", "searchType": "3", "timeType": "0",
    })
    if not isinstance(result, dict) or not isinstance(result.get("postList"), list):
        raise CommunityError("帖子列表响应格式异常")
    posts, seen = [], set()
    for post in result["postList"]:
        if not isinstance(post, dict) or str(post.get("gameId")) != "2":
            continue
        post_id = str(post.get("postId", ""))
        user_id = str(post.get("userId", ""))
        forum_id = str(post.get("gameForumId", ""))
        if not all(value.isdecimal() for value in (post_id, user_id, forum_id)):
            continue
        if post_id not in seen:
            posts.append(post)
            seen.add(post_id)
    return posts


def execute_task(client, name):
    """执行社区签到、浏览、点赞或分享；不调用游戏签到接口。"""
    if name == "用户签到":
        client.post("/user/signIn", {"gameId": "2"})
    elif name == "分享1次帖子":
        client.post("/encourage/level/shareTask", {"gameId": "2"})
    else:
        posts = pgr_posts(client)
        if name == "点赞5次":
            posts = [post for post in posts if str(post.get("isLike", 0)) != "1"]
        required = 3 if name == "浏览3篇帖子" else 5
        for post in posts[:required]:
            if name == "浏览3篇帖子":
                client.post("/forum/getPostDetail", {
                    "postId": post["postId"], "isOnlyPublisher": "0", "showOrderTyper": "2",
                })
            else:
                client.post("/forum/like", {
                    "gameId": "2", "forumId": post["gameForumId"],
                    "likeType": "1", "operateType": "1", "postCommentId": "",
                    "postCommentReplyId": "", "postId": post["postId"],
                    "postType": "1", "toUserId": post["userId"],
                })
        if not posts:
            raise CommunityError("没有符合条件的战双帖子")


def run_community(client):
    """逐项执行任务，再以服务端任务状态确认完成，并查询金币。"""
    tasks = daily_tasks(client)
    for name in TASK_NAMES:
        task = next(task for task in tasks if task.get("remark") == name)
        if completed(task):
            LOGGER.info("%s：已完成，跳过", name)
            continue
        try:
            execute_task(client, name)
        except TokenExpired:
            raise
        except CommunityError as error:
            LOGGER.warning("%s：%s", name, error)
    final_tasks = daily_tasks(client)
    earned = sum(int(task["gainGold"]) for task in final_tasks
                 if completed(task) and str(task.get("gainGold", "")).isdecimal())
    LOGGER.info("今日已完成任务获得金币：%d", earned)
    pending = [name for name in TASK_NAMES if not any(
        task.get("remark") == name and completed(task) for task in final_tasks
    )]
    gold = client.post("/encourage/gold/getTotalGold")
    if isinstance(gold, dict) and str(gold.get("goldNum", "")).isdecimal():
        LOGGER.info("当前金币：%s", int(gold["goldNum"]))
    else:
        raise CommunityError("金币响应格式异常")
    if pending:
        raise CommunityError("服务端仍显示未完成：" + "、".join(pending))
    LOGGER.info("库街区每日任务全部完成")
