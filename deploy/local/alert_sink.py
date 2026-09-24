"""Local Alertmanager delivery journal; private Docker network only."""
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/metrics":
            stage = os.environ.get("KNOWMATE_STAGE", "production")
            files = list(Path("/backups").glob(f"{stage}-*.json"))
            latest = max((p.stat().st_mtime for p in files), default=0)
            stat = os.statvfs("/events")
            free = stat.f_bavail / max(stat.f_blocks, 1)
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; version=0.0.4")
            self.end_headers()
            self.wfile.write(f"knowmate_local_backup_last_success_timestamp_seconds {latest}\nknowmate_local_disk_free_ratio {free}\n".encode())
            return
        self.send_response(200 if self.path == "/health" else 404)
        self.end_headers()

    def do_POST(self):
        size = int(self.headers.get("Content-Length", "0"))
        if self.path != "/alerts" or size > 1048576:
            self.send_error(400)
            return
        body = json.loads(self.rfile.read(size))
        event = {"received_at": datetime.now(timezone.utc).isoformat(), "notification": body}
        with Path("/events/alerts.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(event, ensure_ascii=False) + "\n")
        self.send_response(200)
        self.end_headers()


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 8099), Handler).serve_forever()
