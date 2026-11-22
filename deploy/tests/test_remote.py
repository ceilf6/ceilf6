import os
import pathlib
import shutil
import tempfile
import unittest
from unittest import mock

from deploy import assets, remote

from .test_assets import serving


def svg(label: bytes) -> bytes:
    return b'<svg xmlns="http://www.w3.org/2000/svg"><title>' + label + b"</title></svg>"


def make_assets(root: pathlib.Path, label: bytes = b"valid") -> None:
    root.mkdir(parents=True, exist_ok=True)
    for name in assets.REQUIRED:
        body = svg(label) if name.endswith(".svg") else b"\xff\xd8\xff\xd9"
        (root / name).write_bytes(body)


class PublishAssetsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="publish-assets-test-"))
        self.addCleanup(shutil.rmtree, self.tmp)
        self.live = self.tmp / "wangjinghong"
        self.staging = self.tmp / "staged-assets"
        self.lock = self.tmp / "deploy.lock"

    def test_creates_missing_directory_with_public_modes(self) -> None:
        make_assets(self.staging)
        self.live.mkdir()

        remote.publish_assets(self.staging, self.live, lock_path=self.lock)

        published = self.live / "assets"
        self.assertEqual(0o755, published.stat().st_mode & 0o777)
        for name in assets.REQUIRED:
            self.assertTrue((published / name).is_file(), name)
            self.assertEqual(0o644, (published / name).stat().st_mode & 0o777)

    def test_normalizes_existing_unreadable_directory(self) -> None:
        make_assets(self.staging)
        (self.live / "assets").mkdir(parents=True)
        (self.live / "assets").chmod(0o744)

        remote.publish_assets(self.staging, self.live, lock_path=self.lock)

        self.assertEqual(0o755, (self.live / "assets").stat().st_mode & 0o777)

    def test_preserves_unrelated_files(self) -> None:
        make_assets(self.staging)
        published = self.live / "assets"
        published.mkdir(parents=True)
        keep = published / "keep-me.txt"
        keep.write_text("keep")

        remote.publish_assets(self.staging, self.live, lock_path=self.lock)

        self.assertEqual("keep", keep.read_text())

    def test_rejects_invalid_staging_without_touching_live(self) -> None:
        self.staging.mkdir()
        (self.staging / "blog-card.svg").write_bytes(b"<html>broken</html>")
        published = self.live / "assets"
        published.mkdir(parents=True)
        existing = published / "vlog-card.svg"
        existing.write_bytes(b"existing")

        with self.assertRaises(assets.AssetError):
            remote.publish_assets(self.staging, self.live, lock_path=self.lock)

        self.assertEqual(b"existing", existing.read_bytes())

    def test_partial_upload_updates_only_listed_files(self) -> None:
        make_assets(self.live / "assets", b"old card")
        self.staging.mkdir()
        (self.staging / "blog-card.svg").write_bytes(svg(b"new card"))

        remote.publish_assets(self.staging, self.live, lock_path=self.lock)

        self.assertEqual(svg(b"new card"), (self.live / "assets" / "blog-card.svg").read_bytes())
        self.assertEqual(svg(b"old card"), (self.live / "assets" / "vlog-card.svg").read_bytes())

    def test_partial_upload_rolls_back_when_required_assets_are_missing(self) -> None:
        self.live.mkdir()
        self.staging.mkdir()
        (self.staging / "extra-only.svg").write_bytes(svg(b"extra"))

        with self.assertRaises(assets.AssetError):
            remote.publish_assets(self.staging, self.live, lock_path=self.lock)

        self.assertFalse((self.live / "assets" / "extra-only.svg").exists())

    def test_restores_previous_files_when_origin_check_fails(self) -> None:
        make_assets(self.staging)
        published = self.live / "assets"
        published.mkdir(parents=True)
        old_card = published / "blog-card.svg"
        old_card.write_bytes(b"old card")

        def failing_check() -> None:
            raise assets.AssetError("blog-card.svg: HTTP 404")

        with self.assertRaises(assets.AssetError):
            remote.publish_assets(
                self.staging, self.live, lock_path=self.lock, origin_check=failing_check
            )

        self.assertEqual(b"old card", old_card.read_bytes())
        self.assertFalse((published / "github-stats-card.svg").exists())


class PublishSiteTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="publish-site-test-"))
        self.addCleanup(shutil.rmtree, self.tmp)
        self.live = self.tmp / "wangjinghong"
        self.staging = self.tmp / "wangjinghong.new"
        self.lock = self.tmp / "deploy.lock"
        make_assets(self.live / "assets", b"old card")
        (self.live / "index.html").write_text("OLD")
        (self.live / "static").mkdir()
        (self.live / "static" / "old-chunk.js").write_text("chunk")
        (self.live / "harness").mkdir()
        (self.live / "harness" / "index.html").write_text("dashboard")

    def make_staging(self) -> None:
        make_assets(self.staging / "assets", b"new card")
        (self.staging / "index.html").write_text("NEW")

    def test_rejects_incomplete_bundle_before_swapping(self) -> None:
        make_assets(self.staging / "assets")
        (self.staging / "assets" / "vlog-card.svg").unlink()
        (self.staging / "index.html").write_text("NEW")

        with self.assertRaises(assets.AssetError):
            remote.publish_site(self.staging, self.live, lock_path=self.lock)

        self.assertEqual("OLD", (self.live / "index.html").read_text())

    def test_reader_preflight_checks_paths_that_exist_in_staging(self) -> None:
        self.make_staging()
        checked = []

        def spy(root, user, names):
            for name in names:
                self.assertTrue((pathlib.Path(root) / name).exists(), f"{root}/{name}")
            checked.append(str(root))

        with mock.patch.object(remote, "_assert_readable", spy):
            remote.publish_site(
                self.staging, self.live, lock_path=self.lock, reader_user="www-data"
            )

        self.assertIn(str(self.staging / "assets"), checked)

    def test_swaps_site_and_preserves_runtime_directories(self) -> None:
        self.make_staging()

        remote.publish_site(self.staging, self.live, lock_path=self.lock)

        self.assertEqual("NEW", (self.live / "index.html").read_text())
        self.assertTrue((self.live / "static" / "old-chunk.js").is_file())
        self.assertTrue((self.live / "harness" / "index.html").is_file())
        self.assertEqual("OLD", (self.live.with_name("wangjinghong.old") / "index.html").read_text())

    def test_restores_previous_site_when_origin_check_fails(self) -> None:
        self.make_staging()
        calls = []

        def failing_check() -> None:
            calls.append("probe")
            raise assets.AssetError("homepage unavailable")

        with self.assertRaises(assets.AssetError):
            remote.publish_site(
                self.staging, self.live, lock_path=self.lock, origin_check=failing_check
            )

        self.assertEqual(["probe"], calls)
        self.assertEqual("OLD", (self.live / "index.html").read_text())
        self.assertEqual(svg(b"old card"), (self.live / "assets" / "blog-card.svg").read_bytes())
        self.assertTrue((self.live / "static" / "old-chunk.js").is_file())
        self.assertEqual("dashboard", (self.live / "harness" / "index.html").read_text())


class OriginCheckTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="origin-check-test-"))
        self.addCleanup(shutil.rmtree, self.tmp)
        make_assets(self.tmp / "assets")
        (self.tmp / "index.html").write_text("<html>ok</html>")

    def test_accepts_reachable_homepage_and_assets(self) -> None:
        with serving(self.tmp) as base:
            remote._origin_check(base, None)()

    def test_rejects_broken_homepage_even_when_assets_load(self) -> None:
        routes = {"/": (500, b"<html>error</html>", "text/html")}
        with serving(self.tmp, routes) as base:
            with self.assertRaisesRegex(assets.AssetError, "homepage"):
                remote._origin_check(base, None)()

    def test_rejects_unreachable_origin(self) -> None:
        with self.assertRaises(assets.AssetError):
            remote._origin_check("http://127.0.0.1:9", None)()
