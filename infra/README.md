# infra/ — выгрузка конфигураций oc-node1

Побайтовая выгрузка non-secret-конфигов с сервера **45.91.237.204** от **2026-10-14** (секреты заменены
на `***MASKED***`). Назначение и порядок применения — [`../docs/Восстановление-и-развёртывание.md`](../docs/Восстановление-и-развёртывание.md).

Правила:
- **Секреты сюда не копировать** (токены, пароли, ключи) — только маски и ссылки на места хранения.
- При изменении конфига на сервере — перегружать файл сюда и обновлять дату сверки в доках (OPF-4).
- Файлы `*.example` — шаблоны: реальные значения подставляются при развёртывании.

Эксплуатационные артефакты (добавлено 2026-10-14):
- `openclaw/usage-refresh.sh` — cron-сбор usage-метрик в `/var/lib/openclaw-metrics/usage.json`
  (на сервере: `/usr/local/bin/openclaw-usage-refresh.sh`, вызов от root через `runuser -u openclaw`);
- `zabbix/openclaw-usage.conf` — UserParameter `custom.openclaw.usage.{cost,tokens,input,output,cache_read}`
  (на сервере: `/etc/zabbix/zabbix_agentd.d/openclaw.conf`);
- `cron/openclaw-metrics` — `/etc/cron.d/openclaw-metrics`, запуск refresh каждые 10 минут.