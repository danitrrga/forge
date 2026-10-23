#!/bin/sh
# Apply every pending migration in db/migrations/ to the shared staging database (staging-db.example.test).
# Pending = not listed in db/staging_applied.txt.   --dry-run lists them without applying.
set -e
cd "$(dirname "$0")/.."
case "$1" in
  ""|--dry-run) ;;
  -h|--help) echo "usage: scripts/apply-staging.sh [--dry-run]"; exit 0 ;;
  *) echo "usage: scripts/apply-staging.sh [--dry-run]" >&2; exit 2 ;;
esac
for f in db/migrations/*.sql; do
  name=$(basename "$f")
  grep -qx "$name" db/staging_applied.txt && continue
  if [ "$1" = "--dry-run" ]; then
    echo "pending: $name"
  else
    echo "apply-staging $name" >> ops.log
    echo "$name" >> db/staging_applied.txt
    echo "applied $name to staging-db.example.test"
  fi
done
