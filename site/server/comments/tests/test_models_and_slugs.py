"""Tests for Comment model constraints, ModelForm contract, slug manifest, and permissions."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.db import IntegrityError, connection, transaction
from django.db.models import ProtectedError
from django.forms import modelform_factory
from django.test import TestCase, override_settings

from accounts.models import User
from accounts.tests.helpers import gen_test_credential
from comments.apps import check_note_slugs_manifest
from comments.models import (
    GUEST_DISPLAY_NAME,
    MAX_COMMENT_BODY_LENGTH,
    MAX_NOTE_SLUG_LENGTH,
    Comment,
)
from comments.permissions import can_delete_comment
from comments.slugs import (
    DEFAULT_CONTENT_NOTES_DIR,
    NOTE_SLUGS_MANIFEST_PATH,
    discover_content_note_slugs,
    get_valid_note_slugs,
    load_manifest_note_slugs,
    slug_from_note_path,
)


class CommentModelAndConstraintTests(TestCase):
    def setUp(self) -> None:
        super().setUp()
        self.member = User.objects.create_user(
            "u_model_author",
            "model-author@example.com",
            gen_test_credential(),
            display_name="模型测试读者",
        )

    def test_clean_accepts_guest_member_and_partial_modelform_validation(self) -> None:
        guest_comment = Comment(
            note_slug="harness-cold-start",
            author=None,
            body="a",
        )
        guest_comment.full_clean()
        guest_comment.save()
        self.assertIsNone(guest_comment.author)
        self.assertEqual(GUEST_DISPLAY_NAME, "未登录用户")

        max_body = "字" * MAX_COMMENT_BODY_LENGTH
        member_comment = Comment(
            note_slug="harness-cold-start",
            author=self.member,
            body=max_body,
        )
        member_comment.full_clean()
        member_comment.save()
        self.assertEqual(len(member_comment.body), 1000)
        self.assertIn("harness-cold-start", str(member_comment))
        self.assertNotIn("@", str(member_comment))

        # Partial ModelForm(fields=["body"]) must honor clean_fields(exclude=...) without ValueError
        body_only_form_cls = modelform_factory(Comment, fields=["body"])
        ok_form = body_only_form_cls(data={"body": "部分字段表单正常通过"})
        self.assertTrue(ok_form.is_valid(), msg=ok_form.errors)

        for blank_payload in ("   ", "\u3000\u3000", "bad\x00char"):
            bad_form = body_only_form_cls(data={"body": blank_payload})
            self.assertFalse(bad_form.is_valid())
            self.assertIn("body", bad_form.errors)

    def test_clean_rejects_empty_slug_blank_body_fullwidth_space_nul_and_overlong(
        self,
    ) -> None:
        invalid_cases = [
            ("", "正常正文"),
            ("   ", "正常正文"),
            ("bad\x00slug", "正常正文"),
            ("harness-cold-start", ""),
            ("harness-cold-start", "    "),
            ("harness-cold-start", "\n\t\r "),
            ("harness-cold-start", "\u3000\u3000"),  # 全角空格全空白正文
            ("harness-cold-start", "含空字符\x00正文"),
            ("harness-cold-start", "a" * (MAX_COMMENT_BODY_LENGTH + 1)),
            ("harness-cold-start", "   " + ("a" * 999) + "   "),
        ]
        for slug_val, body_val in invalid_cases:
            with self.subTest(slug=slug_val, body_preview=repr(body_val[:20])):
                candidate = Comment(
                    note_slug=slug_val,
                    author=self.member,
                    body=body_val,
                )
                with self.assertRaises(ValidationError):
                    candidate.full_clean()

    def test_sqlite_check_constraint_blocks_raw_blank_nul_and_overlong_inserts(
        self,
    ) -> None:
        rejected_rows = [
            ("", "正常内容"),
            ("bad\x00slug", "正常内容"),
            ("harness-cold-start", ""),
            ("harness-cold-start", "     "),
            ("harness-cold-start", "\n\t\r "),
            ("harness-cold-start", "x" * 1001),
            ("harness-cold-start", "ok\x00" + ("x" * 2000)),
        ]
        for slug_val, body_val in rejected_rows:
            with self.subTest(slug=slug_val, body_len=len(body_val)):
                with self.assertRaises(IntegrityError):
                    with transaction.atomic():
                        Comment.objects.create(
                            note_slug=slug_val,
                            author=None,
                            body=body_val,
                        )

    def test_author_protect_prevents_cascade_deletion_and_index_supports_cursor_query(
        self,
    ) -> None:
        Comment.objects.create(
            note_slug="harness-cold-start",
            author=self.member,
            body="受保护的历史评论",
        )
        with self.assertRaises(ProtectedError):
            with transaction.atomic():
                self.member.delete()
        self.assertEqual(Comment.objects.count(), 1)

        user_without_comments = User.objects.create_user(
            "u_ephemeral",
            "ephemeral@example.com",
            gen_test_credential(),
            display_name="无评论账号",
        )
        user_without_comments.delete()

        with connection.cursor() as cursor:
            constraints = connection.introspection.get_constraints(
                cursor, Comment._meta.db_table
            )
            self.assertIn("comments_note_slug_id_desc_idx", constraints)
            cursor.execute(
                "EXPLAIN QUERY PLAN "
                'SELECT "id" FROM "comments_comment" '
                'WHERE "note_slug" = %s AND "id" < %s '
                'ORDER BY "id" DESC LIMIT 21',
                ["harness-cold-start", 100],
            )
            plan_rows = " ".join(str(row) for row in cursor.fetchall())
            self.assertIn("comments_note_slug_id_desc_idx", plan_rows)


class NoteSlugManifestTests(TestCase):
    @unittest.skipUnless(
        DEFAULT_CONTENT_NOTES_DIR.is_dir(),
        "Requires repo checkout with site/content/notes/ directory",
    )
    def test_manifest_matches_content_notes_directory(self) -> None:
        raw_manifest = json.loads(
            NOTE_SLUGS_MANIFEST_PATH.read_text(encoding="utf-8")
        )
        discovered = discover_content_note_slugs(DEFAULT_CONTENT_NOTES_DIR)
        self.assertGreater(len(discovered), 0)
        self.assertEqual(raw_manifest, discovered)
        self.assertEqual(len(raw_manifest), len(set(raw_manifest)))
        self.assertEqual(get_valid_note_slugs(), frozenset(discovered))

    def test_standalone_manifest_system_check_and_slug_validation(self) -> None:
        self.assertEqual(
            slug_from_note_path("/content/notes/harness-cold-start.md"),
            "harness-cold-start",
        )
        self.assertEqual(
            slug_from_note_path(r"C:\site\content\notes\v8-gc-source.md"),
            "v8-gc-source",
        )
        self.assertEqual(check_note_slugs_manifest(None), [])

        with patch(
            "comments.slugs.load_manifest_note_slugs",
            side_effect=ImproperlyConfigured("corrupt manifest"),
        ):
            errs = check_note_slugs_manifest(None)
            self.assertEqual(len(errs), 1)
            self.assertEqual(errs[0].id, "comments.E001")

        with patch(
            "comments.slugs.load_manifest_note_slugs",
            return_value=frozenset(),
        ):
            empty_errs = check_note_slugs_manifest(None)
            self.assertEqual(len(empty_errs), 1)
            self.assertEqual(empty_errs[0].id, "comments.E002")

        with tempfile.TemporaryDirectory(prefix="ceilf6-slugs-") as tmp_dir:
            tmp_path = Path(tmp_dir)
            standalone = tmp_path / "note_slugs.json"
            standalone.write_text('["alpha-note", "beta_note_2"]\n', encoding="utf-8")
            load_manifest_note_slugs.cache_clear()
            self.assertEqual(
                load_manifest_note_slugs(standalone),
                frozenset({"alpha-note", "beta_note_2"}),
            )

            corrupt_payloads = [
                "{not-json",
                '{"not": "a-list"}',
                '["valid", "  padded  "]',
                '["invalid.dot.slug"]',
                '["invalid space"]',
                json.dumps(["a" * (MAX_NOTE_SLUG_LENGTH + 1)]),
            ]
            for idx, payload in enumerate(corrupt_payloads):
                with self.subTest(payload=payload[:30]):
                    bad_file = tmp_path / f"bad_{idx}.json"
                    bad_file.write_text(payload, encoding="utf-8")
                    with self.assertRaises(ImproperlyConfigured):
                        load_manifest_note_slugs(bad_file)

            with self.assertRaises(FileNotFoundError):
                discover_content_note_slugs(tmp_path / "missing-notes")

        with override_settings(VALID_NOTE_SLUGS=["custom-slug"]):
            self.assertEqual(get_valid_note_slugs(), frozenset({"custom-slug"}))
        with override_settings(VALID_NOTE_SLUGS=frozenset()):
            self.assertEqual(get_valid_note_slugs(), frozenset())


class CommentDeletePermissionUnitTests(TestCase):
    def setUp(self) -> None:
        super().setUp()
        self.author = User.objects.create_user(
            "u_perm_author",
            "perm-author@example.com",
            gen_test_credential(),
            display_name="作者本人",
        )
        self.other = User.objects.create_user(
            "u_perm_other",
            "perm-other@example.com",
            gen_test_credential(),
            display_name="其他读者",
        )
        self.staff_only = User.objects.create_user(
            "u_perm_staff",
            "perm-staff@example.com",
            gen_test_credential(),
            display_name="普通后台员工",
            is_staff=True,
            is_comment_admin=False,
        )
        self.comment_admin = User.objects.create_user(
            "u_perm_admin",
            "perm-admin@example.com",
            gen_test_credential(),
            display_name="站主管理员",
            is_comment_admin=True,
        )
        self.superuser = User.objects.create_superuser(
            "u_perm_super",
            "perm-super@example.com",
            gen_test_credential(),
            display_name="超级管理员",
        )
        self.guest_comment = Comment.objects.create(
            note_slug="harness-cold-start",
            author=None,
            body="访客留言",
        )
        self.author_comment = Comment.objects.create(
            note_slug="harness-cold-start",
            author=self.author,
            body="作者留言",
        )
        self.other_comment = Comment.objects.create(
            note_slug="harness-cold-start",
            author=self.other,
            body="他人留言",
        )

    def test_permission_matrix_across_all_roles_and_inactive_accounts(self) -> None:
        for anon in (None, AnonymousUser()):
            self.assertFalse(can_delete_comment(anon, self.guest_comment))
            self.assertFalse(can_delete_comment(anon, self.author_comment))

        synthetic_no_pk = SimpleNamespace(
            is_authenticated=True,
            is_active=True,
            is_comment_admin=False,
            is_superuser=False,
            pk=None,
        )
        self.assertFalse(can_delete_comment(synthetic_no_pk, self.guest_comment))

        self.assertFalse(can_delete_comment(self.author, self.guest_comment))
        self.assertTrue(can_delete_comment(self.author, self.author_comment))
        self.assertFalse(can_delete_comment(self.author, self.other_comment))

        self.assertFalse(can_delete_comment(self.staff_only, self.guest_comment))
        self.assertFalse(can_delete_comment(self.staff_only, self.author_comment))

        for privileged in (self.comment_admin, self.superuser):
            self.assertTrue(can_delete_comment(privileged, self.guest_comment))
            self.assertTrue(can_delete_comment(privileged, self.author_comment))
            self.assertTrue(can_delete_comment(privileged, self.other_comment))

        self.author.is_active = False
        self.comment_admin.is_active = False
        self.assertFalse(can_delete_comment(self.author, self.author_comment))
        self.assertFalse(can_delete_comment(self.comment_admin, self.guest_comment))
        self.assertFalse(can_delete_comment(self.comment_admin, self.author_comment))
