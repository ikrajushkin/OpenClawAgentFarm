# agents/ — анкеты агентов «Фабрика агентов» (OPF-8)

Источник истины для агентов oc-node1. `openclaw.json` — производный артефакт:
правки конфига делаются ТОЛЬКО через анкету + `oc-agent-factory.py plan` → apply (E2).
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
projects: []             # OPF-9 (этап E5) — в конфиг не рендерится
reports: {}              # OPF-9 (этап E6) — в конфиг не рендерится
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

## Команды

```bash
python3 scripts/oc-agent-factory.py export   --config /srv/openclaw/.openclaw/openclaw.json
python3 scripts/oc-agent-factory.py validate [--check-secrets]
python3 scripts/oc-agent-factory.py plan     [--emit-patch DIR]   # exit 2 = есть diff
# E2+: запись и жизненный цикл (детали — --help)
python3 scripts/oc-agent-factory.py new     --id <id> --stack <s> [--toolset <t>] [--role <r>] \
  [--channel type:account]...   # settings пресета подставляются из _channels.yaml (E3)
python3 scripts/oc-agent-factory.py edit    --id <id> --set path=value | --unset path
python3 scripts/oc-agent-factory.py apply   [--dry-run] [--yes] --id <id>...
python3 scripts/oc-agent-factory.py destroy --id <id> --confirm [--simulate PATH]
```

`export` перегенерирует анкеты из конфига (аннотации stack/role/toolset/notes
сохраняет). `validate` — ошибки (exit 1) и предупреждения (exit 0). `plan` —
сравнение «анкета → конфиг» по управляемым поддеревьям (agents.entries,
bindings-строки агента, channels-аккаунты по scope).

## Статус (E3, 2026-10-20)

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
- [ ] Включение modelPolicy.allow для main/service/ksu — отдельным шагом после миграции
