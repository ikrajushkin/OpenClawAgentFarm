# agents/ — анкеты агентов «Фабрика агентов» (OPF-8)

Источник истины для агентов oc-node1. `openclaw.json` — производный артефакт:
правки конфига делаются ТОЛЬКО через анкету + `oc-agent-factory.py plan` → apply (E2);
ручные правки конфига запрещены (E4 — drift-контроль `export --check` их ловит).
Каталог и инструмент — план [План-фабрика-агентов.md](../docs/План-фабрика-агентов.md).

## Файлы

| Файл | Назначение |
|---|---|
| `<id>.yaml` | анкета агента `id` (main, service, ksu) |
| `_stacks.yaml` | стеки моделей (model/models/modelPolicy.allow) |
| `_toolsets.yaml` | наборы инструментов (tools.*) |
| `_roles.yaml` | роли субагентов («специфические задачи») |
| `_channels.yaml` | пресеты каналов; ключ — тип канала или id плагина (kind: plugin), scope=account\|channel |

Библиотеки `_*.yaml` — для СОЗДАНИЯ агентов: factory берёт из них значения,
после чего агент правится только в своей анкете (библиотеки не перетирают анкеты).

## Формат анкеты

```yaml
apiVersion: oc-farm/v1
kind: Agent
id: ksu                  # == имени файла; name записи агента в конфиге := id
origin: migrated         # migrated (принят export-ом) | factory (создан new-ом)
stack: ksu-ds            # аннотация → _stacks.yaml (поля model — verbatim в анкете)
toolset: minimal-messaging  # аннотация → _toolsets.yaml
role: doc-writer         # аннотация → _roles.yaml
channels:                # route-строки bindings + settings каналов
  - type: telegram       # тип канала → _channels.yaml (scope)
    account: ksu         # accountId из bindings.match
    preset: telegram-bot # аннотация пресета (settingsTemplate подставляет new)
    settings: {...}      # verbatim: channels.telegram.accounts.ksu
agent: {...}             # НЕТ: всё плоско (см. ниже)
# --- verbatim-зеркало agents.entries.ksu (name не пишется: := id) ---
workspace: /srv/shared/Projects/Ksu
agentDir: /srv/openclaw/.openclaw/agents/ksu/agent
identity: {name: Помощник, emoji: "💬"}
model: {primary: polza-ksu-ds/..., fallbacks: [...]}
models: {...}
tools: {...}
subagents: {...}
thinkingDefault: max
modelPolicy: {allow: [...]}   # жёсткий allowlist; для новых агентов обязателен
notes: "свободные заметки — в конфиг не попадают"
projects:                # OPF-9 (E5): реестр проектов → workspace-слой (см. ниже)
  - { id: dom, title: "Домашние дела", dir: Dom, description: "...", budgetUsdPerDay: 5 }
reports:                  # OPF-9 (E6): настройка дайджеста проектов (в конфиг не рендерится)
  digest:                 # automation factory-digest-<id> -> канал владельца
    schedule: "0 9 * * *"   # cron (5/6 полей)
    tz: Europe/Moscow       # IANA (необязательно)
    channel: telegram       # канал доставки
    account: service        # аккаунт канала (multi-account)
    to: '10292232'          # chatId/номер владельца
    days: 1                 # период дайджеста (дни)
    enabled: true           # false — автоматизация выключена
```

Правила:

1. **Все ключи, кроме мета** (`apiVersion, kind, id, origin, stack, role, toolset,
   channels, notes, projects, reports`), рендерятся в `agents.entries.<id>`
   **verbatim** — анкета зеркалит запись агента один в один. Критерий приёма миграции:
   `plan` после `export` → «0 изменений» по всем агентам.
2. **Секреты запрещены**: только ссылки — `tokenFile: /srv/openclaw/secrets/...` (путь),
   `*File`-пути каналов, `${ENV}` (= SecretRef `env:default:VAR`, резолвится при записи
   и dry-run). Значения токенов/ключей в git не попадают никогда (грабли §1.4).
3. **modelPolicy.allow** — жёсткий allowlist (решение 2026-10-14). Для новых
   агентов обязателен (validate — ошибка); для `origin: migrated` — предупреждение:
   включение allowlist делается отдельным согласованным шагом после миграции,
   чтобы не менять поведение текущих пользователей.
4. Правки руками → `validate` → `plan` (посмотреть diff) → `apply` (E2, с бэкапом).
   Ручные правки `openclaw.json` запрещены (E4): drift-контроль фиксирует расхождение
   «конфиг ≠ анкеты» и правки мимо фабрики.

## Команды

