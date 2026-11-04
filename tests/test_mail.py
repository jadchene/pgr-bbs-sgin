"""离线验证邮件通知和任务失败汇总，不连接邮箱或真实账号。"""

import json
import smtplib
import ssl
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import app
import mail_notify as mail
from community import CommunityError, TokenExpired


class MailTests(unittest.TestCase):
    """验证通知边界及敏感内容保护。作者：chenjd；创建时间：2026-11-04 15:00:00。"""

    def setUp(self):
        """使用隔离目录和假邮箱配置。"""
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "mail.json"
        self.config = {"enabled": True, "sender": "123@qq.com",
                       "recipient": "456@qq.com", "authorization_code": "abcdefghijklmnop"}

    def test_optional_and_invalid_config(self):
        """缺省和关闭不联网，格式及头部注入在发送前拒绝。"""
        self.assertIsNone(mail.load_mail(self.path))
        self.path.write_text('{"enabled": false}')
        self.assertIsNone(mail.load_mail(self.path))
        for field, value in (("enabled", "true"), ("sender", "x@example.com"),
                             ("recipient", "a@qq.com\nBcc: x@qq.com"),
                             ("authorization_code", "secret-invalid")):
            self.path.write_text(json.dumps({**self.config, field: value}))
            with self.assertRaises(CommunityError) as raised:
                mail.load_mail(self.path)
            if field != "enabled":
                self.assertNotIn(value, str(raised.exception))
        self.path.write_text(json.dumps(self.config))
        self.assertEqual(mail.load_mail(self.path), self.config)

    def test_verified_tls_and_envelope(self):
        """启用证书与主机校验，凭据仅供登录且不进入正文。"""
        with patch("mail_notify.smtplib.SMTP_SSL") as factory:
            mail.send_mail(self.config, "测试", "账号 1：认证失败")
        args, kwargs = factory.call_args
        self.assertEqual(args, ("smtp.qq.com", 465))
        self.assertEqual(kwargs["timeout"], 15)
        self.assertTrue(kwargs["context"].check_hostname)
        self.assertEqual(kwargs["context"].verify_mode, ssl.CERT_REQUIRED)
        smtp = factory.return_value.__enter__.return_value
        smtp.login.assert_called_once_with("123@qq.com", "abcdefghijklmnop")
        message = smtp.send_message.call_args.args[0]
        self.assertEqual(message["To"], "456@qq.com")
        self.assertNotIn("abcdefghijklmnop", message.as_string())

    def test_send_errors_hide_server_response(self):
        """网络及认证错误不回显服务端敏感内容。"""
        for error in (smtplib.SMTPAuthenticationError(535, b"secret"), OSError("secret")):
            with patch("mail_notify.smtplib.SMTP_SSL", side_effect=error):
                with self.assertRaises(CommunityError) as raised:
                    mail.send_mail(self.config, "测试", "测试")
                self.assertNotIn("secret", str(raised.exception))

    def test_no_mail_on_success_or_disabled(self):
        """没有失败及未配置邮件均不建立连接。"""
        with patch("mail_notify.load_mail", return_value=None), patch("mail_notify.send_mail") as send:
            mail.notify_failures([])
            mail.notify_failures(["账号 1：认证失败"])
            send.assert_not_called()

    def test_notification_failure_is_contained(self):
        """邮件故障不能使调度退出。"""
        with patch("mail_notify.load_mail", return_value=self.config), patch(
            "mail_notify.send_mail", side_effect=CommunityError("邮件发送失败")
        ), self.assertLogs("pgr-sign", level="ERROR"):
            mail.notify_failures(["账号 1：认证失败"])

    def test_final_failures_are_aggregated_without_secrets(self):
        """多个账号仅汇总一次，重试及认证错误原文不会发到邮箱。"""
        accounts = [{"name": "private-name", "token": "secret"}] * 2
        stop = MagicMock()
        stop.is_set.return_value = False
        stop.wait.return_value = False
        with patch("app.load_accounts", return_value=accounts), patch("app.CommunityClient"), patch(
            "app.run_account", side_effect=[TokenExpired("secret"), CommunityError("secret"),
                                             CommunityError("secret"), CommunityError("secret")]
        ) as run, patch("app.notify_failures") as notify:
            self.assertFalse(app.run_once(stop))
        self.assertEqual(run.call_count, 4)
        notify.assert_called_once()
        failures = notify.call_args.args[0]
        self.assertEqual(len(failures), 2)
        self.assertIn("认证失败", failures[0])
        self.assertIn("重试 3 次", failures[1])
        self.assertNotIn("secret", str(failures))
        self.assertNotIn("private-name", str(failures))

    def test_recovered_run_and_shutdown_do_not_send(self):
        """重试成功及正常停止不发失败邮件。"""
        for stopped in (False, True):
            stop = MagicMock()
            stop.is_set.return_value = False
            stop.wait.return_value = stopped
            with patch("app.load_accounts", return_value=[{}]), patch("app.CommunityClient"), patch(
                "app.run_account", side_effect=[CommunityError("网络异常"), None]
            ), patch("mail_notify.send_mail") as send:
                self.assertEqual(app.run_once(stop), not stopped)
                send.assert_not_called()

    def test_test_email_does_not_run_tasks(self):
        """独立测试邮件无需账号配置，不执行游戏或社区操作。"""
        with patch("sys.argv", ["app.py", "--test-email"]), patch("app.load_mail", return_value=self.config), patch(
            "app.send_mail"
        ) as send, patch("app.load_accounts") as accounts, patch("app.run_once") as run:
            self.assertEqual(app.main(), 0)
        send.assert_called_once()
        accounts.assert_not_called()
        run.assert_not_called()
