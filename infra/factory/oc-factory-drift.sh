#!/bin/bash
# oc-factory-drift.sh - drift control "config != questionnaires" for the agent factory (OPF-8, E4).
# Server path: /usr/local/bin/oc-factory-drift.sh (repo copy: infra/factory/oc-factory-drift.sh).
# Cron: /etc/cron.d/oc-factory (4x/day). Metrics: /var/lib/openclaw-metrics/factory-drift.json
# -> zabbix key custom.openclaw.factory.drift (infra/zabbix/openclaw-factory.conf).
# Detects manual edits of openclaw.json bypassing the factory (and unapplied questionnaires).
set -u
FACTORY=${OC_FACTORY_HOME:-/usr/local/lib/oc-factory}
CONFIG=${OC_FACTORY_CONFIG:-/srv/openclaw/.openclaw/openclaw.json}
METRICS=${OC_FACTORY_METRICS:-/var/lib/openclaw-metrics/factory-drift.json}
LOG=${OC_FACTORY_LOG:-/var/log/oc-factory-drift.log}
STAMP=$(date -u +%Y-%m-%dT%H:%M:%SZ)

OUT=$(python3 "$FACTORY/oc-agent-factory.py" export --check \
        --config "$CONFIG" --agents-dir "$FACTORY/agents" 2>&1)
RC=$?
case $RC in
  0) STATUS=ok ;;
  2) STATUS=drift ;;
  *) STATUS=error ;;
esac

printf '{"status":"%s","rc":%d,"ts":"%s"}\n' "$STATUS" "$RC" "$STAMP" \
    > "$METRICS.tmp" && mv "$METRICS.tmp" "$METRICS"
{
  echo "=== $STAMP rc=$RC status=$STATUS"
  echo "$OUT"
} >> "$LOG"
if [ -f "$LOG" ] && [ "$(wc -c < "$LOG")" -gt 1000000 ]; then
  tail -n 500 "$LOG" > "$LOG.tmp" && mv "$LOG.tmp" "$LOG"
fi
if [ "$STATUS" != "ok" ]; then
  echo "oc-factory-drift: $STATUS (rc=$RC) - details in $LOG" >&2
fi
exit $RC