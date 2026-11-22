import json
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]


def workflow(name: str) -> str:
    return (ROOT / ".github" / "workflows" / name).read_text()


class BuildAndWorkflowWiringTest(unittest.TestCase):
    def test_standard_build_bundles_public_assets(self) -> None:
        package = json.loads((ROOT / "site" / "package.json").read_text())
        build = package["scripts"]["build"]
        self.assertIn("vite build", build)
        self.assertIn("deploy/assets.py bundle", build)

    def test_site_deploy_uses_shared_publisher(self) -> None:
        text = workflow("deploy-ecs.yml")
        self.assertIn("deploy/publish.sh site", text)
        self.assertNotIn("cp -r assets site/dist/assets", text)
        self.assertNotIn("tar -czf - -C site/dist", text)
        self.assertIn('"deploy/**"', text)

    def test_scheduled_uploads_use_shared_publisher(self) -> None:
        for name in ("update-stats-schedule.yml", "update-github-contribution-graph.yml"):
            text = workflow(name)
            self.assertIn("deploy/publish.sh assets", text, name)
            self.assertNotIn("scp -i", text, name)

    def test_contribution_upload_only_ships_its_own_svgs(self) -> None:
        text = workflow("update-github-contribution-graph.yml")
        self.assertIn(
            "PUBLISH_FILES: assets/github-contribution-graph.svg assets/github-contribution-graph-compact.svg",
            text,
        )

    def test_verify_runs_deployment_regressions(self) -> None:
        text = workflow("verify.yml")
        self.assertIn("python3 -m unittest discover -s deploy/tests -t .", text)


if __name__ == "__main__":
    unittest.main()
