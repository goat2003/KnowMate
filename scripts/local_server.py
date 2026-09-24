"""Isolated, single-admin local deployment. No access to existing project volumes.

Requires Python 3.12, PyYAML, cryptography, and Docker Compose v2.
Secrets and rendered configuration stay under ignored .local-server/.
"""
from __future__ import annotations

import argparse
import base64
from datetime import datetime, timedelta, timezone
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.request

import yaml

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / ".local-server"
IMAGES = {"goframe-backend": "goframe-backend", "python-agent": "python-agent",
          "web-admin": "web-admin", "migration-runner": "goframe-backend"}
INFRA = ["mysql", "milvus-etcd", "milvus-minio", "milvus-standalone", "neo4j"]
APPLICATION = ["embedding-mcp", "fetch-mcp", "milvus-mcp", "neo4j-mcp", "python-agent", "goframe-backend", "web-admin", "gateway"]


def run(args, *, data=None, capture=True, timeout=600, cwd=ROOT, env=None):
    result = subprocess.run(args, input=data, stdout=subprocess.PIPE if capture else None,
                            stderr=subprocess.PIPE if capture else None, cwd=cwd, env=env, timeout=timeout)
    if result.returncode:
        # Commands can include container credentials in their output. Only expose the command name.
        raise RuntimeError(f"{args[0]} {args[1]} exited {result.returncode}; inspect service logs locally")
    return result.stdout or b""


def folder(stage):
    if stage not in {"rehearsal", "production", "restore"}:
        raise ValueError("unsupported local stage")
    return STATE / stage


def compose(stage, *args, **kwargs):
    return run(["docker", "compose", "--project-directory", str(ROOT), "-p", f"knowmate-{stage}",
                "-f", str(folder(stage) / "compose.yaml"), *args], **kwargs)


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def protect_state():
    STATE.mkdir(exist_ok=True)
    if os.name == "nt":
        user = run(["whoami"]).decode().strip()
        run(["icacls", str(STATE), "/inheritance:r", "/grant:r", f"{user}:(OI)(CI)F",
             "*S-1-5-18:(OI)(CI)F", "*S-1-5-32-544:(OI)(CI)F"])
    else:
        STATE.chmod(0o700)


