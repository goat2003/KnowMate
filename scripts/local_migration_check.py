"""Rehearsal-only migration replay and changed-checksum refusal check."""
import json

from local_server import compose, folder, write


def main():
    output = compose("rehearsal", "run", "--rm", "--no-deps", "-T", "migration-runner").decode()
    if "already applied:" not in output or "applying migration:" in output:
        raise RuntimeError("migration replay unexpectedly applied files")
    script = '''set -eu
mkdir /tmp/changed-migrations
cp /app/shared/sql/migrations/*.sql /tmp/changed-migrations/
for file in /tmp/changed-migrations/*.sql; do
  printf '\\n-- acceptance checksum change\\n' >> "$file"
  break
done
if MIGRATION_DIR=/tmp/changed-migrations sh /app/scripts/run_migrations.sh >/tmp/check-result 2>&1; then
  echo 'ERROR: changed checksum accepted'
  exit 1
fi
grep -q 'migration checksum changed:' /tmp/check-result
echo 'changed checksum rejected'
'''
    result = compose("rehearsal", "run", "--rm", "--no-deps", "-T", "--entrypoint", "sh",
                     "migration-runner", "-s", data=script.encode()).decode()
    if "changed checksum rejected" not in result:
        raise RuntimeError("checksum rejection was not verified")
    report = {"repeat_skips_applied_migrations": True, "changed_checksum_rejected": True}
    write(folder("rehearsal") / "migration-report.json", json.dumps(report, indent=2))
    print(json.dumps(report))


if __name__ == "__main__":
    main()
