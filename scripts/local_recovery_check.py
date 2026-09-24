"""Rehearsal-only interrupted task recovery and retry, using a labelled fixture."""
import json
import time
import uuid

from local_server import compose, folder, request, write


def main():
    run_id = "local-recovery-" + uuid.uuid4().hex[:12]
    sql = ("INSERT INTO task_runs (run_id, task_type, user_id, status, locked_by, input_summary, output_summary, error_message, input_payload_json, partial_result_json) "
           f"VALUES ('{run_id}', 'articles', 'local-acceptance', 'running', 'stopped-test-instance', '[LOCAL ACCEPTANCE] recovery fixture', '', '', '{{}}', '{{}}')")
    shell = 'export MYSQL_PWD="$(cat "$MYSQL_ROOT_PASSWORD_FILE")"\nmysql -uroot knowledge_post_agent -e "' + sql + '"\n'
    compose("rehearsal", "exec", "-T", "mysql", "sh", "-s", data=shell.encode())
    compose("rehearsal", "restart", "goframe-backend")
    for _ in range(40):
        try:
            if request("rehearsal", "/api/ready")[0] == 200:
                break
        except OSError:
            pass
        time.sleep(2)
    status, body = request("rehearsal", "/api/runs/" + run_id)
    task = json.loads(body)["run"]
    if status != 200 or task["status"] != "pending":
        raise RuntimeError("interrupted task did not become retryable")
    status, body = request("rehearsal", f"/api/runs/{run_id}/retry", body={}, method="POST")
    result = json.loads(body)["result"]
    if status != 200 or result["status"] != "completed":
        raise RuntimeError("recovered task retry did not complete")
    report = {"run_id": run_id, "fixture": True, "recovered_to": "pending", "manual_retry": "completed"}
    write(folder("rehearsal") / "recovery-report.json", json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