def certificate(path):
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "KnowMate localhost")])
    now = datetime.now(timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - timedelta(minutes=5))
            .not_valid_after(now + timedelta(days=365))
            .add_extension(x509.SubjectAlternativeName([x509.DNSName("localhost"),
                           x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]), critical=False)
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .sign(key, hashes.SHA256()))
    (path / "tls.key").write_bytes(key.private_bytes(serialization.Encoding.PEM,
                                serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    (path / "tls.crt").write_bytes(cert.public_bytes(serialization.Encoding.PEM))


def initialize(stage):
    protect_state()
    state = folder(stage)
    state.mkdir(exist_ok=True)
    if not (state / "secrets.json").exists():
        credentials = {key: secrets.token_hex(32) for key in ["MYSQL_ROOT_PASSWORD", "MYSQL_PASSWORD",
                       "GOFRAME_API_TOKEN", "AGENT_GRPC_AUTH_TOKEN", "NEO4J_PASSWORD", "MINIO_ROOT_PASSWORD",
                       "GRAFANA_ADMIN_PASSWORD", "ADMIN_PASSWORD"]}
        write(state / "secrets.json", json.dumps(credentials, indent=2))
    credentials = json.loads((state / "secrets.json").read_text())
    if not (state / "admin-credentials.txt").exists():
        write(state / "admin-credentials.txt", f"Username: admin\nPassword: {credentials['ADMIN_PASSWORD']}\n")
    if not (state / "htpasswd").exists():
        hashed = run(["docker", "run", "--rm", "-i", "--entrypoint", "python", "python:3.12-slim", "-W", "ignore", "-c",
                      "import crypt,sys; print(crypt.crypt(sys.stdin.read(), crypt.mksalt(crypt.METHOD_SHA512)))"],
                     data=credentials["ADMIN_PASSWORD"].encode()).decode().strip()
        write(state / "htpasswd", "admin:" + hashed + "\n")
    if not all((state / name).exists() for name in ["tls.crt", "tls.key"]):
        certificate(state)
    if not (state / "model.env").exists():
        write(state / "model.env", "# Fill these values, then run start --stage production.\n"
              "OPENAI_BASE_URL=https://api.openai.com/v1\nOPENAI_API_KEY=\nOPENAI_MODEL=gpt-4.1-mini\n"
              "EMBEDDING_BASE_URL=https://api.openai.com/v1\nEMBEDDING_API_KEY=\n"
              "EMBEDDING_MODEL=text-embedding-3-large\nEMBEDDING_DIMENSION=3072\n")
    if not (state / "wechat.env").exists():
        shutil.copyfile(ROOT / "configs/env/wechat.env.example", state / "wechat.env")
    if not (state / "sources.yaml").exists():
        sources = yaml.safe_load((ROOT / "configs/crawler/prod.sources.example.yaml").read_text(encoding="utf-8"))
        # Bounded real source. Production operators can add more reviewed sources here.
        sources["crawler"]["sources"] = [s for s in sources["crawler"]["sources"] if s["name"] == "huggingface-blog"]
        sources["crawler"].update(source_max_items=2, run_max_articles=2, retry_times=1)
        write(state / "sources.yaml", yaml.safe_dump(sources, sort_keys=False))
    render(stage)
    print(f"Initialized {stage}. Credentials: {state / 'admin-credentials.txt'}")


def read_model(stage):
    values = {}
    for line in (folder(stage) / "model.env").read_text(encoding="utf-8-sig").splitlines():
        if line.strip() and not line.lstrip().startswith("#"):
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip().strip('\"').strip("'")
    values["EMBEDDING_API_KEY"] = values.get("EMBEDDING_API_KEY") or values.get("OPENAI_API_KEY", "")
    return values


def render(stage):
    state = folder(stage)
    creds = json.loads((state / "secrets.json").read_text())
    model = read_model(stage)
    rehearsal = stage != "production"
    port = 9443 if rehearsal else 8443
    variables = {**creds, **model, "MINIO_ROOT_USER": "knowmate", "GRAFANA_ADMIN_USER": "admin",
                 "CRAWLER_CONFIG_PATH": (state / "sources.yaml").as_posix()}
    text = (ROOT / "docker-compose.prod.yml").read_text(encoding="utf-8")
    pattern = re.compile(r"\$\{([A-Z_][A-Z0-9_]*)(?:(:-|:\?)([^}]*))?\}")
    text = pattern.sub(lambda m: str(variables.get(m[1], m[3] if m[2] == ":-" else "")), text)
    spec = yaml.safe_load(text)
    services = spec["services"]
    for name, service in services.items():
        service.pop("ports", None)
        service["logging"] = {"driver": "json-file", "options": {"max-size": "10m", "max-file": "3"}}
        if "build" in service:
            service.pop("build")
            image = IMAGES.get(name, "mcp-servers")
            service["image"] = f"knowmate-local/{image}:ready"
        service["volumes"] = [v.replace("./", ROOT.as_posix() + "/", 1) if v.startswith("./") else v
                              for v in service.get("volumes", [])]
    services["neo4j"]["image"] = "neo4j:5.26-community"
    services["milvus-standalone"]["image"] = "milvusdb/milvus:v2.6.15"
    services["neo4j"]["environment"].update(NEO4J_server_memory_heap_initial__size="256m",
                                           NEO4J_server_memory_heap_max__size="512m",
                                           NEO4J_server_memory_pagecache_size="256m")
    for name in ["python-agent", "goframe-backend"]:
        services[name]["environment"]["APP_ENV"] = "rehearsal" if rehearsal else "production"
    agent = services["python-agent"]
    agent["environment"].update(LLM_PROVIDER="mock" if rehearsal else "openai", MOCK_LLM=str(rehearsal).lower())
    agent["healthcheck"] = {"test": ["CMD", "python", "healthcheck.py"], "interval": "5s", "timeout": "5s", "retries": 30}
    embed = services["embedding-mcp"]["environment"]
    embed.update(EMBEDDING_PROVIDER="memory" if rehearsal else "openai", OPENAI_BASE_URL=model["EMBEDDING_BASE_URL"])
    embed["APP_ENV"] = "rehearsal" if rehearsal else "production"
    services["goframe-backend"]["environment"].update(AGENT_TIMEOUT_SECONDS="180", HARNESS_TASK_TIMEOUT_SECONDS="600")
    wxpath = state / "wechat.env"
    if not wxpath.exists():
        shutil.copyfile(ROOT / "configs/env/wechat.env.example", wxpath)
    wx = {}
    for line in wxpath.read_text(encoding="utf-8-sig").splitlines():
        if line.strip() and not line.lstrip().startswith("#"):
            key, value = line.split("=", 1)
            wx[key.strip()] = value.strip().strip('"').strip("'")
    for name in ["WECHAT_ENABLED", "WECHAT_OAUTH_REDIRECT_URI", "WECHAT_CHAT_PAGE_URL", "WECHAT_ALLOWED_ORIGINS", "WECHAT_DEV_ANONYMOUS"]:
        services["goframe-backend"]["environment"][name] = wx.get(name, "false" if name in {"WECHAT_ENABLED", "WECHAT_DEV_ANONYMOUS"} else "")
    # Model calls are the only deferred integration. Real databases and fetch stay enabled in rehearsal.
    spec["secrets"] = {}
    for svc, names in {
        "python-agent": ["AGENT_GRPC_AUTH_TOKEN", "OPENAI_API_KEY"],
        "goframe-backend": ["GOFRAME_API_TOKEN", "AGENT_GRPC_AUTH_TOKEN", "MYSQL_DSN"],
        "embedding-mcp": ["OPENAI_API_KEY"],
        "mysql": ["MYSQL_ROOT_PASSWORD", "MYSQL_PASSWORD"],
        "migration-runner": ["MYSQL_PASSWORD"],
    }.items():
        service = services[svc]
        service["secrets"] = []
        for name in names:
            secret_id = f"{svc}-{name}".lower().replace("_", "-")
            value = service["environment"].pop(name, "")
            if svc == "embedding-mcp" and name == "OPENAI_API_KEY":
                value = model["EMBEDDING_API_KEY"]
            path = state / "secrets" / secret_id
            write(path, str(value))
            spec["secrets"][secret_id] = {"file": path.as_posix()}
            service["secrets"].append(secret_id)
            service["environment"][name + "_FILE"] = "/run/secrets/" + secret_id
    services["mysql"]["healthcheck"]["test"] = ["CMD-SHELL", 'MYSQL_PWD=$$(cat $$MYSQL_ROOT_PASSWORD_FILE) mysqladmin ping -h 127.0.0.1 -uroot --silent']
    for name in ["WECHAT_APP_ID", "WECHAT_APP_SECRET", "WECHAT_TOKEN", "WECHAT_ENCODING_AES_KEY", "WECHAT_SESSION_SECRET"]:
        secret_id = name.lower().replace("_", "-")
        path = state / "secrets" / secret_id
        write(path, wx.get(name, ""))
        spec["secrets"][secret_id] = {"file": path.as_posix()}
        services["goframe-backend"]["secrets"].append(secret_id)
        services["goframe-backend"]["environment"][name + "_FILE"] = "/run/secrets/" + secret_id
    prom = yaml.safe_load((ROOT / "observability/prometheus.yml").read_text())
    prom["scrape_configs"].append({"job_name": "local-operations", "static_configs": [{"targets": ["alert-sink:8099"]}]})
    for job in prom["scrape_configs"]:
        if job["job_name"] == "prometheus":
            job["metrics_path"] = "/monitor/metrics"
        if job["job_name"] == "goframe-backend":
            job["authorization"] = {"credentials_file": "/run/secrets/goframe-backend-goframe-api-token"}
    write(state / "prometheus.yaml", yaml.safe_dump(prom, sort_keys=False))
    services["prometheus"]["secrets"] = ["goframe-backend-goframe-api-token"]
    services["prometheus"]["volumes"][0] = f"{state.as_posix()}/prometheus.yaml:/etc/prometheus/prometheus.yml:ro"
    services["prometheus"]["command"] += ["--web.external-url=/monitor/", "--web.route-prefix=/monitor/"]
    am = {"route": {"receiver": "local-journal", "group_wait": "1s", "group_interval": "10s", "repeat_interval": "1h"},
          "receivers": [{"name": "local-journal", "webhook_configs": [{"url": "http://alert-sink:8099/alerts", "send_resolved": True}]}]}
    write(state / "alertmanager.yaml", yaml.safe_dump(am, sort_keys=False))
    services["alertmanager"] = {"image": "prom/alertmanager:v0.28.1", "restart": "unless-stopped",
        "command": ["--config.file=/etc/alertmanager/config.yml", f"--web.external-url=https://localhost:{port}/alerts/", "--web.route-prefix=/"],
        "volumes": [f"{state.as_posix()}/alertmanager.yaml:/etc/alertmanager/config.yml:ro", "alertmanager-data:/alertmanager"]}
    (state / "events").mkdir(exist_ok=True)
    services["alert-sink"] = {"image": "python:3.12-slim", "restart": "unless-stopped", "user": "10001:10001",
        "environment": {"KNOWMATE_STAGE": stage}, "command": ["python", "/app/alert_sink.py"],
        "volumes": [f"{ROOT.as_posix()}/deploy/local/alert_sink.py:/app/alert_sink.py:ro",
                    f"{state.as_posix()}/events:/events", f"{STATE.as_posix()}/backups:/backups:ro"]}
    (STATE / "backups").mkdir(exist_ok=True)
    services["jaeger"] = {"image": "jaegertracing/all-in-one:1.64.0", "restart": "unless-stopped",
                          "environment": {"COLLECTOR_OTLP_ENABLED": "true", "QUERY_BASE_PATH": "/tracing"}}
    services["grafana"]["environment"].update(GF_SERVER_ROOT_URL=f"https://localhost:{port}/grafana/",
                                              GF_SERVER_SERVE_FROM_SUB_PATH="true", GF_USERS_ALLOW_SIGN_UP="false")
    gateway = (ROOT / "deploy/local/gateway.conf.template").read_text().replace("@@PORT@@", str(port)).replace("@@TOKEN@@", creds["GOFRAME_API_TOKEN"])
    write(state / "gateway.conf", gateway)
    services["gateway"] = {"image": "nginxinc/nginx-unprivileged:1.27-alpine", "restart": "unless-stopped",
        "ports": [f"127.0.0.1:{port}:8443"], "volumes": [
            f"{state.as_posix()}/{name}:/etc/local/{name}:ro" for name in ["tls.crt", "tls.key", "htpasswd"]] + [
            f"{state.as_posix()}/gateway.conf:/etc/nginx/conf.d/default.conf:ro"],
        "depends_on": {s: {"condition": "service_started"} for s in ["web-admin", "prometheus", "alertmanager", "grafana", "jaeger"]}}
    spec["volumes"]["alertmanager-data"] = None
    # Compose does not detect content changes in bind mounts or file secrets.
    # Change only the affected service's label so `up` reloads its configuration.
    for service in services.values():
        content = hashlib.sha256()
        paths = [Path(spec["secrets"][name]["file"]) for name in service.get("secrets", [])]
        for mount in service.get("volumes", []):
            if isinstance(mount, str):
                source = mount.rsplit(":/", 1)[0]
                path = Path(source)
                if path.is_file():
                    paths.append(path)
                elif path.is_dir() and mount.endswith(":ro") and path.is_relative_to(ROOT) and not path.is_relative_to(STATE):
                    paths.extend(sorted(p for p in path.rglob("*") if p.is_file()))
        for path in paths:
            content.update(path.as_posix().encode())
            content.update(path.read_bytes())
        service.setdefault("labels", {})["knowmate.config-sha256"] = content.hexdigest()
    # A consistent artifact; no Docker secrets are printed to the terminal.
    write(state / "compose.yaml", yaml.safe_dump(spec, sort_keys=False))
    compose(stage, "config", "--quiet")


def request(stage, path, *, authenticated=True, body=None, method=None, origin=None):
    port = 8443 if stage == "production" else 9443
    state = folder(stage)
    context = ssl.create_default_context(cafile=str(state / "tls.crt"))
    headers = {"Content-Type": "application/json"}
    if authenticated:
        creds = json.loads((state / "secrets.json").read_text())
        headers["Authorization"] = "Basic " + base64.b64encode(f"admin:{creds['ADMIN_PASSWORD']}".encode()).decode()
    if origin:
        headers["Origin"] = origin
    req = urllib.request.Request(f"https://localhost:{port}{path}",
           data=json.dumps(body).encode() if body is not None else None, headers=headers, method=method)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), urllib.request.HTTPSHandler(context=context))
    try:
        with opener.open(req, timeout=650) as result:
            return result.status, result.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def model_preflight(stage):
    model = read_model(stage)
    if not model.get("OPENAI_API_KEY") or not model.get("EMBEDDING_API_KEY"):
        raise RuntimeError("BLOCKED: supply chat and embedding API configuration in .local-server/production/model.env")
    from urllib.parse import urlparse
    for key in ["OPENAI_BASE_URL", "EMBEDDING_BASE_URL"]:
        url = urlparse(model[key])
        if url.scheme != "https" or not url.hostname or url.username or url.password:
            raise ValueError(f"{key} must use HTTPS without embedded credentials")
    for base, key, suffix, body in [
        (model["OPENAI_BASE_URL"], model["OPENAI_API_KEY"], "/chat/completions", {"model": model["OPENAI_MODEL"],
         "messages": [{"role": "user", "content": 'Reply with JSON: {"ready":true}'}], "response_format": {"type": "json_object"}}),
        (model["EMBEDDING_BASE_URL"], model["EMBEDDING_API_KEY"], "/embeddings", {"model": model["EMBEDDING_MODEL"],
         "input": ["KnowMate readiness probe"], "dimensions": int(model["EMBEDDING_DIMENSION"])})]:
        req = urllib.request.Request(base.rstrip("/") + suffix, data=json.dumps(body).encode(),
              headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=45) as response:
            data = json.load(response)
        if suffix == "/chat/completions":
            if json.loads(data["choices"][0]["message"]["content"]).get("ready") is not True:
                raise ValueError("chat JSON probe failed")
        elif len(data["data"][0]["embedding"]) != int(model["EMBEDDING_DIMENSION"]):
            raise ValueError("embedding dimension mismatch")
    print("Real model and embedding preflight passed")