```bash
python3 scripts/oc-agent-factory.py export   --config /srv/openclaw/.openclaw/openclaw.json [--check]
python3 scripts/oc-agent-factory.py validate [--check-secrets]
python3 scripts/oc-agent-factory.py plan     [--emit-patch DIR]   # exit 2 = есть diff
# E2+: запись и жизненный цикл (детали — --help)
python3 scripts/oc-agent-factory.py new     --id <id> --stack <s> [--toolset <t>] [--role <r>] \
  [--channel type:account]...   # settings пресета подставляются из _channels.yaml (E3)
python3 scripts/oc-agent-factory.py edit    --id <id> --set path=value | --unset path
python3 scripts/oc-agent-factory.py apply   [--dry-run] [--yes] --id <id>...
python3 scripts/oc-agent-factory.py destroy --id <id> --confirm [--simulate PATH]
```

`export` перегенерирует анкеты из конфига (аннотации stack/role/toolset/notes/preset
сохраняет); `export --check` — сверка без записи (drift-контроль E4: exit 0 = нет дрейфа,
exit 2 = дрейф). `validate` — ошибки (exit 1) и предупреждения (exit 0). `plan` —
сравнение «анкета → конфиг» по управляемым поддеревьям (agents.entries,
bindings-строки агента, channels-аккаунты по scope).

## Мультипроектность (E5, OPF-9): `projects` и `/проект`

Анкетный `projects` — реестр проектов агента (в `openclaw.json` не рендерится):
`{id, title, dir, description?, budgetUsdPerDay?}`; `id` — slug `[a-z0-9-]`,
`dir` — один сегмент `[A-Za-z0-9._-]` **относительно workspace агента**
(validate ловит `..`, абсолютные пути и подкаталоги). `plan`/`apply` материализуют
workspace-слой (идемпотентно, `openclaw.json` не трогается):

- `projects.yaml` — машиночитаемый реестр (managed, из анкеты);
- `PROJECTS.md` — навигация (managed);
- блок «Проекты» в `AGENTS.md` между `<!-- oc-factory:projects:start/end -->`
  (bootstrap Project Context — виден агенту в каждом ходе; бэкап перед правкой);
- `skills/проект/SKILL.md` — навык; имя навыка = slash-команда чата
  `/проект <id>`, `/проект список`, `/проект статус`;
- `<dir>/{PROJECT.md, docs/, data/, memory/, logs/}` — дерево проекта
  (`PROJECT.md` только создаётся, существующее не перезаписывается);
- `.active-project` — активный проект (создаёт factory = первый проект анкеты;
  дальше пишет только навык `/проект`).

Семантика — [ADR-006](../docs/ADR/ADR-006-Мультипроектность.md): активный проект
один на агента (per-агент), гидратация — `PROJECT.md` активного проекта, состояние
в `.active-project` переживает сессии (зеркало — строка «Активный проект» в блоке).
После правки `SKILL.md` — `systemctl restart openclaw-gateway` (инвентарь навыков
кэшируется; вотчер снапшот не обновляет — грабли §1.6). Пилот — `service`
(e2e проверен 2026-10-21); `main`/`ksu` не трогать.

## Дайджесты и фоновая работа (E6, OPF-9/T8)

- **`reports.digest`** в анкете — конфигурация cron-дайджеста проектов (в конфиг не
  рендерится); синхронизация automation — `scripts/oc-reports.py`:

  ```bash
  sudo -u openclaw env HOME=/srv/openclaw python3 /usr/local/lib/oc-factory/oc-reports.py \
      --agents-dir /usr/local/lib/oc-factory/agents --diff      # что изменится
  # применить: --apply ; удалить лишние factory-digest-*: --apply --prune
  ```

  Automation `factory-digest-<id>` — **command job** (stdout скрипта → `--announce` в канал
  владельца, без агентского хода, 0 токенов); declaration-key `factory:<id>:digest`.
- **Сборщик** — `scripts/oc-project-digest.py` (лежит на сервере рядом с factory):
  разделы «результаты / проблемы / фоновые задачи / ресурсы / бюджеты»; журналы проектов
  `<dir>/logs/*.md` читаются по маркерам `RESULT:`/`PROBLEM:`; задачи — по тегу `proj-<id>`;
  ресурсы — `openclaw gateway usage-cost`; бюджеты `budgetUsdPerDay` (soft) сверяются
  с расходом дня. Ручной прогон:
  `python3 oc-project-digest.py --workspace <ws> --days 1 [--save]`.
- **Навык `фон`** (`/фон задача|список|дайджест`) — фоновые задачи проектов: durable
  `openclaw automations` с тегом `proj-<id>` в имени задачи + журналы `RESULT:`/`PROBLEM:`;
  правила продублированы блоком «Фоновая работа и дайджесты» в `AGENTS.md`.
  Пилот — `service` (дайджест доставляется владельцу в telegram).

