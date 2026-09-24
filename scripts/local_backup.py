"""Encrypted cold snapshots and restore drills for the isolated local stack.

Backup briefly stops the named local stack. Restore only creates knowmate-restore
and refuses existing restore volumes. Never overwrites a live database.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import secrets
import shutil
import subprocess
import tarfile
import tempfile
import time

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
import yaml

from local_server import STATE, ROOT, INFRA, compose, folder, run, write


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def encrypt(source, target, key):
    nonce = secrets.token_bytes(12)
    engine = Cipher(algorithms.AES(key), modes.GCM(nonce)).encryptor()
    with source.open("rb") as reader, target.open("wb") as writer:
        writer.write(b"KM01" + nonce)
        while chunk := reader.read(1024 * 1024):
            writer.write(engine.update(chunk))
        writer.write(engine.finalize())
        writer.write(engine.tag)


def decrypt(source, target, key):
    with source.open("rb") as reader, target.open("wb") as writer:
        if reader.read(4) != b"KM01":
            raise ValueError("not a KnowMate backup")
        nonce = reader.read(12)
        reader.seek(-16, 2)
        tag = reader.read(16)
        remaining = source.stat().st_size - 32
        reader.seek(16)
        engine = Cipher(algorithms.AES(key), modes.GCM(nonce, tag)).decryptor()
        while remaining:
            chunk = reader.read(min(1024 * 1024, remaining))
            if not chunk:
                raise ValueError("truncated backup")
            writer.write(engine.update(chunk))
            remaining -= len(chunk)
        writer.write(engine.finalize())


def backup(stage):
    state = folder(stage)
    keyfile = STATE / "backup.key"
    if not keyfile.exists():
        keyfile.write_bytes(secrets.token_bytes(32))
    key = keyfile.read_bytes()
    running = compose(stage, "ps", "--status", "running", "--services").decode().split()
    if not running:
        raise RuntimeError("source stack must be running before backup")
    volumes = run(["docker", "volume", "ls", "--filter", f"label=com.docker.compose.project=knowmate-{stage}",
                   "--format", "{{.Name}}"]).decode().split()
    expected = set(yaml.safe_load((state / "compose.yaml").read_text())["volumes"])
    if not volumes or any(v.removeprefix(f"knowmate-{stage}_") not in expected for v in volumes):
        raise RuntimeError("unexpected or missing source volumes")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target = STATE / "backups" / f"{stage}-{stamp}.kmbackup"
    target.parent.mkdir(exist_ok=True)
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="backup-work-", dir=STATE) as temp:
        work = Path(temp)
        shutil.copytree(state, work / "config", ignore=shutil.ignore_patterns("events"))
        manifest = {"stage": stage, "created_at": stamp, "state_dir": state.as_posix(), "volumes": {}}
        print(f"Stopping isolated {stage} stack for consistent snapshot", flush=True)
        try:
            compose(stage, "stop", "-t", "60")
            for volume in volumes:
                logical = volume.removeprefix(f"knowmate-{stage}_")
                path = work / f"{logical}.tgz"
                with path.open("wb") as stream:
                    result = subprocess.run(["docker", "run", "--rm", "-v", f"{volume}:/source:ro",
                        "python:3.12-slim", "tar", "-czf", "-", "-C", "/source", "."],
                        stdout=stream, stderr=subprocess.PIPE, timeout=600)
                if result.returncode:
                    raise RuntimeError(f"snapshot failed for {logical}")
                manifest["volumes"][logical] = digest(path)
                print(f"Snapshot verified: {logical}", flush=True)
        finally:
            compose(stage, "start", *running)
        write(work / "manifest.json", json.dumps(manifest, indent=2))
        archive = work / "payload.tar"
        with tarfile.open(archive, "w") as bundle:
            bundle.add(work / "manifest.json", arcname="manifest.json")
            bundle.add(work / "config", arcname="config")
            for logical in manifest["volumes"]:
                bundle.add(work / f"{logical}.tgz", arcname=f"{logical}.tgz")
        pending = target.with_suffix(".partial")
        encrypt(archive, pending, key)
        pending.replace(target)
    report = {"backup": str(target), "sha256": digest(target), "seconds": round(time.monotonic() - started, 2),
              "volume_count": len(volumes), "encrypted": "AES-256-GCM"}
    write(target.with_suffix(".json"), json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))
    return target


def restore(archive):
    state = folder("restore")
    existing = run(["docker", "volume", "ls", "--filter", "label=com.docker.compose.project=knowmate-restore", "--format", "{{.Name}}"])
    if existing.strip() or state.exists():
        raise RuntimeError("restore target already exists; refusing to overwrite it")
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="restore-work-", dir=STATE) as temp:
        work = Path(temp)
        plain = work / "payload.tar"
        decrypt(archive, plain, (STATE / "backup.key").read_bytes())
        with tarfile.open(plain) as bundle:
            bundle.extractall(work, filter="data")
        manifest = json.loads((work / "manifest.json").read_text())
        source_spec = yaml.safe_load((work / "config/compose.yaml").read_text())
        for logical, checksum in manifest["volumes"].items():
            if logical not in source_spec["volumes"] or digest(work / f"{logical}.tgz") != checksum:
                raise RuntimeError("backup manifest checksum or volume mismatch")
        shutil.copytree(work / "config", state)
        spec_text = (state / "compose.yaml").read_text().replace(manifest["state_dir"], state.as_posix())
        spec = yaml.safe_load(spec_text)
        for service in spec["services"].values():
            service.pop("ports", None)
        write(state / "compose.yaml", yaml.safe_dump(spec, sort_keys=False))
        for logical in manifest["volumes"]:
            target_volume = f"knowmate-restore_{logical}"
            run(["docker", "volume", "create", "--label", "com.docker.compose.project=knowmate-restore",
                 "--label", f"com.docker.compose.volume={logical}", target_volume])
            run(["docker", "run", "--rm", "-v", f"{target_volume}:/target", "-v", f"{work.as_posix()}:/backup:ro",
                 "python:3.12-slim", "tar", "-xzf", f"/backup/{logical}.tgz", "-C", "/target"])
        compose("restore", "up", "-d", "--wait", "--wait-timeout", "240", *INFRA, capture=False)
    report = {"source": str(archive), "target": "knowmate-restore", "volume_count": len(manifest["volumes"]),
              "seconds": round(time.monotonic() - started, 2), "infra_health": "passed"}
    write(state / "restore-report.json", json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["backup", "restore"])
    parser.add_argument("--stage", choices=["production", "rehearsal"], default="production")
    parser.add_argument("--archive", type=Path)
    args = parser.parse_args()
    if args.action == "backup":
        backup(args.stage)
    elif args.archive:
        restore(args.archive.resolve())
    else:
        parser.error("restore requires --archive")


if __name__ == "__main__":
    main()
