# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 jadchene；上游来源及权利声明见 NOTICE。
# 本文件由 jadchene 修改或新增，日期：2026-11-07；按 GPLv3 发布，不提供担保。

"""每日补给离线测试；响应为测试样例，不使用真实账号。"""

import io
import json
import unittest
from unittest.mock import MagicMock, patch

import app
import community
import supply


def role(role_id="101", server_id="1000"):
    """构造独立的战双角色参数。"""
    return {"gameId": "2", "roleId": role_id, "serverId": server_id, "userId": "10"}


def status(signed):
    """构造官方页面使用的签到状态和活动日期字段。"""
    return {"isSigIn": signed, "eventStartTimes": "2026-10-01 00:00:00"}


class SupplyTests(unittest.TestCase):
    """验证战双每日补给。作者：chenjd；创建时间：2026-11-04 11:33:00。"""

    def test_discover_roles_uses_real_servers_and_excludes_other_game(self):
        """角色列表限定战双，服务器来自绑定信息，不硬编码。"""
        client = MagicMock()
        client.post.side_effect = [
            {"mine": {"userId": 10}},
            [role(), role(), role("102", "1001"), {**role(), "gameId": "3"}],
        ]
        self.assertEqual(supply.bound_roles(client), [role(), role("102", "1001")])
        self.assertEqual(client.post.call_args.args, ("/user/role/findRoleList", {"gameId": "2"}))

    def test_empty_bindings_fail_without_signing(self):
        """没有角色不能误报领取成功。"""
        client = MagicMock()
        client.post.side_effect = [{"mine": {"userId": 10}}, []]
        with self.assertRaisesRegex(community.CommunityError, "绑定"):
            supply.run_supply(client)
        self.assertEqual(client.post.call_count, 2)

    def test_missing_server_fails_without_guessing(self):
        """服务器信息缺失时禁止猜测服务器。"""
        client = MagicMock()
        client.post.side_effect = [{"mine": {"userId": 10}}, [{"roleId": "101"}]]
        with self.assertRaises(community.CommunityError):
            supply.run_supply(client)

    def test_claim_uses_event_month_and_rechecks_state(self):
        """使用服务端活动月份而非本地月份，领取后再次查询。"""
        client = MagicMock()
        client.post.side_effect = [status(False), {}, status(True)]
        supply.sign_role(client, role())
        self.assertEqual([call.args[0] for call in client.post.call_args_list], [
            supply.INIT_PATH, supply.SIGN_PATH, supply.INIT_PATH,
        ])
        self.assertEqual(client.post.call_args_list[1].args[1], {**role(), "reqMonth": "10"})

    def test_already_signed_skips_claim(self):
        """已领取时不重复发出领取请求。"""
        client = MagicMock()
        client.post.return_value = status(1)
        supply.sign_role(client, role())
        client.post.assert_called_once_with(supply.INIT_PATH, role())

    def test_concurrent_already_signed_response_is_verified(self):
        """其他入口抢先签到时仍以查询状态为准。"""
        client = MagicMock()
        client.post.side_effect = [status(0), community.AlreadySigned(), status(1)]
        supply.sign_role(client, role())
        self.assertEqual(client.post.call_count, 3)

    def test_unconfirmed_claim_fails(self):
        """请求成功或已签到业务码都不能替代服务端确认。"""
        for response in ({}, community.AlreadySigned()):
            client = MagicMock()
            client.post.side_effect = [status(0), response, status(0)]
            with self.assertRaisesRegex(community.CommunityError, "尚未确认"):
                supply.sign_role(client, role())

    def test_invalid_status_or_month_prevents_claim(self):
        """缺失状态、错误状态或活动日期均禁止盲目签到。"""
        for value in ({}, {"isSigIn": "unknown"}, {"isSigIn": False},
                      {"isSigIn": False, "eventStartTimes": "2026-99-01"}):
            client = MagicMock()
            client.post.return_value = value
            with self.subTest(value=value), self.assertRaises(community.CommunityError):
                supply.sign_role(client, role())
            self.assertEqual(client.post.call_count, 1)

    def test_role_failure_does_not_block_other_roles(self):
        """某角色失败仍处理其他角色，并返回整体失败。"""
        with patch("supply.bound_roles", return_value=[role(), role("102")]), patch(
            "supply.sign_role", side_effect=[community.CommunityError("网络异常"), None]
        ) as sign:
            with self.assertRaises(community.CommunityError):
                supply.run_supply(MagicMock())
            self.assertEqual(sign.call_count, 2)

    def test_expired_token_stops_roles(self):
        """凭据失效后不继续尝试其他角色。"""
        with patch("supply.bound_roles", return_value=[role(), role("102")]), patch(
            "supply.sign_role", side_effect=community.TokenExpired("Token 已失效")
        ) as sign:
            with self.assertRaises(community.TokenExpired):
                supply.run_supply(MagicMock())
            self.assertEqual(sign.call_count, 1)

    def test_failed_supply_still_runs_community_and_retry_skips_finished_group(self):
        """补给失败不阻断社区，重试只补做未完成组。"""
        finished = set()
        with patch("app.run_supply", side_effect=[community.CommunityError("失败"), None]) as claim, patch(
            "app.run_community"
        ) as forum:
            with self.assertRaises(community.CommunityError):
                app.run_account(MagicMock(), finished)
            self.assertEqual(finished, {"社区任务"})
            app.run_account(MagicMock(), finished)
            self.assertEqual(claim.call_count, 2)
            forum.assert_called_once()
            self.assertEqual(finished, {"每日补给", "社区任务"})

    def test_failed_community_does_not_repeat_successful_supply(self):
        """社区重试时不重复执行已经完成的补给组。"""
        finished = set()
        with patch("app.run_supply") as claim, patch(
            "app.run_community", side_effect=[community.CommunityError("失败"), None]
        ) as forum:
            with self.assertRaises(community.CommunityError):
                app.run_account(MagicMock(), finished)
            app.run_account(MagicMock(), finished)
            claim.assert_called_once()
            self.assertEqual(forum.call_count, 2)


class SupplyTransportTests(unittest.TestCase):
    """验证补给接口的请求限制。作者：chenjd；创建时间：2026-11-04 11:33:00。"""

    def setUp(self):
        """使用假 Token 和模拟网络响应。"""
        self.client = community.CommunityClient({"token": "fake-secret", "devcode": "d", "distinct_id": "i"})
        self.client.opener = MagicMock()

    def test_other_games_blocked_before_network(self):
        """白名单接口也不能请求其他游戏。"""
        for path in community.SUPPLY_PATHS - {"/user/mineV2"}:
            for data in ({"gameId": "3"}, {}, {"gameId": "1"}):
                with self.subTest(path=path, data=data), self.assertRaises(community.CommunityError):
                    self.client.post(path, data)
        self.client.opener.open.assert_not_called()

    def test_already_signed_code_only_accepted_for_claim(self):
        """1511 仅在补给签到接口有专门含义，且不返回成功。"""
        self.client.opener.open.return_value = io.BytesIO(json.dumps({"code": 1511, "msg": "fake-secret"}).encode())
        with self.assertRaises(community.AlreadySigned) as raised:
            self.client.post(supply.SIGN_PATH, role())
        self.assertNotIn("fake-secret", str(raised.exception))
        self.client.last_request = 0
        self.client.opener.open.return_value = io.BytesIO(b'{"code":1511}')
        with self.assertRaises(community.CommunityError) as raised:
            self.client.post("/user/signIn", {"gameId": "2"})
        self.assertNotIsInstance(raised.exception, community.AlreadySigned)


if __name__ == "__main__":
    unittest.main()
