"""Integration tests for POST /api/notes/{slug}/comments/, CSRF, rate limits, and SQLite concurrency."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from allauth.account.models import EmailAddress
from django.conf import settings
from django.core.cache import cache
from django.test import Client, TestCase, override_settings

from accounts.models import User
from accounts.tests.helpers import build_login_data, gen_test_credential
from comments.models import GUEST_DISPLAY_NAME, Comment
from comments.views import MAX_COMMENT_REQUEST_BYTES
from config.env import FILEBASED_CACHE_BACKEND, SERVER_DIR
from config.middleware import NO_STORE_CACHE_CONTROL

ISO_UTC_Z_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$")
NOTE_SLUG = "harness-cold-start"
COMMENTS_URL = f"/api/notes/{NOTE_SLUG}/comments/"

_CONCURRENT_WORKER_SCRIPT = '''
import json, threading, django
django.setup()
from allauth.account.models import EmailAddress
from django.db import connections
from django.test import Client
from accounts.models import User
from accounts.tests.helpers import gen_test_credential
members = []
for idx in range(4):
    u = User.objects.create_user(f'u_conc_{idx}', f'conc-{idx}@example.com', gen_test_credential(), display_name=f'并发读者{idx}')
    EmailAddress.objects.create(user=u, email=u.email, verified=True, primary=True)
    members.append(u)
connections.close_all()
barrier, errors, statuses, lock = threading.Barrier(8), [], [], threading.Lock()
def worker(idx):
    try:
        c, ip = Client(enforce_csrf_checks=True, HTTP_HOST='127.0.0.1'), f'198.51.100.{20 + idx}'
        kind = 'guest'
        if idx < 4:
            c.force_login(members[idx])
            kind = 'member'
        csrf = c.get('/api/me/', REMOTE_ADDR=ip).json()['csrfToken']
        barrier.wait(timeout=10)
        res = c.post('/api/notes/harness-cold-start/comments/', data=json.dumps({'body': f'并发评论 #{idx}', 'expectedAuthorKind': kind}), content_type='application/json', HTTP_X_CSRFTOKEN=csrf, REMOTE_ADDR=ip)
        with lock: statuses.append((idx, res.status_code, res.json()))
    except BaseException as exc:
        with lock: errors.append(repr(exc))
    finally:
        connections.close_all()
threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
for t in threads: t.start()
for t in threads: t.join(timeout=15)
print(json.dumps({'errors': errors, 'statuses': statuses}))
'''

_CONCURRENT_READBACK_SCRIPT = '''
import json, django
django.setup()
from django.db import connections
from django.test import Client
res = Client(HTTP_HOST='127.0.0.1').get('/api/notes/harness-cold-start/comments/')
connections.close_all()
print(json.dumps({'status': res.status_code, 'payload': res.json()}))
'''


class NoteCommentsCreateApiTests(TestCase):
    def setUp(self) -> None:
        super().setUp()
        cache.clear()

    def _assert_no_store(self, response: Any) -> None:
        self.assertEqual(response["Cache-Control"], NO_STORE_CACHE_CONTROL)
        self.assertIn("Cookie", response["Vary"])

    def _create_user(
        self,
        email_addr: str,
        display_name: str,
        *,
        verified: bool = True,
        is_comment_admin: bool = False,
    ) -> tuple[User, str]:
        pw = gen_test_credential()
        uname = f"u_{email_addr.split('@', 1)[0].replace('-', '_')}"
        user = User.objects.create_user(
            uname, email_addr, pw, display_name=display_name, is_comment_admin=is_comment_admin
        )
        EmailAddress.objects.create(user=user, email=user.email, verified=verified, primary=True)
        return user, pw

    def _bootstrap_csrf(self, client: Client, **extra: Any) -> dict[str, Any]:
        res = client.get("/api/me/", **extra)
        self.assertEqual(res.status_code, 200)
        self._assert_no_store(res)
        return res.json()

    def _post_json(
        self,
        client: Client,
        payload: Any,
        *,
        csrf_token: str | None = None,
        url: str = COMMENTS_URL,
        **extra: Any,
    ) -> Any:
        headers = dict(extra)
        if csrf_token is not None:
            headers["HTTP_X_CSRFTOKEN"] = csrf_token
        return client.post(url, data=json.dumps(payload), content_type="application/json", **headers)

    def test_guest_create_201_csrf_enforcement_and_unknown_slug_404(self) -> None:
        guest_client = Client(enforce_csrf_checks=True)

        # Missing CSRF cookie & header returns JSON 403 csrf_failed (never HTML)
        no_csrf = self._post_json(guest_client, {"body": "无令牌请求", "expectedAuthorKind": "guest"})
        self.assertEqual(no_csrf.status_code, 403)
        self._assert_no_store(no_csrf)
        self.assertEqual(no_csrf.json()["code"], "csrf_failed")

        me_data = self._bootstrap_csrf(guest_client)
        self.assertIsNone(me_data["user"])
        self.assertIs(me_data["guestCommentsAllowed"], True)
        csrf_token = me_data["csrfToken"]

        # Forged CSRF token returns JSON 403 csrf_failed
        bad_csrf = self._post_json(
            guest_client, {"body": "伪造令牌", "expectedAuthorKind": "guest"}, csrf_token="0" * len(csrf_token)
        )
        self.assertEqual(bad_csrf.status_code, 403)
        self._assert_no_store(bad_csrf)
        self.assertEqual(bad_csrf.json()["code"], "csrf_failed")
        self.assertEqual(Comment.objects.count(), 0)

        # Unknown note slug returns 404 JSON
        unknown_res = self._post_json(
            guest_client,
            {"body": "未知文章", "expectedAuthorKind": "guest"},
            csrf_token=csrf_token,
            url="/api/notes/nonexistent-slug/comments/",
        )
        self.assertEqual(unknown_res.status_code, 404)
        self._assert_no_store(unknown_res)
        self.assertEqual(unknown_res.json()["code"], "note_not_found")

        # Valid guest comment creates row with author=None and canDelete=False
        created_res = self._post_json(
            guest_client,
            {"body": "  第一行\r\n第二行  ", "expectedAuthorKind": "guest", "website": ""},
            csrf_token=csrf_token,
        )
        self.assertEqual(created_res.status_code, 201)
        self._assert_no_store(created_res)
        created_json = created_res.json()
        comment = Comment.objects.get()
        self.assertIsNone(comment.author_id)
        self.assertEqual(comment.body, "第一行\n第二行")
        self.assertEqual(
            created_json,
            {
                "id": comment.pk,
                "body": "第一行\n第二行",
                "createdAt": created_json["createdAt"],
                "canDelete": False,
                "author": {"kind": "guest", "id": None, "displayName": GUEST_DISPLAY_NAME},
            },
        )
        self.assertRegex(created_json["createdAt"], ISO_UTC_Z_RE)
        self.assertEqual(guest_client.get(COMMENTS_URL).json()["items"], [created_json])

    def test_verified_member_create_201_viewer_permissions_and_unverified_403(self) -> None:
        member, member_pw = self._create_user("member-ok@example.com", "竹林听雨", verified=True)
        other, _ = self._create_user("other-ok@example.com", "邻座读者", verified=True)
        admin_user, _ = self._create_user("admin-ok@example.com", "站主管理", verified=True, is_comment_admin=True)
        unverified, _ = self._create_user("unverified@example.com", "待验证用户", verified=False)

        unverified_client = Client(enforce_csrf_checks=True)
        unverified_client.force_login(unverified)
        unverified_csrf = self._bootstrap_csrf(unverified_client)["csrfToken"]
        res_unverified = self._post_json(
            unverified_client, {"body": "未验证发言", "expectedAuthorKind": "member"}, csrf_token=unverified_csrf
        )
        self.assertEqual(res_unverified.status_code, 403)
        self._assert_no_store(res_unverified)
        self.assertEqual(res_unverified.json()["code"], "email_not_verified")
        self.assertEqual(Comment.objects.count(), 0)

        member_client = Client(enforce_csrf_checks=True)
        boot_csrf = self._bootstrap_csrf(member_client)["csrfToken"]
        login_res = member_client.post(
            "/accounts/login/", data=build_login_data(member.email, member_pw), HTTP_X_CSRFTOKEN=boot_csrf
        )
        self.assertEqual(login_res.status_code, 302)
        member_csrf = self._bootstrap_csrf(member_client)["csrfToken"]

        created = self._post_json(
            member_client, {"body": "已验证读者留言", "expectedAuthorKind": "member"}, csrf_token=member_csrf
        )
        self.assertEqual(created.status_code, 201)
        self._assert_no_store(created)
        raw_text = created.content.decode("utf-8")
        self.assertNotIn("member-ok@example.com", raw_text)
        self.assertNotIn("@", raw_text)
        self.assertNotIn(member.username, raw_text)

        payload = created.json()
        self.assertIs(payload["canDelete"], True)
        self.assertEqual(payload["author"], {"kind": "member", "id": member.pk, "displayName": "竹林听雨"})

        self.assertIs(Client().get(COMMENTS_URL).json()["items"][0]["canDelete"], False)
        other_client = Client()
        other_client.force_login(other)
        self.assertIs(other_client.get(COMMENTS_URL).json()["items"][0]["canDelete"], False)
        admin_client = Client()
        admin_client.force_login(admin_user)
        self.assertIs(admin_client.get(COMMENTS_URL).json()["items"][0]["canDelete"], True)

    def test_whitelist_oversized_invisible_chars_and_honeypot_return_400(self) -> None:
        client = Client(enforce_csrf_checks=True)
        csrf_token = self._bootstrap_csrf(client)["csrfToken"]

        for bad_field in ("author", "authorId", "displayName", "role", "isCommentAdmin", "canDelete"):
            with self.subTest(bad_field=bad_field):
                res = self._post_json(
                    client, {"body": "正常内容", "expectedAuthorKind": "guest", bad_field: "spoof"}, csrf_token=csrf_token
                )
                self.assertEqual(res.status_code, 400)
                self.assertEqual(res.json()["code"], "invalid_payload")

        form_res = client.post(
            COMMENTS_URL, data={"body": "表单", "expectedAuthorKind": "guest"}, HTTP_X_CSRFTOKEN=csrf_token
        )
        self.assertEqual(form_res.status_code, 400)
        self.assertEqual(form_res.json()["code"], "invalid_payload")

        oversized = client.post(
            COMMENTS_URL,
            data=b"{" + b" " * (MAX_COMMENT_REQUEST_BYTES + 10) + b"}",
            content_type="application/json",
            HTTP_X_CSRFTOKEN=csrf_token,
        )
        self.assertEqual(oversized.status_code, 400)
        self.assertEqual(oversized.json()["code"], "invalid_payload")

        for bad_raw in (b"{bad-json", b"[]", b"123", b'{"body":"hi"}'):
            res = client.post(COMMENTS_URL, data=bad_raw, content_type="application/json", HTTP_X_CSRFTOKEN=csrf_token)
            self.assertEqual(res.status_code, 400)
            self.assertEqual(res.json()["code"], "invalid_payload")

        bad_website_type = self._post_json(
            client, {"body": "正文", "expectedAuthorKind": "guest", "website": 123}, csrf_token=csrf_token
        )
        self.assertEqual(bad_website_type.status_code, 400)
        self.assertEqual(bad_website_type.json()["code"], "invalid_payload")

        for bad_body in (
            None, 42, "", "   \r\n\t\u3000  ", "\u200b\u200b", "\u200d", "\ufe0e", "\ufe0f",
            "\u200d  \ufe0f", "正常\u200b夹带零宽", "正常\x00空字节", "正常\x07控制符", "行分隔\u2028符", "中" * 1001,
        ):
            with self.subTest(bad_body=repr(bad_body)[:24]):
                res = self._post_json(
                    client, {"body": bad_body, "expectedAuthorKind": "guest"}, csrf_token=csrf_token
                )
                self.assertEqual(res.status_code, 400)
                self.assertEqual(res.json()["code"], "invalid_body")

        # Repeated honeypot hits consume quota and eventually trigger 429 without DB writes
        with override_settings(ALLAUTH_TRUSTED_PROXY_COUNT=0, COMMENT_RATE_LIMITS={"guest_ip": ((2, 60),)}):
            for hp_val in ("https://spam.invalid", "   "):
                hp_res = self._post_json(
                    client, {"body": "机器人内容", "expectedAuthorKind": "guest", "website": hp_val},
                    csrf_token=csrf_token, REMOTE_ADDR="198.51.100.200",
                )
                self.assertEqual(hp_res.status_code, 400)
                self.assertEqual(hp_res.json()["code"], "honeypot_triggered")
            hp_429 = self._post_json(
                client, {"body": "机器人内容", "expectedAuthorKind": "guest", "website": "bot"},
                csrf_token=csrf_token, REMOTE_ADDR="198.51.100.200",
            )
            self.assertEqual(hp_429.status_code, 429)
            self.assertEqual(hp_429.json()["code"], "rate_limited")

        self.assertEqual(Comment.objects.count(), 0)

        # Composite ZWJ & variation-selector emojis and exact 1000-char body succeed
        emoji_body = "赞 👨‍💻 🏳️‍🌈 ❤️"
        ok_emoji = self._post_json(
            client, {"body": emoji_body, "expectedAuthorKind": "guest"}, csrf_token=csrf_token
        )
        self.assertEqual(ok_emoji.status_code, 201)
        self.assertEqual(ok_emoji.json()["body"], emoji_body)

        ok_1000 = self._post_json(
            client, {"body": "字" * 1000, "expectedAuthorKind": "guest"}, csrf_token=csrf_token
        )
        self.assertEqual(ok_1000.status_code, 201)
        self.assertEqual(Comment.objects.count(), 2)

    def test_expected_author_kind_mismatch_returns_409_without_side_effects(self) -> None:
        member, _ = self._create_user("drift@example.com", "跨标签读者", verified=True)

        anon_client = Client(enforce_csrf_checks=True)
        anon_csrf = self._bootstrap_csrf(anon_client)["csrfToken"]
        res_anon_mismatch = self._post_json(
            anon_client, {"body": "会话已过期", "expectedAuthorKind": "member"}, csrf_token=anon_csrf
        )
        self.assertEqual(res_anon_mismatch.status_code, 409)
        self._assert_no_store(res_anon_mismatch)
        self.assertEqual(
            res_anon_mismatch.json(),
            {
                "code": "author_state_changed",
                "actualAuthorKind": "guest",
                "message": "当前登录状态已变化，请确认后再提交评论。",
            },
        )

        auth_client = Client(enforce_csrf_checks=True)
        auth_client.force_login(member)
        auth_csrf = self._bootstrap_csrf(auth_client)["csrfToken"]
        res_auth_mismatch = self._post_json(
            auth_client, {"body": "另一标签已登录", "expectedAuthorKind": "guest"}, csrf_token=auth_csrf
        )
        self.assertEqual(res_auth_mismatch.status_code, 409)
        self.assertEqual(res_auth_mismatch.json()["actualAuthorKind"], "member")
        self.assertEqual(Comment.objects.count(), 0)

    @override_settings(ALLOW_GUEST_COMMENTS=False)
    def test_allow_guest_comments_false_blocks_guests_while_members_succeed(self) -> None:
        member, _ = self._create_user("allowed-member@example.com", "已认证成员", verified=True)

        guest_client = Client(enforce_csrf_checks=True)
        guest_me = self._bootstrap_csrf(guest_client)
        self.assertIs(guest_me["guestCommentsAllowed"], False)

        guest_res = self._post_json(
            guest_client, {"body": "访客尝试发言", "expectedAuthorKind": "guest"}, csrf_token=guest_me["csrfToken"]
        )
        self.assertEqual(guest_res.status_code, 403)
        self._assert_no_store(guest_res)
        self.assertEqual(guest_res.json()["code"], "guest_comments_disabled")
        self.assertEqual(Comment.objects.count(), 0)

        member_client = Client(enforce_csrf_checks=True)
        member_client.force_login(member)
        member_me = self._bootstrap_csrf(member_client)
        self.assertIs(member_me["guestCommentsAllowed"], False)
        member_res = self._post_json(
            member_client,
            {"body": "开关关闭后登录用户仍可发言", "expectedAuthorKind": "member"},
            csrf_token=member_me["csrfToken"],
        )
        self.assertEqual(member_res.status_code, 201)
        self.assertEqual(Comment.objects.count(), 1)

    def test_rate_limiting_429_and_xff_spoof_resistance_for_proxy_0_and_1(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ceilf6-comment-rl-") as tmp_dir:
            cache_cfg = {
                "default": {
                    "BACKEND": FILEBASED_CACHE_BACKEND,
                    "LOCATION": tmp_dir,
                    "OPTIONS": settings.CACHES["default"]["OPTIONS"],
                }
            }
            limits = {"guest_ip": ((2, 60),), "member_user": ((2, 60),), "member_ip": ((5, 60),)}

            # Case 1: ALLAUTH_TRUSTED_PROXY_COUNT=0 ignores spoofed X-Forwarded-For completely
            with override_settings(ALLAUTH_TRUSTED_PROXY_COUNT=0, CACHES=cache_cfg, COMMENT_RATE_LIMITS=limits):
                c0 = Client(enforce_csrf_checks=True)
                csrf0 = self._bootstrap_csrf(c0, REMOTE_ADDR="203.0.113.9")["csrfToken"]
                for idx in range(2):
                    ok = self._post_json(
                        c0,
                        {"body": f"直连留言 {idx}", "expectedAuthorKind": "guest"},
                        csrf_token=csrf0,
                        REMOTE_ADDR="203.0.113.9",
                        HTTP_X_FORWARDED_FOR=f"198.51.100.{idx + 1}",
                    )
                    self.assertEqual(ok.status_code, 201)
                blocked0 = self._post_json(
                    c0,
                    {"body": "伪造XFF企图绕过", "expectedAuthorKind": "guest"},
                    csrf_token=csrf0,
                    REMOTE_ADDR="203.0.113.9",
                    HTTP_X_FORWARDED_FOR="198.51.100.250",
                )
                self.assertEqual(blocked0.status_code, 429)
                self._assert_no_store(blocked0)
                self.assertEqual(blocked0.json()["code"], "rate_limited")
                self.assertGreaterEqual(int(blocked0["Retry-After"]), 1)

            # Case 2: ALLAUTH_TRUSTED_PROXY_COUNT=1 takes rightmost hop, blocking prepended XFF spoofing
            with override_settings(ALLAUTH_TRUSTED_PROXY_COUNT=1, CACHES=cache_cfg, COMMENT_RATE_LIMITS=limits):
                c1 = Client(enforce_csrf_checks=True)
                csrf1 = self._bootstrap_csrf(c1, REMOTE_ADDR="127.0.0.1")["csrfToken"]
                for idx in range(2):
                    ok = self._post_json(
                        c1,
                        {"body": f"反代留言 {idx}", "expectedAuthorKind": "guest"},
                        csrf_token=csrf1,
                        REMOTE_ADDR="127.0.0.1",
                        HTTP_X_FORWARDED_FOR=f"10.0.0.{idx}, 198.51.100.77",
                    )
                    self.assertEqual(ok.status_code, 201)
                blocked1 = self._post_json(
                    c1,
                    {"body": "前置随机IP仍被拦", "expectedAuthorKind": "guest"},
                    csrf_token=csrf1,
                    REMOTE_ADDR="127.0.0.1",
                    HTTP_X_FORWARDED_FOR="1.2.3.4, 5.6.7.8, 198.51.100.77",
                )
                self.assertEqual(blocked1.status_code, 429)
                self.assertGreaterEqual(int(blocked1["Retry-After"]), 1)

                c_other = Client(enforce_csrf_checks=True)
                csrf_other = self._bootstrap_csrf(c_other)["csrfToken"]
                ok_other = self._post_json(
                    c_other,
                    {"body": "独立真实IP不受影响", "expectedAuthorKind": "guest"},
                    csrf_token=csrf_other,
                    REMOTE_ADDR="127.0.0.1",
                    HTTP_X_FORWARDED_FOR="198.51.100.88",
                )
                self.assertEqual(ok_other.status_code, 201)

    def test_concurrent_sqlite_file_writes_succeed_and_persist_across_reconnect(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ceilf6-comments-wal-") as tmp_dir:
            tmp_path = Path(tmp_dir)
            env = {
                **os.environ,
                "DJANGO_DOTENV_PATH": str(tmp_path / ".env.empty"),
                "DJANGO_DEBUG": "true",
                "DJANGO_ALLOWED_HOSTS": "127.0.0.1,localhost",
                "ALLOW_GUEST_COMMENTS": "true",
                "DJANGO_SETTINGS_MODULE": "config.settings",
                "SQLITE_PATH": str(tmp_path / "concurrent_comments.sqlite3"),
                "DJANGO_CACHE_PATH": str(tmp_path / "cache"),
                "EMAIL_FILE_PATH": str(tmp_path / "mail"),
            }
            run_py = lambda args: subprocess.run(
                [sys.executable, *args],
                cwd=str(SERVER_DIR),
                env=env,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            migrate_proc = run_py([str(SERVER_DIR / "manage.py"), "migrate", "--noinput"])
            self.assertEqual(migrate_proc.returncode, 0, msg=migrate_proc.stderr)

            write_proc = run_py(["-c", _CONCURRENT_WORKER_SCRIPT])
            self.assertEqual(write_proc.returncode, 0, msg=write_proc.stderr)
            write_result = json.loads(write_proc.stdout.strip().splitlines()[-1])
            self.assertEqual(write_result["errors"], [])
            self.assertEqual([code for _, code, _ in write_result["statuses"]], [201] * 8)

            read_proc = run_py(["-c", _CONCURRENT_READBACK_SCRIPT])
            self.assertEqual(read_proc.returncode, 0, msg=read_proc.stderr)
            read_result = json.loads(read_proc.stdout.strip().splitlines()[-1])
            self.assertEqual(read_result["status"], 200)
            items = read_result["payload"]["items"]
            self.assertEqual({item["body"] for item in items}, {f"并发评论 #{i}" for i in range(8)})
            self.assertEqual(sum(1 for i in items if i["author"]["kind"] == "member"), 4)
            self.assertEqual(sum(1 for i in items if i["author"]["kind"] == "guest"), 4)
