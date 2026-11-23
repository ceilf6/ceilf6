"""Tests for POST /api/comments/<id>/delete/, concurrency safety, and CommentAdmin moderation."""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from types import ModuleType
from typing import Any
from unittest.mock import patch

from allauth.account.models import EmailAddress
from django.contrib import admin
from django.core.cache import cache
from django.core.management import call_command
from django.middleware.csrf import get_token
from django.test import Client, RequestFactory, TestCase, override_settings
from django.urls import include, path

from accounts.models import User
from accounts.tests.helpers import _PW_KEY, build_login_data, gen_test_credential
from accounts.views import me_view
from comments.models import GUEST_DISPLAY_NAME, Comment
from comments.views import (
    MAX_COMMENT_REQUEST_BYTES,
    MAX_SQLITE_INT64,
    delete_comment_view,
    note_comments_view,
)
from config.env import SERVER_DIR
from config.http import empty_no_store
from config.middleware import NO_STORE_CACHE_CONTROL
from config.views import health_check

SLUG_A = "harness-cold-start"
SLUG_B = "cc-source-analysis"
_PW_STDIN_OPT = "--" + _PW_KEY + "-stdin"

_CONCURRENT_DELETE_SCRIPT = """
import json, threading, django
django.setup()
from allauth.account.models import EmailAddress
from django.db import connections
from django.test import Client
from accounts.models import User
from accounts.tests.helpers import gen_test_credential
from comments.models import Comment

author = User.objects.create_user("u_conc_del_a", "conc-a@example.com", gen_test_credential(), display_name="并发作者")
EmailAddress.objects.create(user=author, email=author.email, verified=True, primary=True)
mod = User.objects.create_user(
    "u_conc_del_m", "conc-m@example.com", gen_test_credential(),
    display_name="并发站主", is_comment_admin=True, is_staff=True,
)
EmailAddress.objects.create(user=mod, email=mod.email, verified=True, primary=True)
target_id = Comment.objects.create(note_slug="harness-cold-start", author=author, body="待并发删除评论").pk
connections.close_all()

barrier, errors, results, lock = threading.Barrier(2), [], [], threading.Lock()
actors = [author, mod]
def worker(idx):
    try:
        c = Client(enforce_csrf_checks=True, HTTP_HOST="127.0.0.1")
        c.force_login(actors[idx])
        csrf = c.get("/api/me/").json()["csrfToken"]
        barrier.wait(timeout=10)
        res = c.post(f"/api/comments/{target_id}/delete/", data=b"", content_type="", HTTP_X_CSRFTOKEN=csrf)
        with lock:
            results.append({"status": res.status_code, "body": res.content.decode("utf-8")})
    except BaseException as exc:
        with lock:
            errors.append(repr(exc))
    finally:
        connections.close_all()

threads = [threading.Thread(target=worker, args=(i,)) for i in range(2)]
for t in threads: t.start()
for t in threads: t.join(timeout=15)
remaining = Comment.objects.filter(pk=target_id).count()
connections.close_all()
print(json.dumps({"errors": errors, "results": results, "remaining": remaining}))
"""


