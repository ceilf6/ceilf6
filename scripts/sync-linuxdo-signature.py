#!/usr/bin/env python3
"""Upload a compact SVG to Linux DO and update the owner's image signature."""

import argparse
import os
import sys
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests


DEFAULT_BASE_URL = "https://linux.do"
ALLOWED_CDN_HOST = "cdn3.ldstatic.com"
ALLOWED_BASE_HOSTS = {"linux.do", "127.0.0.1", "localhost"}
TIMEOUT_SECONDS = 20


class SyncError(RuntimeError):
    """An expected synchronization failure that is safe to show in workflow logs."""


def parse_args():
    parser = argparse.ArgumentParser(
        description="Upload a compact SVG and update a Linux DO image signature."
    )
    parser.add_argument("--image", type=Path, required=True)
    parser.add_argument("--username", required=True)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    return parser.parse_args()


def json_response(response, operation):
    if not 200 <= response.status_code < 300:
        raise SyncError(f"{operation} failed with HTTP {response.status_code}")
    try:
        return response.json()
    except ValueError as exc:
        raise SyncError(f"{operation} returned invalid JSON") from exc


def normalized_base_url(value):
    parsed = urlparse(value)
    if parsed.hostname not in ALLOWED_BASE_HOSTS:
        raise SyncError("--base-url is not an allowed Linux DO endpoint")
    if parsed.hostname == "linux.do" and parsed.scheme != "https":
        raise SyncError("--base-url is not an allowed Linux DO endpoint")
    if parsed.hostname != "linux.do" and parsed.scheme not in {"http", "https"}:
        raise SyncError("--base-url is not an allowed Linux DO endpoint")
    return f"{value.rstrip('/')}/"


def allowed_svg_url(value):
    parsed = urlparse(value) if isinstance(value, str) else None
    if (
        not parsed
        or parsed.scheme != "https"
        or parsed.hostname != ALLOWED_CDN_HOST
        or not parsed.path.lower().endswith(".svg")
    ):
        raise SyncError("upload response URL is not an allowed Linux DO SVG URL")
    return value


def request(session, method, url, operation, **kwargs):
    try:
        response = session.request(
            method,
            url,
            timeout=TIMEOUT_SECONDS,
            allow_redirects=False,
            **kwargs,
        )
    except requests.RequestException as exc:
        raise SyncError(f"{operation} request failed") from exc
    return json_response(response, operation)


def sync_signature(image, username, base_url, cookie):
    if not image.is_file() or image.suffix.lower() != ".svg":
        raise SyncError("--image must point to an existing .svg file")
    if not cookie:
        raise SyncError("LINUXDO_SESSION_COOKIE is required")

    base_url = normalized_base_url(base_url)
    session = requests.Session()
    session.headers.update(
        {
            "Accept": "application/json",
            "Cookie": cookie,
            "User-Agent": "ceilf6-linuxdo-signature-sync/1.0",
            "X-Requested-With": "XMLHttpRequest",
        }
    )

    csrf_payload = request(
        session,
        "GET",
        urljoin(base_url, "session/csrf.json"),
        "CSRF request",
    )
    csrf_token = csrf_payload.get("csrf")
    if not isinstance(csrf_token, str) or not csrf_token:
        raise SyncError("CSRF response did not include a token")

    with image.open("rb") as handle:
        upload_payload = request(
            session,
            "POST",
            urljoin(base_url, "uploads.json"),
            "upload",
            data={"upload_type": "composer", "synchronous": "true"},
            files={"file": (image.name, handle, "image/svg+xml")},
            headers={"X-CSRF-Token": csrf_token},
        )

    signature_url = allowed_svg_url(upload_payload.get("url"))
    request(
        session,
        "PUT",
        urljoin(base_url, f"u/{username}.json"),
        "profile update",
        data={"custom_fields[signature_url]": signature_url},
        headers={"X-CSRF-Token": csrf_token},
    )


def main():
    args = parse_args()
    try:
        sync_signature(
            args.image,
            args.username,
            args.base_url,
            os.environ.get("LINUXDO_SESSION_COOKIE", ""),
        )
    except SyncError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print("Linux DO signature updated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
