"""可选 QQ 邮箱通知，发送固定格式的每轮执行结果。"""

import json
import hashlib
import logging
import re
import smtplib
import ssl
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import format_datetime, make_msgid
from pathlib import Path

from community import CommunityError

LOGGER = logging.getLogger("pgr-sign")
MAIL_PATH = Path(__file__).resolve().parent / "config" / "mail.json"
MAIL_SUBJECT = "战双签到通知"


def conversation_id(config):
    """以收发地址生成稳定会话锚点，不依赖容器状态或授权码。"""
    addresses = [config["sender"].lower(), config["recipient"].lower()]
    digest = hashlib.sha256(json.dumps(addresses).encode("utf-8")).hexdigest()
    return f"<pgr-sign.{digest}@pgr-sign.invalid>"


def load_mail(path=MAIL_PATH):
    """未配置时关闭通知；校验失败不回显文件内容。"""
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError):
        raise CommunityError("无法读取 config/mail.json，请检查权限及 JSON 格式") from None
    if not isinstance(data, dict) or type(data.get("enabled")) is not bool:
        raise CommunityError("邮件配置 enabled 必须为 true 或 false")
    if not data["enabled"]:
        return None
    for key in ("sender", "recipient"):
        value = data.get(key)
        if not isinstance(value, str) or not re.fullmatch(
            r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+", value
        ):
            raise CommunityError(f"邮件配置 {key} 需要有效邮箱地址")
    if not data["sender"].lower().endswith("@qq.com"):
        raise CommunityError("发件人需使用 QQ 邮箱地址")
    password = data.get("authorization_code")
    if not isinstance(password, str) or not re.fullmatch(r"[A-Za-z]{16}", password):
        raise CommunityError("请填写 QQ 邮箱的 16 位授权码，不是登录密码")
    return data


def send_mail(config, subject, body):
    """固定使用 QQ SMTP TLS，启用证书校验并隐藏底层错误内容。"""
    message = EmailMessage()
    message["From"] = config["sender"]
    message["To"] = config["recipient"]
    message["Subject"] = subject
    message["Date"] = format_datetime(datetime.now(timezone.utc))
    message["Message-ID"] = make_msgid(domain="qq.com")
    # 所有通知引用同一个会话锚点，每封邮件仍保留独立编号。
    thread_id = conversation_id(config)
    message["In-Reply-To"] = thread_id
    message["References"] = thread_id
    message.set_content(body)
    LOGGER.info("邮件开始发送")
    try:
        with smtplib.SMTP_SSL("smtp.qq.com", 465, timeout=15,
                              context=ssl.create_default_context()) as smtp:
            smtp.login(config["sender"], config["authorization_code"])
            smtp.send_message(message)
    except smtplib.SMTPAuthenticationError:
        raise CommunityError("邮件认证失败，请检查 SMTP 服务及授权码") from None
    except Exception:
        raise CommunityError("邮件发送失败，请检查网络、邮箱设置和发送限制") from None
    LOGGER.info("邮件发送成功：QQ 邮箱服务器已接收，请检查收件箱或垃圾箱")


def notify_results(results, success):
    """每轮结束发送一封成功或失败摘要；通知失败不影响签到调度。"""
    try:
        config = load_mail()
        if not config:
            LOGGER.info("邮件通知未启用，跳过发送")
            return
        status = "全部成功" if success else "存在失败"
        body = f"本轮执行{status}\n完成时间：{datetime.now().astimezone().isoformat(timespec='seconds')}\n\n"
        body += "\n".join(results)
        body += "\n\n请查看容器日志了解详情。账号序号按当前启用账号顺序排列。"
        send_mail(config, MAIL_SUBJECT, body)
    except CommunityError as error:
        LOGGER.error("邮件通知失败：%s", error)