class CommentDeleteAndModerationTests(TestCase):
    def setUp(self) -> None:
        super().setUp()
        cache.clear()

    def _assert_no_store(self, response: Any) -> None:
        self.assertEqual(response["Cache-Control"], NO_STORE_CACHE_CONTROL)
        self.assertIn("Cookie", response["Vary"])

    def _create_user(
        self, email_addr: str, display_name: str, *, verified: bool = True
    ) -> tuple[User, str]:
        pw = gen_test_credential()
        uname = f"u_{email_addr.split('@', 1)[0].replace('-', '_')}"
        user = User.objects.create_user(uname, email_addr, pw, display_name=display_name)
        EmailAddress.objects.create(user=user, email=user.email, verified=verified, primary=True)
        return user, pw

    def _csrf_client(self, user: User | None = None) -> tuple[Client, str]:
        client = Client(enforce_csrf_checks=True)
        if user is not None:
            client.force_login(user)
        res = client.get("/api/me/")
        self.assertEqual(res.status_code, 200)
        return client, res.json()["csrfToken"]

    def _post_delete(
        self,
        client: Client,
        comment_id: str | int,
        *,
        csrf_token: str | None = None,
        data: bytes | str = b"",
        content_type: str = "",
        **extra: Any,
    ) -> Any:
        headers = dict(extra)
        if csrf_token is not None:
            headers["HTTP_X_CSRFTOKEN"] = csrf_token
        return client.post(
            f"/api/comments/{comment_id}/delete/", data=data, content_type=content_type, **headers
        )

    def test_method_gate_and_csrf_protection(self) -> None:
        helper_res = empty_no_store()
        self.assertEqual((helper_res.status_code, helper_res.content), (204, b""))
        self._assert_no_store(helper_res)

        author, _ = self._create_user("csrf-author@example.com", "删评作者")
        comment = Comment.objects.create(note_slug=SLUG_A, author=author, body="受保护评论")
        url = f"/api/comments/{comment.pk}/delete/"

        raw_client = Client(enforce_csrf_checks=True)
        raw_client.force_login(author)
        for method in ("delete", "get", "head", "put", "patch", "options"):
            with self.subTest(method=method):
                res_405 = getattr(raw_client, method)(url)
                self.assertEqual((res_405.status_code, res_405["Allow"]), (405, "POST"))
                self._assert_no_store(res_405)
                if method != "head":
                    self.assertEqual(res_405.json()["code"], "method_not_allowed")

        no_csrf = self._post_delete(raw_client, comment.pk)
        self.assertEqual((no_csrf.status_code, no_csrf.json()["code"]), (403, "csrf_failed"))
        self._assert_no_store(no_csrf)

        authed_client, csrf_token = self._csrf_client(author)
        bad_csrf = self._post_delete(authed_client, comment.pk, csrf_token="0" * len(csrf_token))
        self.assertEqual((bad_csrf.status_code, bad_csrf.json()["code"]), (403, "csrf_failed"))
        self._assert_no_store(bad_csrf)
        self.assertTrue(Comment.objects.filter(pk=comment.pk).exists())

    def test_delete_payload_compatibility_and_validation(self) -> None:
        author, _ = self._create_user("payload-author@example.com", "载荷测试者")
        client, csrf_token = self._csrf_client(author)

        for body, ctype in ((b"", ""), ("{}", "application/json")):
            c_ok = Comment.objects.create(note_slug=SLUG_A, author=author, body="合法删评请求")
            res_ok = self._post_delete(
                client, c_ok.pk, csrf_token=csrf_token, data=body, content_type=ctype
            )
            self.assertEqual((res_ok.status_code, res_ok.content), (204, b""))
            self._assert_no_store(res_ok)
            self.assertFalse(Comment.objects.filter(pk=c_ok.pk).exists())

        c_keep = Comment.objects.create(note_slug=SLUG_A, author=author, body="非法载荷保留")
        bad_requests: list[tuple[bytes | str, str, dict[str, str]]] = [
            (json.dumps({"force": True}), "application/json", {}),
            ("[]", "application/json", {}),
            ("NaN", "application/json", {}),
            ("{bad", "application/json", {}),
            (b"\xff\xfe", "application/json", {}),
            ("force=1", "application/x-www-form-urlencoded", {}),
            ("{}", "text/plain", {}),
            (b" " * (MAX_COMMENT_REQUEST_BYTES + 1), "application/json", {}),
            (b"", "", {"CONTENT_LENGTH": str(MAX_COMMENT_REQUEST_BYTES + 1)}),
            (b"", "", {"CONTENT_LENGTH": "-1"}),
            (b"", "", {"CONTENT_LENGTH": "invalid"}),
            (b"", "", {"CONTENT_LENGTH": "9" * 5000}),
        ]
        for body, ctype, extra in bad_requests:
            with self.subTest(ctype=ctype, extra=extra, size=len(body)):
                res_bad = self._post_delete(
                    client, c_keep.pk, csrf_token=csrf_token, data=body, content_type=ctype, **extra
                )
                self.assertEqual(res_bad.status_code, 400)
                self._assert_no_store(res_bad)
                self.assertEqual(res_bad.json()["code"], "invalid_payload")

        multipart_res = client.post(
            f"/api/comments/{c_keep.pk}/delete/", HTTP_X_CSRFTOKEN=csrf_token
        )
        self.assertEqual((multipart_res.status_code, multipart_res.json()["code"]), (400, "invalid_payload"))
        self.assertTrue(Comment.objects.filter(pk=c_keep.pk).exists())

    def test_invalid_and_edge_comment_ids_return_404_json(self) -> None:
        author, _ = self._create_user("edge-id@example.com", "边界读者")
        existing = Comment.objects.create(note_slug=SLUG_A, author=author, body="真实评论")
        client, csrf_token = self._csrf_client(author)

        bad_ids = (
            str(existing.pk + 9999),
            "0",
            "01",
            f"0{existing.pk}",
            "-5",
            "abc",
            "12ab",
            "١٢٣",
            str(MAX_SQLITE_INT64),
            str(MAX_SQLITE_INT64 + 1),
            "9" * 5000,
        )
        for raw_id in bad_ids:
            with self.subTest(raw_id=raw_id[:32]):
                res = self._post_delete(client, raw_id, csrf_token=csrf_token)
                self.assertEqual((res.status_code, res["Content-Type"]), (404, "application/json"))
                self._assert_no_store(res)
                self.assertEqual(res.json()["code"], "comment_not_found")
        self.assertTrue(Comment.objects.filter(pk=existing.pk).exists())

    def test_role_permission_matrix_and_revoke_flow(self) -> None:
        member_a, _ = self._create_user("member-a@example.com", "读者甲")
        member_b, _ = self._create_user("member-b@example.com", "读者乙")
        unverified, _ = self._create_user("unverified-del@example.com", "未验证用户", verified=False)
        inactive, _ = self._create_user("inactive-del@example.com", "停用账号")
        owner, owner_pw = self._create_user("owner-gov@example.com", "站主惊鸿")
        call_command("grant_comment_admin", email=owner.email, stdout=io.StringIO(), stderr=io.StringIO())
        owner.refresh_from_db()
        self.assertFalse(owner.is_superuser)
        self.assertTrue(owner.is_comment_admin)

        guest_client, guest_csrf = self._csrf_client()
        guest_create = guest_client.post(
            f"/api/notes/{SLUG_A}/comments/",
            data=json.dumps({"body": "访客首评", "expectedAuthorKind": "guest"}),
            content_type="application/json",
            HTTP_X_CSRFTOKEN=guest_csrf,
        )
        self.assertEqual(guest_create.status_code, 201)
        guest_comment_id = guest_create.json()["id"]
        comment_a = Comment.objects.create(note_slug=SLUG_A, author=member_a, body="甲的评论")
        comment_b = Comment.objects.create(note_slug=SLUG_A, author=member_b, body="乙的评论")

        for target_id in (guest_comment_id, comment_a.pk, "non-numeric"):
            res_401 = self._post_delete(guest_client, target_id, csrf_token=guest_csrf)
            self.assertEqual((res_401.status_code, res_401.json()["code"]), (401, "authentication_required"))
            self._assert_no_store(res_401)

        inactive_client, inactive_csrf = self._csrf_client(inactive)
        inactive.is_active = False
        inactive.save(update_fields=["is_active"])
        res_inactive = self._post_delete(inactive_client, comment_a.pk, csrf_token=inactive_csrf)
        self.assertEqual((res_inactive.status_code, res_inactive.json()["code"]), (401, "authentication_required"))

        rf = RequestFactory()
        rf_get = rf.get("/api/me/")
        rf_token = get_token(rf_get)
        rf_post = rf.generic("POST", f"/api/comments/{comment_a.pk}/delete/", b"")
        rf_post.COOKIES["csrftoken"] = rf_get.META["CSRF_COOKIE"]
        rf_post.META["HTTP_X_CSRFTOKEN"] = rf_token
        rf_post.user = inactive
        self.assertEqual(delete_comment_view(rf_post, str(comment_a.pk)).status_code, 401)

        unv_client, unv_csrf = self._csrf_client(unverified)
        res_unv = self._post_delete(unv_client, comment_a.pk, csrf_token=unv_csrf)
        self.assertEqual((res_unv.status_code, res_unv.json()["code"]), (403, "email_not_verified"))
        self._assert_no_store(res_unv)

        # Ordinary member A: own -> 204 & readback gone & repeat -> 404; member B / guest -> 403
        client_a, csrf_a = self._csrf_client(member_a)
        del_own = self._post_delete(client_a, comment_a.pk, csrf_token=csrf_a)
        self.assertEqual((del_own.status_code, del_own.content), (204, b""))
        self._assert_no_store(del_own)
        list_ids = [i["id"] for i in client_a.get(f"/api/notes/{SLUG_A}/comments/").json()["items"]]
        self.assertNotIn(comment_a.pk, list_ids)
        self.assertEqual(
            self._post_delete(client_a, comment_a.pk, csrf_token=csrf_a).status_code, 404
        )
        for forbidden_id in (comment_b.pk, guest_comment_id):
            res_403 = self._post_delete(client_a, forbidden_id, csrf_token=csrf_a)
            self.assertEqual((res_403.status_code, res_403.json()["code"]), (403, "permission_denied"))
            self._assert_no_store(res_403)
            self.assertTrue(Comment.objects.filter(pk=forbidden_id).exists())

        # Comment moderator deletes guest, member B, and own comments across SLUG_A and SLUG_B
        comment_b_slug_b = Comment.objects.create(note_slug=SLUG_B, author=member_b, body="乙在篇B评论")
        owner_own = Comment.objects.create(note_slug=SLUG_B, author=owner, body="站主本人评")
        owner_client, owner_csrf = self._csrf_client(owner)
        for target_id, slug in (
            (guest_comment_id, SLUG_A),
            (comment_b_slug_b.pk, SLUG_B),
            (owner_own.pk, SLUG_B),
        ):
            mod_res = self._post_delete(owner_client, target_id, csrf_token=owner_csrf)
            self.assertEqual((mod_res.status_code, mod_res.content), (204, b""))
            self._assert_no_store(mod_res)
            remaining = [i["id"] for i in owner_client.get(f"/api/notes/{slug}/comments/").json()["items"]]
            self.assertNotIn(target_id, remaining)

        # Revoke comment admin -> session purged (401), relogin as regular member -> 403 on others
        guest_after = Comment.objects.create(note_slug=SLUG_A, author=None, body="撤销后访客评")
        call_command("grant_comment_admin", email=owner.email, revoke=True, stdout=io.StringIO(), stderr=io.StringIO())
        purged = self._post_delete(owner_client, comment_b.pk, csrf_token=owner_csrf)
        self.assertEqual((purged.status_code, purged.json()["code"]), (401, "authentication_required"))

        boot_csrf = owner_client.get("/api/me/").json()["csrfToken"]
        self.assertEqual(
            owner_client.post(
                "/accounts/login/",
                data=build_login_data(owner.email, owner_pw),
                HTTP_X_CSRFTOKEN=boot_csrf,
            ).status_code,
            302,
        )
        relogin_csrf = owner_client.get("/api/me/").json()["csrfToken"]
        for protected_id in (comment_b.pk, guest_after.pk):
            denied = self._post_delete(owner_client, protected_id, csrf_token=relogin_csrf)
            self.assertEqual((denied.status_code, denied.json()["code"]), (403, "permission_denied"))
            self.assertTrue(Comment.objects.filter(pk=protected_id).exists())

    def test_concurrent_double_delete_on_wal_sqlite_returns_204_and_404(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ceilf6-del-wal-") as tmp_dir:
            tmp_path = Path(tmp_dir)
            env = {
                **os.environ,
                "DJANGO_DOTENV_PATH": str(tmp_path / ".env.empty"),
                "DJANGO_DEBUG": "true",
                "DJANGO_ALLOWED_HOSTS": "127.0.0.1,localhost",
                "DJANGO_SETTINGS_MODULE": "config.settings",
                "SQLITE_PATH": str(tmp_path / "concurrent_delete.sqlite3"),
                "DJANGO_CACHE_PATH": str(tmp_path / "cache"),
                "EMAIL_FILE_PATH": str(tmp_path / "mail"),
            }
            run_py = lambda args: subprocess.run(
                [sys.executable, *args], cwd=str(SERVER_DIR), env=env,
                capture_output=True, text=True, timeout=30, check=False,
            )
            mig = run_py([str(SERVER_DIR / "manage.py"), "migrate", "--noinput"])
            self.assertEqual(mig.returncode, 0, msg=mig.stderr)

            proc = run_py(["-c", _CONCURRENT_DELETE_SCRIPT])
            self.assertEqual(proc.returncode, 0, msg=proc.stderr)
            payload = json.loads(proc.stdout.strip().splitlines()[-1])
            self.assertEqual((payload["errors"], payload["remaining"]), ([], 0))
            self.assertEqual(sorted(item["status"] for item in payload["results"]), [204, 404])
            for item in payload["results"]:
                if item["status"] == 204:
                    self.assertEqual(item["body"], "")
                else:
                    self.assertEqual(json.loads(item["body"])["code"], "comment_not_found")

    def test_custom_admin_path_end_to_end_moderation(self) -> None:
        custom_admin_prefix = "ops-console/"
        custom_urlconf = ModuleType("test_comment_moderation_urls")
        custom_urlconf.urlpatterns = [  # type: ignore[attr-defined]
            path(custom_admin_prefix, admin.site.urls),
            path("accounts/", include("allauth.account.urls")),
            path("api/health/", health_check, name="api-health"),
            path("api/me/", me_view, name="api-me"),
            path("api/notes/<str:slug>/comments/", note_comments_view, name="api-note-comments"),
            path("api/comments/<str:comment_id>/delete/", delete_comment_view, name="api-comment-delete"),
        ]

        owner_pw, member_pw = gen_test_credential(), gen_test_credential()
        for email_addr, display, pw in (
            ("owner-e2e@example.com", "站主巡检员", owner_pw),
            ("reader-e2e@example.com", "清风读者", member_pw),
        ):
            with patch("sys.stdin", io.StringIO(f"{pw}\n")):
                call_command(
                    "ensure_verified_user", "--email", email_addr, "--display-name", display,
                    _PW_STDIN_OPT, stdout=io.StringIO(),
                )
        call_command("grant_comment_admin", email="owner-e2e@example.com", stdout=io.StringIO(), stderr=io.StringIO())
        reader = User.objects.get(email="reader-e2e@example.com")

        long_body = "首行标记\n" + ("长评内容片段" * 12)
        c_guest_a = Comment.objects.create(note_slug=SLUG_A, author=None, body="待治理访客广告甲")
        c_member_a = Comment.objects.create(note_slug=SLUG_A, author=reader, body=long_body)
        c_guest_b = Comment.objects.create(note_slug=SLUG_B, author=None, body="跨篇批量清理乙")
        changelist_path = f"/{custom_admin_prefix}comments/comment/"
        add_path = f"/{custom_admin_prefix}comments/comment/add/"

        with override_settings(DJANGO_ADMIN_PATH=custom_admin_prefix, ROOT_URLCONF=custom_urlconf):
            self.assertEqual(self.client.get("/admin/comments/comment/").status_code, 404)

            member_client = Client()
            self.assertEqual(
                member_client.post("/accounts/login/", data=build_login_data("reader-e2e@example.com", member_pw)).status_code,
                302,
            )
            member_admin_res = member_client.get(changelist_path, follow=True)
            self.assertEqual((member_admin_res.redirect_chain, member_admin_res.status_code), ([], 403))

            owner_client = Client()
            unauth_entry = owner_client.get(changelist_path)
            self.assertEqual(unauth_entry.status_code, 302)
            login_ok = owner_client.post(
                unauth_entry["Location"],
                data=build_login_data("owner-e2e@example.com", owner_pw, next_url=changelist_path),
            )
            self.assertEqual((login_ok.status_code, login_ok["Location"]), (302, changelist_path))

            list_res = owner_client.get(changelist_path)
            self.assertEqual(list_res.status_code, 200)
            self.assertContains(list_res, GUEST_DISPLAY_NAME)
            self.assertContains(list_res, "清风读者")
            self.assertNotContains(list_res, "reader-e2e@example.com")
            self.assertContains(list_res, f"{(' '.join(long_body.split()))[:60]}…")

            filtered_res = owner_client.get(f"{changelist_path}?note_slug={SLUG_A}")
            self.assertContains(filtered_res, "待治理访客广告甲")
            self.assertNotContains(filtered_res, "跨篇批量清理乙")

            search_res = owner_client.get(f"{changelist_path}?q=跨篇批量")
            self.assertContains(search_res, "跨篇批量清理乙")
            self.assertNotContains(search_res, "待治理访客广告甲")

            detail_path = f"{changelist_path}{c_member_a.pk}/change/"
            detail_res = owner_client.get(detail_path)
            self.assertEqual(detail_res.status_code, 200)
            self.assertNotContains(detail_res, 'name="_save"')
            self.assertEqual(owner_client.post(detail_path, data={"note_slug": SLUG_A, "body": "后台篡改"}).status_code, 403)
            c_member_a.refresh_from_db()
            self.assertEqual(c_member_a.body, long_body)
            self.assertEqual(owner_client.get(add_path).status_code, 403)
            self.assertEqual(owner_client.post(add_path, data={}).status_code, 403)

            single_del = owner_client.post(f"{changelist_path}{c_guest_a.pk}/delete/", data={"post": "yes"})
            self.assertEqual(single_del.status_code, 302)
            self.assertFalse(Comment.objects.filter(pk=c_guest_a.pk).exists())
            self.assertEqual(
                [i["id"] for i in Client().get(f"/api/notes/{SLUG_A}/comments/").json()["items"]],
                [c_member_a.pk],
            )

            bulk_del = owner_client.post(
                changelist_path,
                data={
                    "action": "delete_selected",
                    "_selected_action": [str(c_member_a.pk), str(c_guest_b.pk)],
                    "post": "yes",
                },
            )
            self.assertEqual((bulk_del.status_code, Comment.objects.count()), (302, 0))
            self.assertEqual(Client().get(f"/api/notes/{SLUG_A}/comments/").json()["items"], [])
            self.assertEqual(Client().get(f"/api/notes/{SLUG_B}/comments/").json()["items"], [])
