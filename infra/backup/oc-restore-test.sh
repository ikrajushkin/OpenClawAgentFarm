#!/bin/bash
# oc-restore-test.sh - periodic restore drill for oc-node1 backups (OPF-4).
# Server path: /usr/local/bin/oc-restore-test.sh (repo copy: infra/backup/oc-restore-test.sh).
# Validates the newest /srv/openclaw/backups/auto/<stamp>/:
#   1) sha256 manifest, 2) tar.zst integrity + entry counts,
#   3) real pg_restore of both dumps into throwaway postgres containers.
# Writes /var/lib/openclaw-metrics/restore-test.json for Zabbix (custom.openclaw.restore.*).
set -uo pipefail

BACKUP_ROOT=/srv/openclaw/backups/auto
METRICS=/var/lib/openclaw-metrics/restore-test.json
LOG=/var/log/oc-restore-test.log
FAILED=0

log() { echo "$(date -Is) $*" | tee -a "$LOG"; }

DEST=$(ls -1dt "$BACKUP_ROOT"/*/ 2>/dev/null | head -1)
if [ -z "$DEST" ]; then
  log "FAIL no backups under $BACKUP_ROOT"
  mkdir -p "$(dirname "$METRICS")"
  jq -n '{status:"nobackup", stamp:"", lastRunEpoch:(now|floor)}' > "$METRICS"
  exit 1
fi
STAMP=$(basename "$DEST")
log "=== restore-test start for $STAMP ==="

# 1) manifest
if (cd "$DEST" && sha256sum -c SHA256SUMS >>"$LOG" 2>&1); then
  log "OK   sha256 manifest"
else
  log "FAIL sha256 manifest"
  FAILED=1
fi

# 2) archives readable + entry counts
for f in "$DEST"/*.tar.zst; do
  n=$(tar -I zstd -tf "$f" 2>>"$LOG" | wc -l)
  if [ "$n" -gt 0 ]; then
    log "OK   tar $f entries=$n"
  else
    log "FAIL tar $f"
    FAILED=1
  fi
done

# 3) real pg_restore into throwaway containers
restore_db() {
  local image=$1 user=$2 db=$3 dump="$DEST/$4" pre_sql=${5:-} cname=oc-restore-test-$$
  docker rm -f "$cname" >/dev/null 2>&1
  if ! docker run -d --name "$cname" -e POSTGRES_USER="$user" -e POSTGRES_PASSWORD=restore-test \
       -e POSTGRES_DB="$db" "$image" >/dev/null 2>&1; then
    log "FAIL docker run $image"
    FAILED=1; return
  fi
  local ok=0
  for _ in $(seq 1 30); do
    docker exec "$cname" pg_isready -U "$user" -d "$db" >/dev/null 2>&1 && { ok=1; break; }
    sleep 2
  done
  # roles referenced by GRANTs in the dump must exist in the fresh cluster (e.g. oc_admin in nextcloud-db)
  if [ -n "$pre_sql" ]; then
    docker exec "$cname" psql -U "$user" -d "$db" -c "$pre_sql" >>"$LOG" 2>&1
  fi
  if [ "$ok" = 1 ] && docker exec -i "$cname" pg_restore -U "$user" -d "$db" --no-owner < "$dump" >>"$LOG" 2>&1; then
    local tbl
    tbl=$(docker exec "$cname" psql -U "$user" -d "$db" -tAc "select count(*) from information_schema.tables where table_schema='public'")
    log "OK   pg_restore $db tables=$tbl"
  else
    log "FAIL pg_restore $db"
    FAILED=1
  fi
  docker rm -f "$cname" >/dev/null 2>&1
}
restore_db postgres:17-alpine nextcloud nextcloud nextcloud-db.dump 'CREATE ROLE oc_admin'
restore_db postgres:16-alpine basip basip basip-db.dump

if [ "$FAILED" -eq 0 ]; then STATUS=ok; else STATUS=error; fi
mkdir -p "$(dirname "$METRICS")"
jq -n --arg stamp "$STAMP" --arg status "$STATUS" \
      '{stamp:$stamp, status:$status, lastRunEpoch:(now|floor)}' > "$METRICS"
chmod 644 "$METRICS"
log "=== restore-test end status=$STATUS ==="
[ "$FAILED" -eq 0 ]