"""Idempotently create or update an active user with a verified primary email."""

from __future__ import annotations

import os
import secrets
import sys
from typing import Any

from allauth.account.models import EmailAddress
from django.contrib.auth import password_validation
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.core.validators import validate_email
from django.db import transaction

from accounts.adapter import generate_opaque_username
from accounts.models import (
    User,
    normalize_display_name,
    validate_safe_display_name,
)


class Command(BaseCommand):
    help = (
        "Idempotently ensure an active user with a verified primary EmailAddress "
        "without passing raw credentials on the command line."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--email",
            type=str,
            required=True,
            help="Login email address for the account.",
        )
        parser.add_argument(
            "--display-name",
            type=str,
            required=True,
            help="Public display nickname (1-64 safe characters).",
        )
        cred_group = parser.add_mutually_exclusive_group(required=True)
        cred_group.add_argument(
            "--password-env",
            type=str,
            help="Environment variable name containing the account password.",
        )
        cred_group.add_argument(
            "--password-stdin",
            action="store_true",
            help="Read the account password from standard input (single line).",
        )
        cred_group.add_argument(
            "--generate-password",
            action="store_true",
            help="Generate a strong random password (printed once to stderr).",
        )
        parser.add_argument(
            "--reset-password",
            action="store_true",
            help="Allow --generate-password to overwrite an existing user's password.",
        )
        parser.add_argument(
            "--reactivate",
            action="store_true",
            help="Explicitly re-enable an existing inactive (is_active=False) account.",
        )

    def _resolve_credential(self, options: dict[str, Any]) -> str:
        env_var_name: str | None = options.get("password_env")
        if env_var_name is not None:
            cleaned_name = env_var_name.strip()
            if not cleaned_name:
                raise CommandError("--password-env variable name must not be empty.")
            value = os.environ.get(cleaned_name, "")
            if not value:
                raise CommandError(
                    f"Environment variable {cleaned_name!r} is unset or empty."
                )
            return value

        if options.get("password_stdin"):
            stream = getattr(self, "stdin", None) or sys.stdin
            raw_line = stream.readline()
            value = raw_line.rstrip("\r\n")
            if not value:
                raise CommandError("No password received on standard input.")
            return value

        return f"Auto-{secrets.token_urlsafe(24)}-9!"

    def handle(self, *args: Any, **options: Any) -> None:
        del args
        raw_email = (options.get("email") or "").strip().lower()
        try:
            validate_email(raw_email)
        except ValidationError as exc:
            raise CommandError(f"Invalid --email value: {exc.messages[0]}") from exc

        cleaned_display_name = normalize_display_name(options.get("display_name"))
        if not cleaned_display_name:
            raise CommandError("--display-name must not be empty or whitespace.")
        try:
            validate_safe_display_name(cleaned_display_name)
        except ValidationError as exc:
            raise CommandError(
                f"Invalid --display-name value: {exc.messages[0]}"
            ) from exc

        generated_mode = bool(options.get("generate_password"))
        reset_password = bool(options.get("reset_password"))
        reactivate = bool(options.get("reactivate"))
        credential = self._resolve_credential(options)

        with transaction.atomic():
            conflicting_email = (
                EmailAddress.objects.select_for_update()
                .filter(email__iexact=raw_email)
                .first()
            )
            user = (
                User.objects.select_for_update()
                .filter(email__iexact=raw_email)
                .first()
            )
            if (
                conflicting_email is not None
                and user is not None
                and conflicting_email.user_id != user.pk
            ):
                raise CommandError(
                    "EmailAddress row belongs to a different user record."
                )
            if conflicting_email is not None and user is None:
                user = (
                    User.objects.select_for_update()
                    .filter(pk=conflicting_email.user_id)
                    .first()
                )

            created = user is None
            if user is None:
                user = User(
                    username=generate_opaque_username(),
                    email=raw_email,
                    display_name=cleaned_display_name,
                    is_active=True,
                )
            else:
                if not user.is_active and not reactivate:
                    raise CommandError(
                        f"Target user id={user.pk} is inactive; pass --reactivate to re-enable it explicitly."
                    )
                if generated_mode and not reset_password:
                    raise CommandError(
                        f"Target user id={user.pk} already exists; pass --reset-password alongside --generate-password to rotate their password."
                    )
                if not user.username or "@" in user.username:
                    user.username = generate_opaque_username()
                user.email = raw_email
                user.display_name = cleaned_display_name
                if reactivate:
                    user.is_active = True

            try:
                password_validation.validate_password(credential, user)
            except ValidationError as exc:
                joined = "; ".join(exc.messages)
                raise CommandError(f"Password validation failed: {joined}") from exc

            user.set_password(credential)
            user.full_clean()
            user.save()

            EmailAddress.objects.filter(user=user).exclude(
                email__iexact=raw_email
            ).delete()
            email_row = (
                EmailAddress.objects.select_for_update()
                .filter(user=user, email__iexact=raw_email)
                .first()
            )
            if email_row is None:
                EmailAddress.objects.create(
                    user=user,
                    email=raw_email,
                    verified=True,
                    primary=True,
                )
            else:
                dirty_email_fields: list[str] = []
                if email_row.email != raw_email:
                    email_row.email = raw_email
                    dirty_email_fields.append("email")
                if not email_row.verified:
                    email_row.verified = True
                    dirty_email_fields.append("verified")
                if not email_row.primary:
                    email_row.primary = True
                    dirty_email_fields.append("primary")
                if dirty_email_fields:
                    email_row.save(update_fields=dirty_email_fields)

        action = "Created" if created else "Updated"
        self.stdout.write(
            self.style.SUCCESS(
                f"{action} verified user id={user.pk} ({user})."
            )
        )
        if generated_mode:
            self.stderr.write(f"Generated password (shown once): {credential}")
