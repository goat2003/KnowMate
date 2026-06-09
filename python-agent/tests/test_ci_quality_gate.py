from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def read_text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_quality_gate_scripts_are_declared() -> None:
    required_scripts = [
        "scripts/quality_gate.ps1",
        "scripts/check_secrets.py",
        "scripts/verify_migrations.ps1",
        "scripts/run_benchmarks.ps1",
    ]

    for relative_path in required_scripts:
        assert (ROOT / relative_path).is_file(), relative_path


def test_quality_gate_runs_required_local_checks() -> None:
    script = read_text("scripts/quality_gate.ps1")

    for required in [
        "check_proto_contract.ps1",
        "check_secrets.py",
        "verify_migrations.ps1",
        "run_benchmarks.ps1",
        "go fmt",
        "go vet",
        "go test ./...",
        "pytest",
        "ruff check",
        "mypy",
        "pip-audit",
        "govulncheck",
        "docker build",
        "smoke_e2e.ps1",
    ]:
        assert required in script


def test_github_actions_quality_gate_has_required_jobs() -> None:
    workflow = read_text(".github/workflows/ci.yml")

    for required in [
        "go-quality",
        "python-quality",
        "proto-and-migrations",
        "docker-build",
        "vulnerability-scan",
        "e2e-smoke",
        "actions/setup-go",
        "actions/setup-python",
        "actions/upload-artifact",
        "check_proto_contract.ps1",
        "verify_migrations.ps1",
        "check_secrets.py",
        "go test ./... -coverprofile",
        "pytest --cov",
        "docker build",
        "smoke_e2e.ps1",
    ]:
        assert required in workflow


def test_python_dev_requirements_cover_lint_type_coverage_and_audit() -> None:
    requirements = read_text("requirements-dev.txt")

    for package in ["pytest-cov", "ruff", "mypy", "pip-audit"]:
        assert package in requirements


def test_readme_documents_local_testing_and_ci_gate() -> None:
    readme = read_text("README.md")

    for required in [
        "本地测试与 CI 质量门禁",
        "scripts\\quality_gate.ps1",
        "Go 单元测试",
        "Python 单元测试",
        "MCP Tool 契约测试",
        "gRPC 协议兼容测试",
        "MySQL、Milvus、Neo4j 集成测试",
        "端到端测试",
        "故障注入测试",
        "基准测试",
        "禁止提交未同步的 Proto 生成代码",
        "禁止提交明显密钥",
    ]:
        assert required in readme
