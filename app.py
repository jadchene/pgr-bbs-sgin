"""Docker 定时入口，账号文件只读，每轮执行前重新加载。"""

import argparse
import json
import logging
import os
import re
import signal
import threading
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from community import CommunityClient, CommunityError, TokenExpired, run_community

LOGGER = logging.getLogger("pgr-sign")
CONFIG_PATH = Path(__file__).resolve().parent / "config" / "accounts.json"


def load_accounts(path=CONFIG_PATH):
    """校验账号配置；错误只报告序号，防止配置内容进入日志。"""
    try:
        accounts = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        raise CommunityError("无法读取 config/accounts.json，请检查文件及 JSON 格式") from None
    if not isinstance(accounts, list) or not accounts:
        raise CommunityError("账号配置必须是非空数组")
    result, names = [], set()
    for index, account in enumerate(accounts, 1):
        if not isinstance(account, dict) or type(account.get("enabled", True)) is not bool:
            raise CommunityError(f"第 {index} 个账号的配置格式错误")
        if not account.get("enabled", True):
            continue
        name = account.get("name")
        if not isinstance(name, str) or not name.strip() or any(ord(c) < 32 for c in name):
            raise CommunityError(f"第 {index} 个账号需要有效名称")
        if name in names:
            raise CommunityError(f"第 {index} 个账号名称重复")
        names.add(name)
        token = account.get("token")
        if not isinstance(token, str) or not re.fullmatch(r"[\x21-\x7e]+", token):
            raise CommunityError(f"第 {index} 个账号需要有效 Token")
        item = {"name": name, "token": token}
        for key in ("devcode", "distinct_id"):
            value = account.get(key) or str(uuid.uuid5(uuid.NAMESPACE_URL, f"pgr-sign/{name}/{key}"))
            if not isinstance(value, str) or not re.fullmatch(r"[\x21-\x7e]+", value):
                raise CommunityError(f"第 {index} 个账号的设备标识无效")
            item[key] = value
        result.append(item)
    if not result:
        raise CommunityError("没有启用的账号")
    return result


def run_once(stop, path=CONFIG_PATH):
    """串行运行账号；单个账号失败不影响其他账号，不自动删除或禁用账号。"""
    try:
        accounts = load_accounts(path)
    except CommunityError as error:
        LOGGER.error("%s", error)
        return False
    success = True
    for index, account in enumerate(accounts, 1):
        if stop.is_set():
            return False
        # 只记录账号序号，避免误填在名称字段的敏感数据进入日志。
        LOGGER.info("开始执行账号 %d/%d", index, len(accounts))
        for attempt in range(1, 4):
            try:
                run_community(CommunityClient(account, stop))
                break
            except TokenExpired as error:
                LOGGER.error("账号 %d：%s", index, error)
                success = False
                break
            except CommunityError as error:
                LOGGER.warning("账号 %d，第 %d/3 次：%s", index, attempt, error)
                if attempt == 3:
                    success = False
                elif stop.wait(10):
                    return False
            except Exception:
                LOGGER.error("账号 %d：发生未预期错误，请检查接口适配", index)
                success = False
                break
    return success


def schedule_settings():
    """读取每日执行时刻、时区和启动执行开关。"""
    value = os.getenv("SIGN_TIME", "09:30")
    if not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", value):
        raise CommunityError("SIGN_TIME 必须是 HH:MM，例如 09:30")
    hour, minute = map(int, value.split(":"))
    try:
        zone = ZoneInfo(os.getenv("TZ", "Asia/Shanghai"))
    except (ZoneInfoNotFoundError, ValueError):
        raise CommunityError("TZ 不是可用的时区") from None
    startup = os.getenv("RUN_ON_START", "true").lower()
    if startup not in ("true", "false"):
        raise CommunityError("RUN_ON_START 必须是 true 或 false")
    return hour, minute, zone, startup == "true"


def next_run(now, hour, minute):
    """计算下一个本地每日时刻，已到执行时刻则选择次日。"""
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return target


def serve(stop, hour, minute, zone, startup, runner=run_once, now=None):
    """在同一线程内调度，等待可被停止信号中断，防止任务重叠。"""
    clock = now or (lambda: datetime.now(zone))
    if startup and not stop.is_set():
        runner(stop)
    while not stop.is_set():
        target = next_run(clock(), hour, minute)
        LOGGER.info("下次执行：%s", target.isoformat())
        while not stop.is_set():
            remaining = target.timestamp() - clock().timestamp()
            if remaining <= 0:
                break
            stop.wait(min(remaining, 30))
        if not stop.is_set():
            runner(stop)


def main():
    """默认运行定时服务，支持 Compose 内一次执行和只读配置检查。"""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="库街区战双社区定时任务")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--once", action="store_true", help="执行一轮后退出")
    mode.add_argument("--check", action="store_true", help="只验证配置，不发送网络请求")
    args = parser.parse_args()
    stop = threading.Event()
    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, lambda *_: stop.set())
    try:
        settings = schedule_settings()
        load_accounts()
        if args.check:
            LOGGER.info("账号和定时配置检查通过")
            return 0
        if args.once:
            return 0 if run_once(stop) else 1
        serve(stop, *settings)
        return 0
    except CommunityError as error:
        LOGGER.error("%s", error)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
