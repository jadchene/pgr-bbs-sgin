"""使用本地模拟接口验证任务范围、凭据保护和定时行为，不访问真实账号。"""

import io
import json
import os
import tempfile
import threading
import unittest
import urllib.error
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import app
import community


def tasks(done):
    """生成明确的社区任务状态。"""
    return {"dailyTask": [
        {"remark": name, "process": str(int(done)), "gainGold": 10}
        for name in community.TASK_NAMES
    ]}


def posts():
    """生成战双帖子及一个其他游戏帖子，验证过滤。"""
    return {"postList": [
        {"postId": str(i), "userId": "100", "gameId": 2, "gameForumId": 3, "isLike": 0}
        for i in range(1, 7)
    ] + [{"postId": "999", "userId": "100", "gameId": 3, "gameForumId": 9}]}


class CommunityTests(unittest.TestCase):
    """验证社区任务范围。作者：chenjd；创建时间：2026-11-04 11:30:00。"""

    def test_full_flow_only_community_and_pgr(self):
        """所有变更限定战双社区，完成状态必须再次查询。"""
        client = MagicMock()
        status = iter([tasks(False), tasks(True)])

        def respond(path, data=None):
            """模拟各社区接口。"""
            if path.endswith("getTaskProcess"):
                return next(status)
            if path == "/forum/list":
                return posts()
            if path.endswith("getTotalGold"):
                return {"goldNum": 120}
            return {}

        client.post.side_effect = respond
        community.run_community(client)
        calls = client.post.call_args_list
        paths = [call.args[0] for call in calls]
        self.assertEqual(paths.count("/user/signIn"), 1)
        self.assertEqual(paths.count("/forum/getPostDetail"), 3)
        self.assertEqual(paths.count("/forum/like"), 5)
        self.assertEqual(paths.count("/encourage/level/shareTask"), 1)
        self.assertEqual(paths.count("/encourage/level/getTaskProcess"), 2)
        self.assertEqual(set(paths), community.COMMUNITY_PATHS)
        for call in calls:
            if len(call.args) < 2:
                continue
            path, data = call.args
            if "gameId" in data:
                self.assertEqual(data["gameId"], "0" if path.endswith("getTaskProcess") else "2")
            self.assertNotEqual(data.get("postId"), "999")
            if path == "/forum/list":
                self.assertEqual(data["forumId"], "2")
            if path == "/forum/like":
                self.assertEqual(data["forumId"], 3)

    def test_completed_tasks_do_not_repeat_mutations(self):
        """已完成时只查询任务及金币。"""
        client = MagicMock()
        client.post.side_effect = [tasks(True), tasks(True), {"goldNum": 10}]
        community.run_community(client)
        self.assertEqual(client.post.call_count, 3)

    def test_unfinished_tasks_are_failure(self):
        """接口成功但服务端仍未完成时不能报告成功。"""
        client = MagicMock()
        client.post.side_effect = [tasks(True), tasks(False), {"goldNum": 10}]
        with self.assertRaisesRegex(community.CommunityError, "仍显示未完成"):
            community.run_community(client)

    def test_missing_tasks_fail_closed(self):
        """空任务或字段变化不能当作全部完成。"""
        client = MagicMock()
        client.post.return_value = {"dailyTask": []}
        with self.assertRaises(community.CommunityError):
            community.run_community(client)

    def test_skip_already_liked_and_deduplicate_posts(self):
        """不反复点赞同一帖子，不触碰其他游戏帖子。"""
        client = MagicMock()
        result = posts()
        result["postList"][0]["isLike"] = 1
        result["postList"].insert(0, result["postList"][1])
        client.post.return_value = result
        community.execute_task(client, "点赞5次")
        liked = [call.args[1]["postId"] for call in client.post.call_args_list
                 if call.args[0] == "/forum/like"]
        self.assertEqual(len(liked), 5)
        self.assertEqual(len(set(liked)), 5)
        self.assertNotIn("1", liked)
        self.assertNotIn("999", liked)


class TransportTests(unittest.TestCase):
    """验证凭据传输边界。作者：chenjd；创建时间：2026-11-04 11:30:00。"""

    def setUp(self):
        """创建假账号，不使用真实 Token。"""
        self.client = community.CommunityClient({
            "token": "secret-test-token", "devcode": "device", "distinct_id": "distinct",
        })
        self.client.opener = MagicMock()

    def respond(self, body):
        """设置模拟响应。"""
        self.client.opener.open.return_value = io.BytesIO(json.dumps(body).encode())

    def test_fixed_https_host_and_headers(self):
        """凭据只发往固定 HTTPS 地址。"""
        self.respond({"code": 200, "data": {}})
        self.client.post("/user/signIn", {"gameId": "2"})
        request = self.client.opener.open.call_args.args[0]
        self.assertEqual(request.full_url, "https://api.kurobbs.com/user/signIn")
        self.assertEqual(request.get_header("Token"), "secret-test-token")
        self.assertEqual(request.data, b"gameId=2")
        self.assertEqual(self.client.opener.open.call_args.kwargs["timeout"], 30)

    def test_disallow_external_and_unapproved_endpoints(self):
        """外部地址及未授权补签接口均在联网前被拒绝。"""
        for path in ("https://example.com", "//example.com", "/encourage/signIn/repleSigInV2"):
            with self.subTest(path=path), self.assertRaises(community.CommunityError):
                self.client.post(path)
        self.client.opener.open.assert_not_called()

    def test_no_redirect(self):
        """所有重定向都不携带 Token 跟随。"""
        handler = community.NoRedirect()
        for code in (301, 302, 303, 307, 308):
            self.assertIsNone(handler.redirect_request(None, None, code, "", {}, "https://example.com"))

    def test_auth_expiry_and_error_redaction(self):
        """不把服务端回显内容记录到异常。"""
        self.respond({"code": 220, "msg": "secret-test-token"})
        with self.assertRaises(community.TokenExpired) as raised:
            self.client.post("/user/signIn")
        self.assertNotIn("secret-test-token", str(raised.exception))

    def test_network_error_redaction(self):
        """底层异常中的凭据不外泄。"""
        self.client.opener.open.side_effect = urllib.error.URLError("secret-test-token")
        with self.assertRaises(community.CommunityError) as raised:
            self.client.post("/user/signIn")
        self.assertNotIn("secret-test-token", str(raised.exception))

    def test_proxy_environment_is_ignored(self):
        """环境中的代理不会改变凭据去向。"""
        with patch.dict(os.environ, {"HTTPS_PROXY": "http://example.com:8080"}), patch(
            "community.urllib.request.getproxies", side_effect=AssertionError("不应读取代理")
        ) as proxy:
            community.CommunityClient({"token": "test", "devcode": "d", "distinct_id": "i"})
            proxy.assert_not_called()


