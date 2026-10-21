#!/bin/bash
# oc-factory-install.sh - install the agent factory (OPF-8, E4) on oc-node1 from a staging dir.
# Usage: bash oc-factory-install.sh /root/oc-factory-deploy
# Server layout after install:
#   /usr/local/lib/oc-factory/oc-agent-factory.py      factory code
#   /usr/local/lib/oc-factory/agents/*.yaml            questionnaires + libraries (git copy)
#   /usr/local/bin/oc-factory                          wrapper (CLI)
#   /usr/local/bin/oc-factory-drift.sh                 drift control script
#   /etc/cron.d/oc-factory                             schedule (4x/day)
#   /etc/zabbix/zabbix_agentd.d/openclaw-factory.conf  key custom.openclaw.factory.drift
# Idempotent. Details: docs/Vosstanovlenie (see repo docs).
set -eu
SRC=${1:-/root/oc-factory-deploy}
install -d /usr/local/lib/oc-factory/agents
install -m 0644 "$SRC/oc-agent-factory.py" /usr/local/lib/oc-factory/oc-agent-factory.py
install -m 0644 "$SRC/agents/"*.yaml /usr/local/lib/oc-factory/agents/
printf '#!/bin/bash\nexec python3 /usr/local/lib/oc-factory/oc-agent-factory.py "$@"\n' \
    > /usr/local/bin/oc-factory
chmod 0755 /usr/local/bin/oc-factory
install -m 0755 "$SRC/oc-factory-drift.sh" /usr/local/bin/oc-factory-drift.sh
install -m 0644 "$SRC/cron-oc-factory" /etc/cron.d/oc-factory
install -m 0644 "$SRC/openclaw-factory.conf" /etc/zabbix/zabbix_agentd.d/openclaw-factory.conf
systemctl reload zabbix-agent 2>/dev/null || systemctl restart zabbix-agent
echo "oc-factory installed; smoke: validate"
python3 /usr/local/lib/oc-factory/oc-agent-factory.py validate \
    --config /srv/openclaw/.openclaw/openclaw.json \
    --agents-dir /usr/local/lib/oc-factory/agents