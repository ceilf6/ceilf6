"""Idempotently grant or revoke site-owner comment admin and Django Admin access."""

from __future__ import annotations

from importlib import import_module
from typing import Any

from allauth.account.models import EmailAddress
from django.conf import settings
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.contrib.sessions.models import Session
from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import transaction

from accounts.models import User

DB_BACKED_SESSION_ENGINES = frozenset(
    {
        "django.contrib.sessions.backends.db",
        "django.contrib.sessions.backends.cached_db",
    }
)


def _invalidate_user_sessions(user_pk: int) -> int:
    """Delete all active DB-backed sessions belonging to user_pk outside write lock."""
    target_uid = str(user_pk)
    keys_to_delete: list[str] = []
    for session in Session.objects.all().iterator():
        try:
            decoded = session.get_decoded()
        except Exception:  # noqa: BLE001
            continue
        if str(decoded.get("_auth_user_id")) == target_uid:
            keys_to_delete.append(session.session_key)
    if not keys_to_delete:
        return 0
    session_store_cls = import_module(settings.SESSION_ENGINE).SessionStore
    for session_key in keys_to_delete:
        session_store_cls(session_key).delete()
    return len(keys_to_delete)


class Command(BaseCommand):
    help = (
        "Idempotently grant or revoke site-owner comment admin and staff access "
        "(--revoke also logs out all active DB sessions for that user)."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        target_group = parser.add_mutually_exclusive_group(required=True)
        target_group.add_argument(
            "--user-id",
            type=int,
            help="Explicit primary key of the target accounts.User.",
        )
        target_group.add_argument(
            "--email",
            type=str,
            help="Explicit email address of the target accounts.User.",
        )
        parser.add_argument(
            "--revoke",
            action="store_true",
            help="Revoke comment admin & staff access and invalidate all active sessions.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        del args
        user_id: int | None = options.get("user_id")
        raw_email: str | None = options.get("email")
        revoke: bool = bool(options.get("revoke"))

        if user_id is not None and user_id <= 0:
            raise CommandError("--user-id must be a positive integer.")

        normalized_email = ""
        if raw_email is not None:
            normalized_email = raw_email.strip().lower()
            if not normalized_email:
                raise CommandError("--email must not be empty.")

        has_verified_email = True
        with transaction.atomic():
            if user_id is not None:
                user = (
                    User.objects.select_for_update()
                    .filter(pk=user_id)
                    .first()
                )
                target_desc = f"id={user_id}"
            else:
                user = (
                    User.objects.select_for_update()
                    .filter(email__iexact=normalized_email)
                    .first()
                )
                target_desc = "specified email"

            if user is None:
                raise CommandError(f"Target user ({target_desc}) does not exist.")

            user_pk = user.pk
            user_label = str(user)
            is_superuser_flag = user.is_superuser

            user_ct = ContentType.objects.get_for_model(User)
            view_user_perm = Permission.objects.get(
                content_type=user_ct, codename="view_user"
            )

            if revoke:
                changed_fields: list[str] = []
                if user.is_comment_admin:
                    user.is_comment_admin = False
                    changed_fields.append("is_comment_admin")
                if not is_superuser_flag and user.is_staff:
                    user.is_staff = False
                    changed_fields.append("is_staff")
                if changed_fields:
                    user.save(update_fields=changed_fields)
                user.user_permissions.remove(view_user_perm)
            else:
                if not user.is_active:
                    raise CommandError(
                        f"Cannot grant comment admin access to inactive user id={user_pk}."
                    )
                changed_fields = []
                if not user.is_comment_admin:
                    user.is_comment_admin = True
                    changed_fields.append("is_comment_admin")
                if not user.is_staff:
                    user.is_staff = True
                    changed_fields.append("is_staff")
                if changed_fields:
                    user.save(update_fields=changed_fields)
                user.user_permissions.add(view_user_perm)
                has_verified_email = EmailAddress.objects.filter(
                    user=user, verified=True
                ).exists()

        if revoke:
            if settings.SESSION_ENGINE in DB_BACKED_SESSION_ENGINES:
                invalidated = _invalidate_user_sessions(user_pk)
            else:
                invalidated = 0
                self.stderr.write(
                    self.style.WARNING(
                        f"WARNING: SESSION_ENGINE={settings.SESSION_ENGINE!r} is not "
                        "database-backed; active sessions could not be purged."
                    )
                )
            if is_superuser_flag:
                self.stderr.write(
                    self.style.WARNING(
                        f"WARNING: User id={user_pk} ({user_label}) still has "
                        "is_superuser=True and retains Django Admin and /api/me/ "
                        "(isCommentAdmin=true) superuser privileges."
                    )
                )
            self.stdout.write(
                self.style.SUCCESS(
                    f"Revoked comment admin flag for user id={user_pk} "
                    f"({user_label}); invalidated {invalidated} session(s)."
                )
            )
            return

        self.stdout.write(
            self.style.SUCCESS(
                f"Granted comment admin and staff access to user id={user_pk} ({user_label})."
            )
        )
        if not has_verified_email:
            self.stderr.write(
                self.style.WARNING(
                    f"WARNING: User id={user_pk} ({user_label}) has no verified "
                    "EmailAddress yet; run ensure_verified_user before signing in via /accounts/login/."
                )
            )
