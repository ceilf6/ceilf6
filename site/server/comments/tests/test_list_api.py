"""API tests for GET /api/notes/{slug}/comments/ pagination, cursors, and privacy."""

from __future__ import annotations

import re

from django.db import connection
from django.test import Client, RequestFactory, TestCase
from django.test.utils import CaptureQueriesContext

from accounts.models import User
from accounts.tests.helpers import gen_test_credential
from comments.models import GUEST_DISPLAY_NAME, Comment
from comments.views import MAX_SQLITE_INT64, note_comments_view
from config.middleware import NO_STORE_CACHE_CONTROL

ISO_UTC_Z_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$")


class NoteCommentsListApiTests(TestCase):
    def setUp(self) -> None:
        super().setUp()
        self.factory = RequestFactory()

    def _assert_no_store_headers(self, response) -> None:
        self.assertEqual(response["Cache-Control"], NO_STORE_CACHE_CONTROL)
        self.assertIn("Cookie", response["Vary"])

    def test_method_guard_head_and_unknown_slugs_return_json_with_no_store_headers(
        self,
    ) -> None:
        csrf_client = Client(enforce_csrf_checks=True)
        url = "/api/notes/harness-cold-start/comments/"

        for method_name in ("put", "patch", "delete", "options"):
            with self.subTest(method=method_name):
                res_405 = getattr(csrf_client, method_name)(url)
                self.assertEqual(res_405.status_code, 405)
                self.assertEqual(res_405["Allow"], "GET, HEAD, POST")
                self._assert_no_store_headers(res_405)
                self.assertEqual(
                    res_405.json(),
                    {
                        "code": "method_not_allowed",
                        "message": "Method not allowed.",
                    },
                )

        head_ok = csrf_client.head(url)
        self.assertEqual(head_ok.status_code, 200)
        self._assert_no_store_headers(head_ok)
        self.assertEqual(head_ok.content, b"")

        for unknown_slug in (
            "nonexistent-note",
            "harness-cold-start.md",
            "unknown..slug",
            "UPPERCASE-SLUG",
        ):
            with self.subTest(slug=unknown_slug):
                res_404 = csrf_client.get(f"/api/notes/{unknown_slug}/comments/")
                self.assertEqual(res_404.status_code, 404)
                self._assert_no_store_headers(res_404)
                self.assertEqual(
                    res_404.json(),
                    {
                        "code": "note_not_found",
                        "message": "未找到对应的札记。",
                    },
                )

    def test_invalid_overflow_and_5000_digit_cursors_return_400_json_never_500(
        self,
    ) -> None:
        base_url = "/api/notes/harness-cold-start/comments/"
        bad_queries = [
            "before=",
            "before=0",
            "before=000",
            f"before={'0' * 5000}",  # exceeds Python int_max_str_digits if unstripped
            "before=-1",
            "before=%2B5",
            "before=abc",
            "before=12.5",
            "before=10%20",
            "before=%EF%BC%91%EF%BC%92%EF%BC%93",  # fullwidth １２３
            "before=%C2%B2",  # superscript ²
            "before=10&before=20",
            f"before={MAX_SQLITE_INT64 + 1}",
            f"before={1 << 128}",
            f"before={'9' * 5000}",  # exceeds Python 4300-digit int_max_str_digits
        ]
        for query in bad_queries:
            with self.subTest(query_len=len(query), prefix=query[:24]):
                res = self.client.get(f"{base_url}?{query}")
                self.assertEqual(res.status_code, 400)
                self._assert_no_store_headers(res)
                self.assertEqual(
                    res.json(),
                    {
                        "code": "invalid_cursor",
                        "message": "分页游标参数无效。",
                    },
                )

        Comment.objects.create(
            note_slug="harness-cold-start",
            author=None,
            body="最大有符号 64 位整数边界内正常返回",
        )
        max_ok = self.client.get(f"{base_url}?before={MAX_SQLITE_INT64}")
        self.assertEqual(max_ok.status_code, 200)
        self._assert_no_store_headers(max_ok)
        self.assertEqual(len(max_ok.json()["items"]), 1)
        self.assertIsNone(max_ok.json()["nextBefore"])

    def test_cursor_pagination_45_mixed_comments_no_n_plus_1_and_slug_isolation(
        self,
    ) -> None:
        authors = [
            User.objects.create_user(
                f"u_pag_{idx}",
                f"pag-{idx}@example.com",
                gen_test_credential(),
                display_name=f"读者{idx}",
            )
            for idx in range(4)
        ]

        # Verify authenticated real Client executes constant SQL queries for 1 vs 45 comments
        auth_client = Client()
        auth_client.force_login(authors[0])
        url = "/api/notes/harness-cold-start/comments/"

        first_row = Comment.objects.create(
            note_slug="harness-cold-start",
            author=None,
            body="目标札记第 1 条评论",
        )
        with CaptureQueriesContext(connection) as single_row_queries:
            res_single = auth_client.get(url)
        self.assertEqual(res_single.status_code, 200)

        target_ids: list[int] = [first_row.pk]
        for idx in range(1, 45):
            author = None if idx % 3 == 0 else authors[idx % len(authors)]
            row = Comment.objects.create(
                note_slug="harness-cold-start",
                author=author,
                body=f"目标札记第 {idx + 1} 条评论",
            )
            target_ids.append(row.pk)

        for idx in range(12):
            Comment.objects.create(
                note_slug="v8-gc-source",
                author=authors[idx % len(authors)],
                body=f"其他札记干扰评论 {idx + 1}",
            )

        with CaptureQueriesContext(connection) as full_page_queries:
            res_auth_page = auth_client.get(url)
        self.assertEqual(res_auth_page.status_code, 200)
        self.assertEqual(len(single_row_queries), len(full_page_queries))

        collected_ids: list[int] = []

        # Anonymous Client: strictly 1 SQL query per page (LEFT OUTER JOIN accounts_user)
        with self.assertNumQueries(1):
            res_p1 = self.client.get(url)
        self.assertEqual(res_p1.status_code, 200)
        self._assert_no_store_headers(res_p1)
        data_p1 = res_p1.json()
        self.assertEqual(len(data_p1["items"]), 20)
        self.assertEqual(data_p1["nextBefore"], data_p1["items"][-1]["id"])
        collected_ids.extend(item["id"] for item in data_p1["items"])

        with self.assertNumQueries(1):
            res_p2 = self.client.get(f"{url}?before={data_p1['nextBefore']}")
        self.assertEqual(res_p2.status_code, 200)
        data_p2 = res_p2.json()
        self.assertEqual(len(data_p2["items"]), 20)
        self.assertEqual(data_p2["nextBefore"], data_p2["items"][-1]["id"])
        collected_ids.extend(item["id"] for item in data_p2["items"])

        with self.assertNumQueries(1):
            res_p3 = self.client.get(f"{url}?before={data_p2['nextBefore']}")
        self.assertEqual(res_p3.status_code, 200)
        data_p3 = res_p3.json()
        self.assertEqual(len(data_p3["items"]), 5)
        self.assertIsNone(data_p3["nextBefore"])
        collected_ids.extend(item["id"] for item in data_p3["items"])

        self.assertEqual(collected_ids, list(reversed(target_ids)))

        req = self.factory.get(url)
        req.user = authors[0]
        with self.assertNumQueries(1):
            direct_res = note_comments_view(req, slug="harness-cold-start")
        self.assertEqual(direct_res.status_code, 200)
        self._assert_no_store_headers(direct_res)

        empty_res = self.client.get("/api/notes/study4examagent/comments/")
        self.assertEqual(empty_res.status_code, 200)
        self.assertEqual(empty_res.json(), {"items": [], "nextBefore": None})

        for idx in range(20):
            Comment.objects.create(
                note_slug="study4examagent",
                author=None,
                body=f"恰好二十条 #{idx + 1}",
            )
        exact_20_res = self.client.get("/api/notes/study4examagent/comments/")
        self.assertEqual(exact_20_res.status_code, 200)
        exact_20_json = exact_20_res.json()
        self.assertEqual(len(exact_20_json["items"]), 20)
        self.assertIsNone(exact_20_json["nextBefore"])

    def test_five_session_roles_can_delete_matrix_and_zero_privacy_leakage(
        self,
    ) -> None:
        user_a = User.objects.create_user(
            "u_secret_alpha_001",
            "alice-private@example.com",
            gen_test_credential(),
            display_name="山月读者",
        )
        user_b_blank_name = User.objects.create_user(
            "u_secret_bravo_002",
            "bob-private@example.com",
            gen_test_credential(),
            display_name="",
        )
        owner_admin = User.objects.create_user(
            "u_secret_owner_003",
            "owner-private@example.com",
            gen_test_credential(),
            display_name="站主本尊",
            is_comment_admin=True,
        )

        c_guest = Comment.objects.create(
            note_slug="node-event-loop",
            author=None,
            body="未登录路人评论",
        )
        c_a = Comment.objects.create(
            note_slug="node-event-loop",
            author=user_a,
            body="读者甲本人评论",
        )
        c_b = Comment.objects.create(
            note_slug="node-event-loop",
            author=user_b_blank_name,
            body="空昵称注册用户评论",
        )
        c_owner = Comment.objects.create(
            note_slug="node-event-loop",
            author=owner_admin,
            body="站主本人评论",
        )
        ordered_ids = [c_owner.pk, c_b.pk, c_a.pk, c_guest.pk]

        url = "/api/notes/node-event-loop/comments/"
        anon_client = Client()
        client_a = Client()
        client_b = Client()
        client_owner = Client()

        client_a.force_login(user_a)
        client_b.force_login(user_b_blank_name)
        client_owner.force_login(owner_admin)

        res_anon = anon_client.get(url)
        res_a = client_a.get(url)
        res_b = client_b.get(url)
        res_owner = client_owner.get(url)

        for response in (res_anon, res_a, res_b, res_owner):
            self.assertEqual(response.status_code, 200)
            self._assert_no_store_headers(response)
            raw_text = response.content.decode("utf-8")
            self.assertNotIn("email", raw_text)
            self.assertNotIn("@", raw_text)
            self.assertNotIn("alice-private", raw_text)
            self.assertNotIn("bob-private", raw_text)
            self.assertNotIn("owner-private", raw_text)
            self.assertNotIn(user_a.username, raw_text)
            self.assertNotIn(user_b_blank_name.username, raw_text)
            self.assertNotIn(owner_admin.username, raw_text)

        def flags_by_id(res) -> dict[int, bool]:
            items = res.json()["items"]
            self.assertEqual([it["id"] for it in items], ordered_ids)
            for it in items:
                self.assertRegex(it["createdAt"], ISO_UTC_Z_RE)
            return {it["id"]: it["canDelete"] for it in items}

        by_id_payload = {it["id"]: it for it in res_anon.json()["items"]}
        self.assertEqual(
            by_id_payload[c_guest.pk]["author"],
            {"kind": "guest", "id": None, "displayName": GUEST_DISPLAY_NAME},
        )
        self.assertEqual(
            by_id_payload[c_a.pk]["author"],
            {"kind": "member", "id": user_a.pk, "displayName": "山月读者"},
        )
        expected_blank_fallback = f"用户 #{user_b_blank_name.pk}"
        self.assertEqual(
            by_id_payload[c_b.pk]["author"],
            {
                "kind": "member",
                "id": user_b_blank_name.pk,
                "displayName": expected_blank_fallback,
            },
        )
        # Verify /api/me/ and comments list emit identical public_display_name fallback
        me_b_json = client_b.get("/api/me/").json()
        self.assertEqual(
            me_b_json["user"]["displayName"], expected_blank_fallback
        )

        self.assertEqual(
            flags_by_id(res_anon),
            {
                c_owner.pk: False,
                c_b.pk: False,
                c_a.pk: False,
                c_guest.pk: False,
            },
        )
        self.assertEqual(
            flags_by_id(res_a),
            {
                c_owner.pk: False,
                c_b.pk: False,
                c_a.pk: True,
                c_guest.pk: False,
            },
        )
        self.assertEqual(
            flags_by_id(res_b),
            {
                c_owner.pk: False,
                c_b.pk: True,
                c_a.pk: False,
                c_guest.pk: False,
            },
        )
        self.assertEqual(
            flags_by_id(res_owner),
            {
                c_owner.pk: True,
                c_b.pk: True,
                c_a.pk: True,
                c_guest.pk: True,
            },
        )
        user_a.is_active = False
        user_a.save(update_fields=["is_active"])
        res_inactive = client_a.get(url)
        self.assertEqual(
            flags_by_id(res_inactive),
            {
                c_owner.pk: False,
                c_b.pk: False,
                c_a.pk: False,
                c_guest.pk: False,
            },
        )
