"""Destructive-to-service-availability tests: restricted to knowmate-rehearsal."""
import json
import time

from local_server import compose, folder, request, verify, write


def wait_ready():
    for _ in range(40):
        try:
            status, _ = request("rehearsal", "/api/ready")
            if status == 200:
                return
        except OSError:
            pass
        time.sleep(3)
    raise RuntimeError("service did not recover")


def main():
    evidence = {}
    for service in ["python-agent", "mysql"]:
        print(f"Stopping rehearsal {service}", flush=True)
        try:
            compose("rehearsal", "stop", "-t", "20", service)
            status, _ = request("rehearsal", "/api/ready")
            if status != 503:
                raise RuntimeError(f"{service} failure did not fail readiness: {status}")
            evidence[service + "_readiness"] = status
        finally:
            compose("rehearsal", "start", service)
        wait_ready()
        evidence[service + "_recovered"] = True
        print(f"Recovered rehearsal {service}", flush=True)
    journal = folder("rehearsal") / "events/alerts.jsonl"
    before = journal.stat().st_size if journal.exists() else 0
    try:
        compose("rehearsal", "stop", "fetch-mcp")
        deadline = time.monotonic() + 220
        while time.monotonic() < deadline:
            if journal.exists():
                with journal.open(encoding="utf-8") as stream:
                    stream.seek(before)
                    notifications = [json.loads(line) for line in stream if line.strip()]
                alerts = [a for n in notifications for a in n["notification"].get("alerts", [])]
                if any(a["labels"].get("alertname") == "KnowMateServiceDown" and
                       "fetch-mcp" in a["labels"].get("instance", "") for a in alerts):
                    evidence["real_service_down_alert_delivered"] = True
                    break
            print("Waiting for real Prometheus ServiceDown -> Alertmanager -> local journal", flush=True)
            time.sleep(10)
        else:
            raise RuntimeError("no service-down notification received")
    finally:
        compose("rehearsal", "start", "fetch-mcp")
    time.sleep(20)
    verify("rehearsal")
    write(folder("rehearsal") / "drill-report.json", json.dumps(evidence, indent=2))
    print(json.dumps(evidence, indent=2))


if __name__ == "__main__":
    main()
