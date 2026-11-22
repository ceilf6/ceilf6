import contextlib
import functools
import http.server
import os
import pathlib
import shutil
import tempfile
import threading
import unittest

from deploy import assets


VALID_SVG = b'<svg xmlns="http://www.w3.org/2000/svg"><rect width="1" height="1"/></svg>'


def write_assets(root: pathlib.Path, names=None) -> None:
    root.mkdir(parents=True, exist_ok=True)
    for name in names or assets.REQUIRED:
        body = VALID_SVG if name.endswith(".svg") else b"\xff\xd8\xff\xd9"
        (root / name).write_bytes(body)


class Server:
    def __init__(self, directory: pathlib.Path, routes=None) -> None:
        handler = functools.partial(_Handler, directory=str(directory), routes=routes or {})
        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}"

    def close(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()


class _Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, directory=None, routes=None, **kwargs) -> None:
        self.routes = routes or {}
        super().__init__(*args, directory=directory, **kwargs)

    def do_GET(self) -> None:
        if self.path in self.routes:
            entry = self.routes[self.path]
            status, (body, content_type) = (
                (entry[0], entry[1:]) if len(entry) == 3 else (200, entry)
            )
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        super().do_GET()

    def log_message(self, *args) -> None:
        pass


@contextlib.contextmanager
def serving(directory: pathlib.Path, routes=None):
    server = Server(directory, routes)
    try:
        yield server.url
    finally:
        server.close()


class ValidateAndBundleTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="asset-contract-test-"))
        self.addCleanup(shutil.rmtree, self.tmp)

    def test_bundle_copies_required_and_extra_assets_with_public_modes(self) -> None:
        source = self.tmp / "assets"
        write_assets(source)
        (source / "extra.svg").write_bytes(VALID_SVG)
        dest = self.tmp / "dist" / "assets"

        assets.bundle(source, dest)

        for name in assets.REQUIRED:
            self.assertTrue((dest / name).is_file(), name)
        self.assertTrue((dest / "extra.svg").is_file())
        self.assertEqual(0o755, dest.stat().st_mode & 0o777)
        self.assertEqual(0o644, (dest / "github-stats-card.svg").stat().st_mode & 0o777)

    def test_validate_rejects_missing_required_asset(self) -> None:
        source = self.tmp / "assets"
        write_assets(source, ("blog-card.svg",))

        with self.assertRaisesRegex(assets.AssetError, "vlog-card.svg"):
            assets.validate(source)

    def test_validate_rejects_empty_required_asset(self) -> None:
        source = self.tmp / "assets"
        write_assets(source)
        (source / "vlog-card.svg").write_bytes(b"")

        with self.assertRaisesRegex(assets.AssetError, "vlog-card.svg"):
            assets.validate(source)

    def test_validate_rejects_malformed_svg(self) -> None:
        source = self.tmp / "assets"
        write_assets(source)
        (source / "blog-card.svg").write_bytes(b"<html>404 Not Found</html>")

        with self.assertRaisesRegex(assets.AssetError, "blog-card.svg"):
            assets.validate(source)

    def test_failed_validation_leaves_destination_untouched(self) -> None:
        source = self.tmp / "assets"
        write_assets(source, ("blog-card.svg",))
        dest = self.tmp / "dist" / "assets"
        dest.mkdir(parents=True)
        marker = dest / "previous-build.svg"
        marker.write_bytes(VALID_SVG)

        with self.assertRaises(assets.AssetError):
            assets.bundle(source, dest)

        self.assertEqual([marker], list(dest.iterdir()))


class SmokeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="asset-smoke-test-"))
        self.addCleanup(shutil.rmtree, self.tmp)
        write_assets(self.tmp / "assets")

    def test_smoke_accepts_reachable_assets(self) -> None:
        with serving(self.tmp) as base:
            results = assets.smoke(base)

        self.assertEqual(len(assets.REQUIRED), len(results))

    def test_smoke_rejects_missing_asset(self) -> None:
        (self.tmp / "assets" / "vlog-card.svg").unlink()
        with serving(self.tmp) as base:
            with self.assertRaisesRegex(assets.AssetError, "vlog-card.svg"):
                assets.smoke(base)

    def test_smoke_rejects_spa_html_fallback_for_svg(self) -> None:
        routes = {"/assets/blog-card.svg": (b"<!doctype html><html></html>", "text/html")}
        with serving(self.tmp, routes) as base:
            with self.assertRaisesRegex(assets.AssetError, "blog-card.svg.*text/html"):
                assets.smoke(base, required={"blog-card.svg": "image/svg+xml"})

    def test_smoke_rejects_non_svg_body_with_svg_content_type(self) -> None:
        routes = {"/assets/blog-card.svg": (b"<html>oops</html>", "image/svg+xml")}
        with serving(self.tmp, routes) as base:
            with self.assertRaisesRegex(assets.AssetError, "blog-card.svg"):
                assets.smoke(base, required={"blog-card.svg": "image/svg+xml"})


if __name__ == "__main__":
    unittest.main()
