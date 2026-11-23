"""Tests for CommentAdmin governance permissions, superuser write lock, and N+1."""

from __future__ import annotations

import io

from django.contrib import admin
from django.core.management import call_command
from django.db import connection
from django.test import Client, TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from accounts.models import User
from accounts.tests.helpers import gen_test_credential
from comments.admin import CommentAdmin
from comments.models import Comment


class CommentAdminModerationTests(TestCase):
    def setUp(self) -> None:
        super().setUp()
        self.owner = User.objects.create_user(
            "u_admin_owner",
            "owner-mod@example.com",
            gen_test_credential(),
            display_name="站主治理员",
        )
        call_command(
            "grant_comment_admin",
            "--email",
            "owner-mod@example.com",
            stdout=io.StringIO(),
            stderr=io.StringIO(),
        )
        self.owner.refresh_from_db()
        self.assertTrue(self.owner.is_comment_admin)
        self.assertTrue(self.owner.is_staff)
        self.assertFalse(self.owner.is_superuser)

        self.superuser = User.objects.create_superuser(
            "u_root_admin",
            "root-mod@example.com",
            gen_test_credential(),
            display_name="超管治理员",
        )

        self.staff_without_role = User.objects.create_user(
            "u_plain_staff",
            "plain-staff@example.com",
            gen_test_credential(),
            display_name="无治理权限员工",
            is_staff=True,
            is_comment_admin=False,
        )

    def test_granted_comment_admin_and_superuser_read_delete_only_and_zero_n_plus_1(
        self,
    ) -> None:
        model_admin = admin.site._registry[Comment]
        self.assertIsInstance(model_admin, CommentAdmin)
        self.assertEqual(model_admin.raw_id_fields, ())

        changelist_url = reverse("admin:comments_comment_changelist")
        add_url = reverse("admin:comments_comment_add")

        # Plain staff without is_comment_admin gets 403 on CommentAdmin
        plain_client = Client()
        plain_client.force_login(self.staff_without_role)
        self.assertEqual(plain_client.get(changelist_url).status_code, 403)

        owner_client = Client()
        owner_client.force_login(self.owner)

        super_client = Client()
        super_client.force_login(self.superuser)

        first_author = User.objects.create_user(
            "u_c_author_0",
            "c-author-0@example.com",
            gen_test_credential(),
            display_name="留言者零",
        )
        guest_row = Comment.objects.create(
            note_slug="harness-cold-start",
            author=None,
            body="访客待审留言",
        )
        member_row = Comment.objects.create(
            note_slug="harness-cold-start",
            author=first_author,
            body="读者原始留言正文",
        )

        with CaptureQueriesContext(connection) as small_list_queries:
            res_small = owner_client.get(changelist_url)
        self.assertEqual(res_small.status_code, 200)
        self.assertContains(res_small, "harness-cold-start")

        for idx in range(1, 11):
            extra_author = User.objects.create_user(
                f"u_c_author_{idx}",
                f"c-author-{idx}@example.com",
                gen_test_credential(),
                display_name=f"留言者{idx}",
            )
            Comment.objects.create(
                note_slug="harness-cold-start",
                author=extra_author,
                body=f"第 {idx} 位读者留言",
            )

        with CaptureQueriesContext(connection) as large_list_queries:
            res_large = owner_client.get(changelist_url)
        self.assertEqual(res_large.status_code, 200)
        self.assertEqual(len(small_list_queries), len(large_list_queries))

        change_url = reverse(
            "admin:comments_comment_change", args=[member_row.pk]
        )
        # BOTH comment_admin and superuser are strictly read/delete-only (add/change disabled)
        for mod_client in (owner_client, super_client):
            self.assertEqual(mod_client.get(add_url).status_code, 403)
            self.assertEqual(mod_client.post(add_url, data={}).status_code, 403)
            detail_res = mod_client.get(change_url)
            self.assertEqual(detail_res.status_code, 200)
            self.assertNotContains(detail_res, 'name="_save"')
            self.assertEqual(
                mod_client.post(
                    change_url,
                    data={"note_slug": "harness-cold-start", "body": "篡改后的正文"},
                ).status_code,
                403,
            )

        member_row.refresh_from_db()
        self.assertEqual(member_row.body, "读者原始留言正文")

        # Comment admin CAN delete both guest and member comments via Admin delete view
        for target in (guest_row, member_row):
            delete_url = reverse(
                "admin:comments_comment_delete", args=[target.pk]
            )
            self.assertEqual(owner_client.get(delete_url).status_code, 200)
            del_res = owner_client.post(delete_url, data={"post": "yes"})
            self.assertEqual(del_res.status_code, 302)
            self.assertFalse(Comment.objects.filter(pk=target.pk).exists())
