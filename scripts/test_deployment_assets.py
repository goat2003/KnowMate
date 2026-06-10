from __future__ import annotations

from pathlib import Path
import re
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[1]


class DeploymentAssetsTest(unittest.TestCase):
    def test_go_toolchain_is_pinned_to_patched_release(self) -> None:
        go_mod = _read("goframe-backend/go.mod")
        match = re.search(r"(?m)^go\s+(\d+)\.(\d+)\.(\d+)\s*$", go_mod)
        self.assertIsNotNone(match, "go.mod must pin a full Go patch version")
        version = tuple(int(part) for part in match.groups())
        self.assertGreaterEqual(version, (1, 25, 11))

        dockerfile = _read("goframe-backend/Dockerfile")
        image_match = re.search(r"(?m)^FROM\s+golang:(\d+\.\d+\.\d+)-alpine\s+AS\s+build\s*$", dockerfile)
        self.assertIsNotNone(image_match, "Go builder image must pin the patched Go version")
        image_version = tuple(int(part) for part in image_match.group(1).split("."))
        self.assertEqual(image_version, version)

    def test_e2e_smoke_makes_output_bind_mount_container_writable(self) -> None:
        script = _read("scripts/smoke_e2e.ps1")
        self.assertIn("Set-SmokeOutputDirectory", script)
        self.assertRegex(script, r"(?i)chmod\s+['\"]?0777['\"]?")

    def test_service_dockerfiles_run_as_non_root_and_define_healthchecks(self) -> None:
        for relative in [
            "goframe-backend/Dockerfile",
            "python-agent/Dockerfile",
            "mcp-servers/Dockerfile",
            "web-admin/Dockerfile",
        ]:
            with self.subTest(dockerfile=relative):
                text = _read(relative)
                self.assertRegex(text, r"(?im)^\s*USER\s+(?!root\b)\S+")
                self.assertRegex(text, r"(?im)^\s*HEALTHCHECK\b")

    def test_production_compose_and_kubernetes_assets_exist(self) -> None:
        for relative in [
            "docker-compose.prod.yml",
            "deploy/kubernetes/namespace.yaml",
            "deploy/kubernetes/app-config.yaml",
            "deploy/kubernetes/secrets.example.yaml",
            "deploy/kubernetes/mysql.yaml",
            "deploy/kubernetes/goframe-backend.yaml",
            "deploy/kubernetes/python-agent.yaml",
            "deploy/kubernetes/mcp-servers.yaml",
            "deploy/kubernetes/web-admin.yaml",
            "deploy/kubernetes/migration-job.yaml",
            "deploy/kubernetes/observability.yaml",
        ]:
            with self.subTest(asset=relative):
                self.assertTrue((ROOT / relative).is_file(), f"missing {relative}")

    def test_kubernetes_manifests_use_probes_and_non_root_security_context(self) -> None:
        manifest_text = "\n---\n".join(
            path.read_text(encoding="utf-8")
            for path in sorted((ROOT / "deploy" / "kubernetes").glob("*.yaml"))
        )
        for required in [
            "readinessProbe:",
            "livenessProbe:",
            "runAsNonRoot: true",
            "allowPrivilegeEscalation: false",
            "kind: Job",
            "migration-runner",
        ]:
            with self.subTest(required=required):
                self.assertIn(required, manifest_text)

    def test_kubernetes_manifests_parse_as_yaml_documents(self) -> None:
        for path in sorted((ROOT / "deploy" / "kubernetes").glob("*.yaml")):
            with self.subTest(manifest=path.name):
                documents = [doc for doc in yaml.safe_load_all(path.read_text(encoding="utf-8")) if doc]
                self.assertGreater(len(documents), 0)
                for document in documents:
                    self.assertIn("apiVersion", document)
                    self.assertIn("kind", document)
                    self.assertIn("metadata", document)

    def test_required_release_documents_exist_with_key_sections(self) -> None:
        required_sections = {
            "RELEASE_CHECKLIST.md": ["最终验收", "已知限制", "下一版本规划"],
            "OPERATIONS.md": ["备份", "恢复", "监控", "告警", "回滚"],
            "ARCHITECTURE.md": ["服务", "数据流", "部署", "安全"],
            "KNOWN_LIMITATIONS.md": ["已知限制", "部署", "数据", "安全"],
            "NEXT_VERSION_PLAN.md": ["下一版本规划", "P0", "P1", "P2"],
        }
        for relative, sections in required_sections.items():
            with self.subTest(document=relative):
                text = _read(relative)
                for section in sections:
                    self.assertIn(section, text)


def _read(relative: str) -> str:
    path = ROOT / relative
    if not path.is_file():
        raise AssertionError(f"missing {relative}")
    return path.read_text(encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