def verify(stage):
    evidence = {}
    for path in ["/", "/api/runs", "/monitor/", "/alerts/"]:
        status, _ = request(stage, path, authenticated=False)
        if status != 401:
            raise RuntimeError(f"unauthenticated {path} returned {status}")
    evidence["anonymous_rejected"] = True
    status, _ = request(stage, "/api/feedback", method="POST", body={}, origin="https://untrusted.invalid")
    if status != 403:
        raise RuntimeError("cross-origin write was not rejected")
    evidence["foreign_origin_rejected"] = True
    for path in ["/", "/api/ready", "/api/health", "/api/runs", "/monitor/-/ready", "/alerts/-/ready", "/grafana/api/health"]:
        status, data = request(stage, path)
        if status != 200:
            raise RuntimeError(f"authenticated {path} returned {status}")
        if path == "/api/health":
            evidence["health"] = json.loads(data)
    if stage == "production" and evidence["health"].get("agent", {}).get("mock_mode", True):
        raise RuntimeError("production health reports mock mode")
    status, body = request(stage, "/monitor/api/v1/targets")
    targets = json.loads(body)["data"]["activeTargets"]
    expected_jobs = {job["job_name"] for job in yaml.safe_load((folder(stage) / "prometheus.yaml").read_text())["scrape_configs"]}
    actual_jobs = {target["labels"].get("job") for target in targets}
    if expected_jobs - actual_jobs:
        raise RuntimeError(f"missing monitoring targets: {sorted(expected_jobs - actual_jobs)}")
    down = [t["labels"] for t in targets if t["health"] != "up"]
    if down:
        raise RuntimeError(f"monitoring targets not up: {down}")
    evidence["monitoring_targets_up"] = len(targets)
    evidence["verified_at"] = datetime.now(timezone.utc).isoformat()
    write(folder(stage) / "verification.json", json.dumps(evidence, indent=2))
    print(json.dumps(evidence, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["init", "render", "build", "prepare", "start", "check", "stop", "preflight"])
    parser.add_argument("--stage", choices=["production", "rehearsal"], default="production")
    parser.add_argument("--cached-runtime", action="store_true", help="Build Go using host module cache and existing local runtime image")
    args = parser.parse_args()
    if args.action == "init":
        initialize(args.stage)
    elif args.action == "build":
        for service in ["goframe-backend", "python-agent", "mcp-servers", "web-admin"]:
            if service == "goframe-backend" and args.cached_runtime:
                build_cached_backend()
                continue
            run(["docker", "build", "-f", f"{service}/Dockerfile", "-t", f"knowmate-local/{service}:ready", "."], capture=False, timeout=1800)
    elif args.action == "render":
        render(args.stage)
    elif args.action == "preflight":
        model_preflight(args.stage)
    elif args.action == "prepare":
        render(args.stage)
        compose(args.stage, "up", "-d", "--wait", "--wait-timeout", "240", *INFRA, capture=False)
    elif args.action == "start":
        if args.stage == "production":
            model_preflight(args.stage)
        render(args.stage)
        compose(args.stage, "up", "-d", "--wait", "--wait-timeout", "300", capture=False)
        for _ in range(20):
            try:
                verify(args.stage)
                break
            except (RuntimeError, OSError):
                time.sleep(5)
        else:
            verify(args.stage)
    elif args.action == "check":
        verify(args.stage)
    elif args.action == "stop":
        compose(args.stage, "stop", capture=False)


def build_cached_backend():
    target = ROOT / "artifacts/local-build"
    target.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, GOOS="linux", GOARCH="amd64", CGO_ENABLED="0", GOPROXY="off")
    run(["go", "build", "-trimpath", "-o", str(target / "goframe-backend"), "."],
        cwd=ROOT / "goframe-backend", env=env, timeout=600)
    shutil.copytree(ROOT / "goframe-backend/manifest", target / "manifest", dirs_exist_ok=True)
    shutil.copytree(ROOT / "shared/sql", target / "sql", dirs_exist_ok=True)
    shutil.copyfile(ROOT / "scripts/run_migrations.sh", target / "run_migrations.sh")
    write(target / "Dockerfile", "FROM knowledge-post-agent-goframe-backend:latest\n"
          "COPY --chown=knowmate:knowmate --chmod=755 goframe-backend /app/goframe-backend/goframe-backend\n"
          "COPY --chown=knowmate:knowmate manifest /app/goframe-backend/manifest\n"
          "COPY --chown=knowmate:knowmate sql /app/shared/sql\n"
          "COPY --chown=knowmate:knowmate --chmod=755 run_migrations.sh /app/scripts/run_migrations.sh\n"
          "HEALTHCHECK --interval=5s --timeout=5s --retries=30 CMD wget -qO- http://127.0.0.1:8080/ready >/dev/null || exit 1\n")
    run(["docker", "build", "-t", "knowmate-local/goframe-backend:ready", str(target)], capture=False)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        # Provider response bodies and command output may contain secrets.
        print(f"Local deployment failed: {type(exc).__name__}: {exc}" if isinstance(exc, (RuntimeError, ValueError))
              else f"Local deployment failed: {type(exc).__name__}; inspect local configuration", file=sys.stderr)
        raise SystemExit(1)