## Деплой и drift-контроль (E4, 2026-10-21)

Factory на oc-node1 живёт постоянно: `/usr/local/lib/oc-factory/` (код + анкеты, зеркало git),
обёртка `/usr/local/bin/oc-factory`. Заливка с рабочей станции — один шаг:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/oc-factory-deploy.ps1
```

Скрипт нормализует `.sh` в LF (грабля CRLF), устанавливает factory + drift-контроль
(`infra/factory/oc-factory-install.sh`) и прогоняет `validate` + `export --check`
(дрейф должен быть 0). Состав установки —
[docs/Восстановление-и-развёртывание.md](../docs/Восстановление-и-развёртывание.md).

**Drift-контроль**: cron `/etc/cron.d/oc-factory` (4×/сутки) запускает
`/usr/local/bin/oc-factory-drift.sh` → `export --check` → `/var/log/oc-factory-drift.log`
+ метрика `custom.openclaw.factory.drift` (`ok`/`drift`/`error`) для Zabbix. Что ловит:

- ручную правку `openclaw.json` мимо фабрики (hot-fix → дрейф «конфиг ≠ анкеты»);
- анкету без записи в `agents.entries` (создан/удалён мимо фабрики или не применена).

Расхождение = сигнал разобраться: правка мимо фабрики → перенести в анкету (сверить `export`)
или откатить; неприменённая анкета → `plan` → `apply`. Ошибка проверки (`error`) —
смотреть `/var/log/oc-factory-drift.log`.

## Статус (E4, 2026-10-21)

- [x] export/validate/plan реализованы и проверены на снимке конфига: plan = 0 изменений
      для main/service/ksu (снимок вне репо, секретов в конфиге нет — только
      `${POLZA_API_KEY}` из env и tokenFile-пути)
- [x] apply/new/edit/destroy (E2) — приёмка 2026-10-20 на тестовом агенте `fab-test`
      (канал не подключали): new → validate → plan → apply --dry-run → apply --yes →
      destroy --confirm; после каждого destroy конфиг семантически идентичен снимку
      «до фабрики» (сверка скриптом), main/service/ksu не тронуты; создание — <2 мин.
      Грабли этапа (per-entry `subagents`, roster-guard `oc config patch`, обход
      gateway при destroy) — план §8 «Итоги E2».
- [x] Библиотеки каналов (E3, 2026-10-20): `_channels.yaml` — пресеты `telegram-bot`, `max-bot`,
      `nc-talk` (settingsTemplate применяется `new --channel type:account`), `mail-imap`/`webhook-in`
      (kind: plugin — подключение вручную, ноты в `_channels.yaml`); шаблоны проверены
      `oc config patch --dry-run`; `validate` ловит неизвестные типы каналов и сверяет pluginId
      с `plugins.allow`. T2/T3/T4 закрыты на уровне пресетов.
- [x] E4 (2026-10-21): миграция main/service/ksu на анкеты закрыта (diff=0: `export --check`
      = 0 дрейфов, `plan` = 0 на живом конфиге); drift-контроль — `export --check` + cron
      `/etc/cron.d/oc-factory` (4×/сутки) + метрика `custom.openclaw.factory.drift`;
      постоянный деплой `/usr/local/lib/oc-factory/` (заливка `scripts/oc-factory-deploy.ps1`),
      `/root/oc-factory-e2/` удалён. T5/T6 закрыты: правки агентов — только анкета →
      `plan` → `apply`, ручные правки конфига запрещены.
- [ ] Включение modelPolicy.allow для main/service/ksu — отдельным согласованным шагом
- [x] E5 (2026-10-21): мультипроектность OPF-9 — ADR-006, `projects` в анкете +
      workspace-слой `plan`/`apply` (projects.yaml, PROJECTS.md, блок AGENTS.md,
      навык `/проект`, деревья проектов, `.active-project`), пилот на `service`
      (digitalization-uk / wifi-public-business / brand-stopzatop) — e2e
      `/проект список|<id>` проверен; `openclaw.json` не менялся (md5 тот же).
- [x] E6 (2026-10-21): фоновая работа + дайджесты + бюджеты (T8) — `oc-project-digest.py`
      + automation command job `factory-digest-<id>` (delivery владельцу, 0 токенов),
      синхронизация из `reports.digest` (`oc-reports.py`), навык `/фон` (durable-задачи
      `proj-<id>` + журналы `RESULT:`/`PROBLEM:`), бюджеты `budgetUsdPerDay` (soft);
      пилот `service` — дайджест доставлен владельцу, `plan`=0, `export --check`=0.
- [ ] E7: док-апдейты, сверка managed-файлов workspace в drift-контроле (OPF-9)
