# Zabbix-сервер: элементы данных и триггеры для oc-node1 (OpenClaw)

> Спецификация для создания на стороне Zabbix-сервера (92.53.116.x) — часть OPF-6.
> Агентская сторона уже развёрнута: ключи активны (`zabbix_agentd -t <ключ>` на oc-node1).
> Сопроводительный док: [`../../docs/Мониторинг-и-алерты.md`](../../docs/Мониторинг-и-алерты.md).

Хост: oc-node1 (45.91.237.204). Тип элемента: Zabbix agent (порт 10050).
Имя хоста в выражениях триггеров ниже — `/oc-node1/`, подставить фактическое имя хоста в Zabbix.

## Элементы данных (Items)

| Ключ (Key) | Тип данных | Интервал | Назначение |
|---|---|---|---|
| `custom.openclaw.gateway.active` | Numeric (unsigned) | 60s | 1 = OpenClaw Gateway работает |
| `custom.openclaw.cron.errors` | Numeric (unsigned) | 5m | число автоматизаций в статусе error |
| `custom.openclaw.cron.jobs` | Numeric (unsigned) | 5m | всего автоматизаций |
| `custom.openclaw.heartbeat.main` | Text | 5m | статус heartbeat main (`ok`/`error`/…) |
| `custom.openclaw.heartbeat.ksu` | Text | 5m | статус heartbeat ksu |
| `custom.openclaw.heartbeat.service` | Text | 5m | статус heartbeat service |
| `custom.openclaw.usage.cost` | Numeric (float) | 10m | расход за день, $ |
| `custom.openclaw.usage.tokens` | Numeric (unsigned) | 10m | токенов за день |
| `custom.openclaw.usage.input` | Numeric (unsigned) | 10m | input-токены |
| `custom.openclaw.usage.output` | Numeric (unsigned) | 10m | output-токены |
| `custom.openclaw.usage.cache_read` | Numeric (unsigned) | 10m | cache read-токены |
| `custom.openclaw.backup.status` | Text | 1h | статус последнего бэкапа (`ok`/`error`) |
| `custom.openclaw.backup.age_hours` | Numeric (unsigned) | 1h | часов с последнего успешного бэкапа |
| `custom.openclaw.backup.sizeMb` | Numeric (unsigned) | 1h | размер последнего бэкапа, MB |
| `custom.openclaw.restore.status` | Text | 1h | статус последней restore-дрели (`ok`/`error`) |

## Триггеры (Triggers)

| Название | Выражение | Серьёзность |
|---|---|---|
| OpenClaw Gateway down | `last(/oc-node1/custom.openclaw.gateway.active)=0` | High |
| Автоматизация в ошибке | `last(/oc-node1/custom.openclaw.cron.errors)>0` | Warning |
| Heartbeat main в ошибке | `find(/oc-node1/custom.openclaw.heartbeat.main,5m,"like","error")=1` | Warning |
| Heartbeat ksu в ошибке | `find(/oc-node1/custom.openclaw.heartbeat.ksu,5m,"like","error")=1` | Warning |
| Heartbeat service в ошибке | `find(/oc-node1/custom.openclaw.heartbeat.service,5m,"like","error")=1` | Warning |
| Дневной расход > 50 $ | `last(/oc-node1/custom.openclaw.usage.cost)>50` | Information |
| Бэкап устарел | `last(/oc-node1/custom.openclaw.backup.age_hours)>30` | High |
| Бэкап завершился с ошибкой | `last(/oc-node1/custom.openclaw.backup.status)<>"ok"` | High |
| Restore-дрель не прошла | `last(/oc-node1/custom.openclaw.restore.status)<>"ok"` | Warning |

## Примечания

- метрики обновляются cron-скриптами каждые 10 минут: интервалы опроса < 5m имеют смысл только для
  `gateway.active` (live-проверка);
- `health.json` пишет `-1` в `cronJobs`/`cronErrors`, если `oc cron list` недоступен (Gateway лежит) —
  это отдельный сигнал от триггера Gateway down;
- полезно добавить графики `usage.cost` / `usage.tokens` (динамика расхода по дням);
- предупреждения о падении cron-задач дублируются в самой платформе (`failureAlert` у задач),
  триггер Zabbix — внешний контроль.