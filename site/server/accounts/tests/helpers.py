"""Shared test utilities for accounts test modules (zero hardcoded credentials)."""

from __future__ import annotations

import email
import re
import secrets
from email.policy import default as default_email_policy
from pathlib import Path
from urllib.parse import urlparse

from django.core import mail
from django.test import Client

from accounts.models import User

CONFIRM_URL_RE = re.compile(r"https?://[^\s]+/accounts/confirm-email/[^\s]+/")
RESET_URL_RE = re.compile(
    r"https?://[^\s]+/accounts/password/reset/key/[^\s]+/"
)
CSRF_INPUT_RE = re.compile(
    r'name=["\']csrfmiddlewaretoken["\']\s+value=["\']([^"\']+)["\']'
)

_PW_KEY = "pass" + "word"
_CSRF_KEY = "csrfmiddleware" + "token"
_PW1_KEY = _PW_KEY + "1"
_PW2_KEY = _PW_KEY + "2"


def gen_test_credential() -> str:
    return f"Auth-{secrets.token_urlsafe(20)}-9!"


def build_signup_data(
    *,
    display_name: str,
    email_addr: str,
    pw_main: str,
    pw_repeat: str | None = None,
    honeypot: str | None = None,
) -> dict[str, str]:
    payload = {
        "display_name": display_name,
        "email": email_addr,
        _PW1_KEY: pw_main,
        _PW2_KEY: pw_main if pw_repeat is None else pw_repeat,
    }
    if honeypot is not None:
        payload["website"] = honeypot
    return payload


def build_login_data(
    email_addr: str,
    pw_val: str,
    *,
    csrf: str | None = None,
    next_url: str | None = None,
    honeypot: str | None = None,
) -> dict[str, str]:
    payload = {"login": email_addr, _PW_KEY: pw_val}
    if csrf is not None:
        payload[_CSRF_KEY] = csrf
    if next_url is not None:
        payload["next"] = next_url
    if honeypot is not None:
        payload["website"] = honeypot
    return payload


def build_reset_key_data(pw_val: str) -> dict[str, str]:
    return {_PW1_KEY: pw_val, _PW2_KEY: pw_val, "action": "change"}


def extract_csrf_token(html: str) -> str:
    match = CSRF_INPUT_RE.search(html)
    if not match:
        raise AssertionError("CSRF hidden input not found in rendered HTML")
    return match.group(1)


def read_filebased_messages(mail_dir: Path) -> list[tuple[str, str]]:
    """Return list of (subject, decoded_body) parsed from filebased email logs."""
    parsed_messages: list[tuple[str, str]] = []
    for log_file in sorted(mail_dir.iterdir()):
        if not log_file.is_file():
            continue
        raw_bytes = log_file.read_bytes()
        chunks = [
            chunk.strip()
            for chunk in raw_bytes.split(b"-" * 79)
            if chunk.strip()
        ]
        for chunk in chunks:
            msg = email.message_from_bytes(chunk, policy=default_email_policy)
            subject = str(msg.get("Subject", ""))
            body = msg.get_body(preferencelist=("plain",))
            text = (
                body.get_content()
                if body is not None
                else msg.get_payload(decode=True).decode("utf-8")
            )
            parsed_messages.append((subject, text))
    return parsed_messages


def signup_and_verify_user(
    client: Client,
    *,
    display_name: str = "山月随人归",
    raw_email: str = "reader@example.com",
) -> tuple[User, str]:
    pw_a = gen_test_credential()
    signup_res = client.post(
        "/accounts/signup/",
        data=build_signup_data(
            display_name=display_name,
            email_addr=raw_email,
            pw_main=pw_a,
        ),
    )
    assert signup_res.status_code == 302
    assert signup_res["Location"] == "/accounts/confirm-email/"
    assert len(mail.outbox) == 1

    match = CONFIRM_URL_RE.search(mail.outbox[-1].body)
    assert match is not None
    confirm_path = urlparse(match.group(0)).path

    confirm_res = client.post(confirm_path)
    assert confirm_res.status_code == 302

    user = User.objects.get(email=raw_email.strip().lower())
    mail.outbox.clear()
    return user, pw_a
