# ADR-004 — Модельная цепочка: DeepSeek-flash через провайдеров polza

- **Статус:** принято (зафиксировано по факту `oc models status` 2026-10-14). **Мотивация решения в доках
  не зафиксирована** — исторические следы: бэкапы `openclaw.json.before-deepseek-*`, `before-ksu-*`
  (2026-09-28) в `/srv/openclaw/.openclaw/`.
- **Контекст:** по серверному RUNBOOK дефолтом должна быть Anthropic Sonnet 5 (Haiku 4.5 в резерве,
  подписка до 2027-08-31). Фактически агент переключён на DeepSeek через агрегаторов `polza`/`polza-ds`
  и `polza-ksu`/`polza-ksu-ds` (API-ключи `pza_*` в профиле агента; в git не попадают).
- **Решение:** дефолт — `polza-ds/deepseek/deepseek-v4.1-flash`; фолбэки — `polza-ds/deepseek/deepseek-v4-flash`,
  `polza-ds/deepseek/deepseek-v4-flash-0731`; второй профиль — `polza-ksu-ds/deepseek/deepseek-v4.1-flash`.
  Токен Anthropic остаётся авторизованным, но **в цепочку не входит** (ручной/аварийный сценарий).
  Utility/image-модели не настроены; эмбеддинги — локально (Ollama `bge-m3`).
- **Последствия:** расход идёт по API `polza*`, а не по подписке Anthropic; flash-модели рассчитаны на
  повседневные задачи агента. Откат/смена цепочки — правка профиля `main` в `openclaw.json`
  (`oc models status` для проверки); при деградации polza — включить anthropic в цепочку вручную.

Связи[ADR-004]: relates=ADR-002

---

## Дополнение 2026-10-14 — токен Anthropic удалён

Токен Anthropic (`sk-ant-oat01-…`) признан **недействительным** (auth-профиль `anthropic:manual` уже
был disabled/auth_permanent) и **удалён**:
- auth-профиль `anthropic:manual` снят через `oc models auth logout anthropic:manual --agent main --yes`
  (в агентов `ksu`/`service` профилей не было);
- ключ `CLAUDE_CODE_OAUTH_TOKEN` удалён из `/etc/openclaw/env` (бэкап — `/etc/openclaw/env.bak-20261014`),
  Gateway перезапущен.

Текст ADR выше («токен остаётся авторизованным…») относится к периоду **до 2026-10-14**. Текущее состояние:
авторизация **только** провайдеры `polza*`; при деградации polza резерв через Anthropic потребует
повторной авторизации (`oc models auth login --provider anthropic`).

---

## Дополнение 2026-10-14 — схема ключей polza vs polza-ksu (OPF-7)

Разделение расходов между агентами подтверждено фактами `oc models status`:

- `main`, `service` → профиль **`polza-ds`**: `polza-ds/deepseek/deepseek-v4.1-flash`, фолбэки
  `polza-ds/deepseek/deepseek-v4-flash` и `polza-ds/deepseek/deepseek-v4-flash-0731`;
- `ksu` → отдельный профиль **`polza-ksu-ds`**: те же модели DeepSeek, но **свой API-ключ `pza_*`** —
  расход агента `ksu` учитывается отдельно от общего.

Схема: **один провайдерский профиль = один «кошелёк»** — общий `polza-ds` (main + service) и
персональный `polza-ksu-ds` (ksu). Ключи хранятся в состоянии OpenClaw (auth-store агентов),
в git и в `infra/` не копируются; в `/etc/openclaw/env` переменных polza нет. Каталог моделей
`polza/anthropic/*`, `polza/qwen/*` в `agents.defaults.models` — резервный, в цепочку не входит.
При заведении новых агентов решение «общий или отдельный кошелёк» принимать сразу и отражать здесь.