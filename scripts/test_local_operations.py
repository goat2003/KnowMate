import importlib.util
import sys
from pathlib import Path

import pytest
from cryptography.exceptions import InvalidTag

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))

from local_backup import decrypt, encrypt  # noqa: E402
from local_server import folder  # noqa: E402


def test_encrypted_backup_roundtrip_and_tamper_detection(tmp_path):
    original, encrypted, restored = [tmp_path / name for name in ["original", "encrypted", "restored"]]
    payload = b"database snapshot\0" * 100000
    original.write_bytes(payload)
    key = bytes(range(32))
    encrypt(original, encrypted, key)
    assert b"database snapshot" not in encrypted.read_bytes()
    decrypt(encrypted, restored, key)
    assert restored.read_bytes() == payload
    data = bytearray(encrypted.read_bytes())
    data[55] ^= 1
    encrypted.write_bytes(data)
    with pytest.raises(InvalidTag):
        decrypt(encrypted, restored, key)


def test_deployment_stage_cannot_escape_state_directory():
    for name in ["../production", "knowledge-post-agent", "mem_pro", "D:/"]:
        with pytest.raises(ValueError):
            folder(name)


def test_backup_refuses_existing_restore(monkeypatch):
    import local_backup
    monkeypatch.setattr(local_backup, "run", lambda *args, **kwargs: b"existing-volume")
    with pytest.raises(RuntimeError, match="refusing to overwrite"):
        local_backup.restore(Path("unused"))