class ConfigAndSchedulerTests(unittest.TestCase):
    """验证配置、隔离和定时。作者：chenjd；创建时间：2026-11-04 11:30:00。"""

    def setUp(self):
        """准备独立临时账号文件。"""
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "accounts.json"
        self.path.write_text(json.dumps([{"name": "test", "token": "fake-token"}]))

    def test_stable_identifiers_and_readonly_config(self):
        """运行不修改账号文件，生成的设备标识保持稳定。"""
        before = self.path.read_bytes()
        self.assertEqual(app.load_accounts(self.path), app.load_accounts(self.path))
        self.assertEqual(before, self.path.read_bytes())

    def test_reject_bad_config_without_content(self):
        """错误配置中嵌入的敏感内容不进入异常。"""
        for content in ('{"secret":"fake-token"}', '[{"name":"x","token":"fake-token\\n"}]', '[]'):
            self.path.write_text(content)
            with self.assertRaises(community.CommunityError) as raised:
                app.load_accounts(self.path)
            self.assertNotIn("fake-token", str(raised.exception))

    def test_accounts_isolated_and_no_secret_logs(self):
        """首账号失效不影响后续账号，日志没有 Token。"""
        self.path.write_text(json.dumps([
            {"name": "fake-token", "token": "fake-token"},
            {"name": "second", "token": "other-token"},
        ]))
        with patch("app.run_account", side_effect=[community.TokenExpired("Token 已失效"), None]) as run:
            with self.assertLogs("pgr-sign", level="INFO") as logs:
                self.assertFalse(app.run_once(threading.Event(), self.path))
            self.assertEqual(run.call_count, 2)
            self.assertNotIn("fake-token", "".join(logs.output))
            self.assertNotIn("other-token", "".join(logs.output))

    def test_retry_then_success(self):
        """普通故障重试，重新查询任务避免重复操作。"""
        stop = MagicMock()
        stop.is_set.return_value = False
        stop.wait.return_value = False
        with patch("app.run_account", side_effect=[community.CommunityError("网络异常"), None]) as run:
            self.assertTrue(app.run_once(stop, self.path))
            self.assertEqual(run.call_count, 2)
        stop.wait.assert_called_once_with(10)

    def test_next_run_cross_day(self):
        """本地日历跨日计算正确。"""
        zone = timezone(timedelta(hours=8))
        before = datetime(2026, 11, 4, 9, 29, tzinfo=zone)
        self.assertEqual(app.next_run(before, 9, 30).day, 4)
        self.assertEqual(app.next_run(before.replace(hour=10), 9, 30).day, 5)
        self.assertEqual(app.next_run(before.replace(minute=30), 9, 30).day, 5)

    def test_schedule_runs_at_target_and_stops(self):
        """实际调度循环到点运行，收到停止信号后退出。"""
        zone = timezone(timedelta(hours=8))
        current = [datetime(2026, 11, 4, 9, 29, 55, tzinfo=zone)]
        stop = MagicMock()
        halted = [False]
        stop.is_set.side_effect = lambda: halted[0]
        stop.wait.side_effect = lambda seconds: current.__setitem__(0, current[0] + timedelta(seconds=seconds))

        def run(event):
            """记录到点执行并请求停止。"""
            self.assertEqual(current[0].minute, 30)
            halted[0] = True

        runner = MagicMock(side_effect=run)
        app.serve(stop, 9, 30, zone, False, runner, lambda: current[0])
        runner.assert_called_once_with(stop)

    def test_startup_run_and_shutdown(self):
        """启动执行开关生效，关闭时不会再执行。"""
        stop = threading.Event()
        runner = MagicMock(side_effect=lambda event: event.set())
        app.serve(stop, 9, 30, timezone.utc, True, runner)
        runner.assert_called_once_with(stop)

    def test_invalid_schedule_rejected(self):
        """非法执行时间不能悄悄使用默认值。"""
        with patch.dict(os.environ, {"SIGN_TIME": "25:00"}):
            with self.assertRaises(community.CommunityError):
                app.schedule_settings()


if __name__ == "__main__":
    unittest.main()
