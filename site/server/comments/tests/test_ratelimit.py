"""Unit and concurrency tests for trusted client IP extraction and atomic rate limiting."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.core.cache import cache
from django.test import RequestFactory, TestCase, override_settings

from comments.ratelimit import consume_comment_rate_limit, get_client_ip
from config.env import FILEBASED_CACHE_BACKEND, SERVER_DIR

_BURST_QUOTA_SCRIPT = '''
import json, threading, django
django.setup()
from allauth.account.models import EmailAddress
from django.db import connections
from django.test import Client, override_settings
from accounts.models import User
from accounts.tests.helpers import gen_test_credential
from comments.models import Comment

member = User.objects.create_user(
    'u_burst_member', 'burst-member@example.com', gen_test_credential(), display_name='并发限频成员'
)
EmailAddress.objects.create(user=member, email=member.email, verified=True, primary=True)
connections.close_all()

limits = {'guest_ip': ((5, 60),), 'member_user': ((4, 60),), 'member_ip': ((50, 60),)}
with override_settings(ALLAUTH_TRUSTED_PROXY_COUNT=0, COMMENT_RATE_LIMITS=limits):
    # 1) 20 concurrent guest POSTs from identical IP -> exact 5x 201 and 15x 429
    guest_barrier = threading.Barrier(20)
    guest_codes, guest_errors, lock = [], [], threading.Lock()
    def guest_worker(idx):
        try:
            c = Client(enforce_csrf_checks=True, HTTP_HOST='127.0.0.1')
            csrf = c.get('/api/me/', REMOTE_ADDR='203.0.113.50').json()['csrfToken']
            guest_barrier.wait(timeout=10)
            res = c.post(
                '/api/notes/harness-cold-start/comments/',
                data=json.dumps({'body': f'同IP突发 #{idx}', 'expectedAuthorKind': 'guest'}),
                content_type='application/json',
                HTTP_X_CSRFTOKEN=csrf,
                REMOTE_ADDR='203.0.113.50',
            )
            with lock: guest_codes.append(res.status_code)
        except BaseException as exc:
            with lock: guest_errors.append(repr(exc))
        finally:
            connections.close_all()
    t_guests = [threading.Thread(target=guest_worker, args=(i,)) for i in range(20)]
    for t in t_guests: t.start()
    for t in t_guests: t.join(timeout=15)

    # 2) 12 concurrent member POSTs on identical user -> exact 4x 201 and 8x 429
    member_barrier = threading.Barrier(12)
    member_codes, member_errors = [], []
    def member_worker(idx):
        try:
            c = Client(enforce_csrf_checks=True, HTTP_HOST='127.0.0.1')
            c.force_login(member)
            ip = f'198.51.100.{60 + idx}'
            csrf = c.get('/api/me/', REMOTE_ADDR=ip).json()['csrfToken']
            member_barrier.wait(timeout=10)
            res = c.post(
                '/api/notes/harness-cold-start/comments/',
                data=json.dumps({'body': f'同账号突发 #{idx}', 'expectedAuthorKind': 'member'}),
                content_type='application/json',
                HTTP_X_CSRFTOKEN=csrf,
                REMOTE_ADDR=ip,
            )
            with lock: member_codes.append(res.status_code)
        except BaseException as exc:
            with lock: member_errors.append(repr(exc))
        finally:
            connections.close_all()
    t_members = [threading.Thread(target=member_worker, args=(i,)) for i in range(12)]
    for t in t_members: t.start()
    for t in t_members: t.join(timeout=15)

guest_db = Comment.objects.filter(author__isnull=True).count()
member_db = Comment.objects.filter(author=member).count()
connections.close_all()
print(json.dumps({
    'guest_errors': guest_errors,
    'member_errors': member_errors,
    'guest_201': guest_codes.count(201),
    'guest_429': guest_codes.count(429),
    'member_201': member_codes.count(201),
    'member_429': member_codes.count(429),
    'guest_db': guest_db,
    'member_db': member_db,
}))
'''


class CommentRateLimitUnitTests(TestCase):
    def setUp(self) -> None:
        super().setUp()
        cache.clear()
        self.rf = RequestFactory()

    def test_get_client_ip_ports_ipv6_short_xff_and_empty_hop_alignment(self) -> None:
        cases_proxy_1 = (
            ("2001:0db8:0000:0000:0000:0000:0000:0001", "127.0.0.1", "2001:db8::1"),
            ("2001:db8::1", "127.0.0.1", "2001:db8::1"),
            ("[2001:db8::1]:54321", "127.0.0.1", "2001:db8::1"),
            ("198.51.100.42:54321", "127.0.0.1", "198.51.100.42"),
            ("::ffff:198.51.100.42", "127.0.0.1", "198.51.100.42"),
            ("198.51.100.42:99999", "192.0.2.9", "192.0.2.9"),
            ("not-an-ip", "192.0.2.9", "192.0.2.9"),
            (" , , ", "invalid", "unknown"),
        )
        with override_settings(ALLAUTH_TRUSTED_PROXY_COUNT=1):
            for xff, remote_addr, expected in cases_proxy_1:
                with self.subTest(xff=xff, remote=remote_addr):
                    req = self.rf.post(
                        "/api/notes/x/comments/",
                        REMOTE_ADDR=remote_addr,
                        HTTP_X_FORWARDED_FOR=xff,
                    )
                    self.assertEqual(get_client_ip(req), expected)

        # Short XFF chain (< trusted_proxy_count) MUST fall back to REMOTE_ADDR, never hops[0]
        req_short = self.rf.post(
            "/api/notes/x/comments/",
            REMOTE_ADDR="127.0.0.1",
            HTTP_X_FORWARDED_FOR="198.51.100.42",
        )
        with override_settings(ALLAUTH_TRUSTED_PROXY_COUNT=2):
            self.assertEqual(get_client_ip(req_short), "127.0.0.1")

        # Empty hop injection `, ,` must NOT shift index left to attacker-controlled hop
        req_empty_hop = self.rf.post(
            "/api/notes/x/comments/",
            REMOTE_ADDR="127.0.0.1",
            HTTP_X_FORWARDED_FOR="1.2.3.4, , 198.51.100.99",
        )
        with override_settings(ALLAUTH_TRUSTED_PROXY_COUNT=2):
            self.assertEqual(get_client_ip(req_empty_hop), "127.0.0.1")

    @override_settings(
        ALLAUTH_TRUSTED_PROXY_COUNT=0,
        COMMENT_RATE_LIMITS={"member_user": ((2, 60),), "member_ip": ((2, 60),)}, 
    )
    def test_all_or_nothing_shared_ip_429_preserves_member_user_quota(self) -> None:
        shared_ip_req = self.rf.post("/api/notes/x/comments/", REMOTE_ADDR="198.51.100.10")
        # Users 101 & 102 exhaust shared member_ip (2/2)
        self.assertEqual(consume_comment_rate_limit(shared_ip_req, user_id=101), (True, 0))
        self.assertEqual(consume_comment_rate_limit(shared_ip_req, user_id=102), (True, 0))

        # User 303 hits member_ip 429 on shared IP; personal member_user quota must stay untouched
        for _ in range(3):
            allowed, retry_after = consume_comment_rate_limit(shared_ip_req, user_id=303)
            self.assertFalse(allowed)
            self.assertGreaterEqual(retry_after, 1)

        own_ip_req = self.rf.post("/api/notes/x/comments/", REMOTE_ADDR="198.51.100.11")
        self.assertEqual(consume_comment_rate_limit(own_ip_req, user_id=303), (True, 0))
        self.assertEqual(consume_comment_rate_limit(own_ip_req, user_id=303), (True, 0))
        self.assertFalse(consume_comment_rate_limit(own_ip_req, user_id=303)[0])

    def test_filebased_cache_subsecond_tail_429_and_3600s_ttl_persistence(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ceilf6-rl-win-") as tmp_dir:
            cache_cfg = {
                "default": {
                    "BACKEND": FILEBASED_CACHE_BACKEND,
                    "LOCATION": tmp_dir,
                    "OPTIONS": settings.CACHES["default"]["OPTIONS"],
                }
            }
            # 1) Sub-second window tail (<1s remaining) 429 recovers immediately after boundary
            req_short = self.rf.post("/api/notes/x/comments/", REMOTE_ADDR="203.0.113.60")
            with override_settings(
                ALLAUTH_TRUSTED_PROXY_COUNT=0,
                CACHES=cache_cfg,
                COMMENT_RATE_LIMITS={"guest_ip": ((2, 60),)}, 
            ):
                with patch("comments.ratelimit.time.time", return_value=1000.0):
                    self.assertEqual(consume_comment_rate_limit(req_short, user_id=None), (True, 0))
                    self.assertEqual(consume_comment_rate_limit(req_short, user_id=None), (True, 0))
                with patch("comments.ratelimit.time.time", return_value=1059.4):
                    self.assertEqual(consume_comment_rate_limit(req_short, user_id=None), (False, 1))
                with patch("comments.ratelimit.time.time", return_value=1060.2):
                    self.assertEqual(consume_comment_rate_limit(req_short, user_id=None), (True, 0))

            # 2) 3600s window retains count past Django's 300s default TTL
            req_hour = self.rf.post("/api/notes/x/comments/", REMOTE_ADDR="203.0.113.61")
            with override_settings(
                ALLAUTH_TRUSTED_PROXY_COUNT=0,
                CACHES=cache_cfg,
                COMMENT_RATE_LIMITS={"guest_ip": ((2, 3600),)}, 
            ):
                with patch("comments.ratelimit.time.time", return_value=1000.0):
                    self.assertEqual(consume_comment_rate_limit(req_hour, user_id=None), (True, 0))
                with patch("comments.ratelimit.time.time", return_value=1400.0):
                    self.assertEqual(consume_comment_rate_limit(req_hour, user_id=None), (True, 0))
                    self.assertEqual(consume_comment_rate_limit(req_hour, user_id=None), (False, 3200))
                with patch("comments.ratelimit.time.time", return_value=4600.1):
                    self.assertEqual(consume_comment_rate_limit(req_hour, user_id=None), (True, 0))

    def test_concurrent_burst_same_ip_and_same_member_enforce_exact_quota(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ceilf6-rl-burst-") as tmp_dir:
            tmp_path = Path(tmp_dir)
            env = {
                **os.environ,
                "DJANGO_DOTENV_PATH": str(tmp_path / ".env.empty"),
                "DJANGO_DEBUG": "true",
                "DJANGO_ALLOWED_HOSTS": "127.0.0.1,localhost",
                "ALLOW_GUEST_COMMENTS": "true",
                "DJANGO_SETTINGS_MODULE": "config.settings",
                "SQLITE_PATH": str(tmp_path / "burst.sqlite3"),
                "DJANGO_CACHE_PATH": str(tmp_path / "cache"),
                "EMAIL_FILE_PATH": str(tmp_path / "mail"),
            }
            migrate_proc = subprocess.run(
                [sys.executable, str(SERVER_DIR / "manage.py"), "migrate", "--noinput"],
                cwd=str(SERVER_DIR),
                env=env,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            self.assertEqual(migrate_proc.returncode, 0, msg=migrate_proc.stderr)

            burst_proc = subprocess.run(
                [sys.executable, "-c", _BURST_QUOTA_SCRIPT],
                cwd=str(SERVER_DIR),
                env=env,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            self.assertEqual(burst_proc.returncode, 0, msg=burst_proc.stderr)
            result = json.loads(burst_proc.stdout.strip().splitlines()[-1])
            self.assertEqual(result["guest_errors"], [])
            self.assertEqual(result["member_errors"], [])
            self.assertEqual((result["guest_201"], result["guest_429"], result["guest_db"]), (5, 15, 5))
            self.assertEqual((result["member_201"], result["member_429"], result["member_db"]), (4, 8, 4))
