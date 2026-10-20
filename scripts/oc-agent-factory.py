#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""oc-agent-factory — «Фабрика агентов» OpenClaw (OPF-8).

Анкеты agents/*.yaml (git — источник истины) ↔ openclaw.json (производный артефакт).

Команды:
  export   — openclaw.json → agents/<id>.yaml (verbatim-зеркало управляемых фрагментов)
  validate — проверка анкет и библиотек agents/_*.yaml
  plan     — diff «анкета → конфиг» по управляемым поддеревьям; exit 2, если есть изменения
  new      — анкета нового агента из библиотек (stack → model/models/modelPolicy.allow,
             toolset → tools, role → subagents, --channel type:account → settings
             из пресета agents/_channels.yaml); origin: factory
  edit     — точечные правки анкеты (--set path=value / --unset path)
  apply    — validate → план → бэкап конфига → oc config patch --dry-run → запись
             → каркас каталогов новых агентов → контрольный plan (0 изменений)
  destroy  — удаление агента: запись уходит через `oc agents delete --force`
             (единственное «явное удаление» ростера, грабли 2026-10-20), оставшиеся
             route-строки — `oc config patch --replace-path bindings`; workspace и
             agentDir ПЕРЕМЕЩАЮТСЯ в снимок (данные не теряются); обязателен --confirm

Принципы (решения 2026-10-14):
  * миграция минимально-инвазивна: export обязан давать plan «0 изменений» по всем агентам;
  * правки конфига — только через анкету + plan перед apply (бэкап конфига обязателен);
    запись делается ТОЛЬКО `oc config patch` (одна валидируемая запись, грабли §1.3);
  * секреты — только tokenFile/secretRef; значения в git не попадают;
  * модельные права — жёсткий allowlist (modelPolicy.allow) для новых агентов;
    мигрируемые агенты остаются как есть (предупреждение validate), включение
    allowlist — отдельным согласованным шагом после миграции.

Управляемые поддеревья (рендер + дифф):
  agents.entries.<id>            — всё кроме name (name := id): workspace, agentDir,
                                   identity, model, models, tools, subagents,
                                   thinkingDefault, modelPolicy, ...
  bindings                       — route-строки агента (type/agentId/match)
  channels.<type>[.accounts.<a>] — по scope из agents/_channels.yaml (account|channel)

Немета-ключи анкеты рендерятся verbatim: анкета — зеркало записи агента + аннотации
(stack/role/toolset/notes/projects/reports) в конфиг не попадают.

Зависимости: PyYAML (проверено: oc-node1 — 6.0.3, рабочая станция — 6.0.3).
Запуск: python3 oc-agent-factory.py new|edit|export|validate|plan|apply|destroy
        [--config PATH] [--agents-dir PATH] [--id ID] [--check-secrets]
        [--emit-patch DIR] [--dry-run] [--simulate PATH] [--confirm]
        [--oc-cmd CMD] [--backup-dir DIR]
"""

import argparse
import copy
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time

try:
    import yaml
except ImportError:  # pragma: no cover
    sys.exit("ТРЕБУЕТСЯ PyYAML (python3-yaml / pip install pyyaml); проверено: 6.0.3")

if hasattr(sys.stdout, "reconfigure"):  # cp1252-консоль не роняет вывод (грабли Windows)
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

API_VERSION = "oc-farm/v1"
KIND = "Agent"

# Порядок рендера управляемых ключей записи агента (name не входит: задаётся как id).
AGENT_KEY_ORDER = [
    "workspace", "agentDir", "identity", "model", "models",
    "tools", "subagents", "thinkingDefault", "modelPolicy", "heartbeat",
]

# Мета-ключи анкеты: в конфиг не рендерятся.
META_KEYS = {
    "apiVersion", "kind", "id", "origin", "stack", "role", "toolset",
    "channels", "notes", "projects", "reports",
}

LIB_NAMES = ("_stacks", "_toolsets", "_roles", "_channels")

MISSING = object()


# ---------------------------------------------------------------- YAML I/O

def load_yaml(path):
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def dump_yaml(data, header=None):
    body = yaml.safe_dump(
        data, allow_unicode=True, sort_keys=False,
        default_flow_style=False, width=100,
    )
    return (header.rstrip() + "\n" + body) if header else body


def fmt_val(val):
    return "<нет>" if val is MISSING else json.dumps(val, ensure_ascii=False)


# ---------------------------------------------------------------- дифф

def diff_value(path, live, wanted, out):
    """Рекурсивный дифф двух структур. out: список (путь, live, wanted)."""
    if isinstance(wanted, dict) and isinstance(live, dict):
        for key in wanted:
            sub = "%s.%s" % (path, key) if path else str(key)
            if key in live:
                diff_value(sub, live[key], wanted[key], out)
            else:
                out.append((sub, MISSING, wanted[key]))
        for key in live:
            if key not in wanted:
                sub = "%s.%s" % (path, key) if path else str(key)
                out.append((sub, live[key], MISSING))
    elif wanted != live:
        out.append((path, live, wanted))


# ---------------------------------------------------------------- данные

def load_libs(agents_dir):
    libs = {}
    for name in LIB_NAMES:
        path = os.path.join(agents_dir, name + ".yaml")
        libs[name] = load_yaml(path) if os.path.exists(path) else {}
    return libs


def agent_files(agents_dir):
    if not os.path.isdir(agents_dir):
        sys.exit("НЕТ каталога анкет: %s" % agents_dir)
    return sorted(
        f for f in os.listdir(agents_dir)
        if f.endswith(".yaml") and not f.startswith("_")
    )


def load_docs(agents_dir):
    docs, errors = [], []
    for fname in agent_files(agents_dir):
        path = os.path.join(agents_dir, fname)
        try:
            doc = load_yaml(path) or {}
        except yaml.YAMLError as exc:
            errors.append("%s: синтаксис YAML: %s" % (fname, exc))
            continue
        docs.append((fname, doc))
    return docs, errors


def channel_scope(libs, channel_type):
    preset = (libs.get("_channels") or {}).get(channel_type) or {}
    return preset.get("scope", "account")


def render_agent(doc):
    """Анкета → запись agents.entries.<id> (name := id, мета-ключи отбрасываются)."""
    out = {"name": doc.get("id")}
    for key in AGENT_KEY_ORDER:
        if key in doc:
            out[key] = copy.deepcopy(doc[key])
    for key, val in doc.items():
        if key not in META_KEYS and key not in AGENT_KEY_ORDER:
            out[key] = copy.deepcopy(val)
    return out


def render_channels(docs, libs):
    """Анкеты → фрагмент channels + route-строки bindings."""
    frag, rows = {}, []
    for _, doc in sorted(docs, key=lambda item: item[1].get("id") or ""):
        agent_id = doc.get("id")
        for chan in doc.get("channels") or []:
            ctype = chan.get("type")
            account = chan.get("account")
            settings = chan.get("settings")
            rows.append({
                "type": "route", "agentId": agent_id,
                "match": {"channel": ctype, "accountId": account},
            })
            if settings is None:
                continue
            if channel_scope(libs, ctype) == "channel":
                frag.setdefault(ctype, {}).update(copy.deepcopy(settings))
            else:
                frag.setdefault(ctype, {}).setdefault("accounts", {})[account] = \
                    copy.deepcopy(settings)
    return frag, rows


def binding_tuple(row):
    match = row.get("match") or {}
    return (row.get("type"), row.get("agentId"),
            match.get("channel"), match.get("accountId"))


def agent_diffs(doc, cfg, libs):
    """diff «анкета → конфиг» для одного агента.

    Возвращает (entry_diffs, missing_rows, extra_rows, channel_diffs):
      entry_diffs   — [(путь, live, wanted)] по agents.entries.<id>
      missing_rows  — route-строки bindings, которых нет в конфиге
      extra_rows    — route-строки bindings агента в конфиге, которых нет в анкете
      channel_diffs — [(путь, live, wanted)] по channels-настройкам канала
    """
    agent_id = doc.get("id")
    entries = (cfg.get("agents") or {}).get("entries") or {}
    live_entry = entries.get(agent_id)

    entry_diffs = []
    if live_entry is None:
        entry_diffs.append(("agents.entries.%s" % agent_id,
                            MISSING, render_agent(doc)))
    else:
        diff_value("", live_entry, render_agent(doc), entry_diffs)

    _, rows = render_channels([(None, doc)], libs)
    want_rows = sorted(binding_tuple(r) for r in rows)
    live_rows = sorted(
        binding_tuple(b) for b in (cfg.get("bindings") or [])
        if b.get("type") == "route" and b.get("agentId") == agent_id
    )
    missing_rows = [r for r in want_rows if r not in live_rows]
    extra_rows = [r for r in live_rows if r not in want_rows]

    channels = cfg.get("channels") or {}
    channel_diffs = []
    for chan in doc.get("channels") or []:
        ctype = chan.get("type")
        account = chan.get("account")
        settings = chan.get("settings")
        if settings is None:
            continue
        if channel_scope(libs, ctype) == "channel":
            diff_value("channels.%s" % ctype,
                       channels.get(ctype), settings, channel_diffs)
        else:
            live_set = ((channels.get(ctype) or {}).get("accounts") or {}).get(account)
            diff_value("channels.%s.accounts.%s" % (ctype, account),
                       live_set, settings, channel_diffs)
    return entry_diffs, missing_rows, extra_rows, channel_diffs


def rebuild_bindings(live_bindings, docs, libs, apply_ids):
    """Полный массив bindings: не-route и чужие строки verbatim + route-строки
    управляемых агентов из анкет. Массивы в oc config patch заменяются целиком,
    поэтому патч всегда несёт полный состав."""
    full = [copy.deepcopy(b) for b in (live_bindings or [])
            if not (b.get("type") == "route" and b.get("agentId") in apply_ids)]
    for _, doc in sorted(docs, key=lambda item: item[1].get("id") or ""):
        if doc.get("id") not in apply_ids:
            continue
        _, rows = render_channels([(None, doc)], libs)
        full.extend(copy.deepcopy(rows))
    return full


def build_patch(cfg, docs, libs, ids=None):
    """Патч только с изменёнными кусками + пути полной замены.

    Возвращает (patch, replace_paths, changed, total): patch — JSON5-объект для
    `oc config patch`; replace_paths — для `--replace-path` (запись агента и
    bindings заменяются целиком — merge оставил бы устаревшие ключи/строки).
    """
    entries = (cfg.get("agents") or {}).get("entries") or {}
    live_bindings = cfg.get("bindings") or []
    targets = [(f, d) for f, d in docs
               if d.get("id") and (ids is None or d.get("id") in ids)]
    apply_ids = {d.get("id") for _, d in targets}

    patch, replace, changed = {}, [], {}
    total = 0
    bindings_touch = False

    for _, doc in targets:
        agent_id = doc.get("id")
        entry_diffs, missing, extra, chan_diffs = agent_diffs(doc, cfg, libs)
        if not (entry_diffs or missing or extra or chan_diffs):
            continue
        changed[agent_id] = (entry_diffs, missing, extra, chan_diffs)
        total += len(entry_diffs) + len(missing) + len(extra) + len(chan_diffs)

        if entry_diffs:
            patch.setdefault("agents", {}).setdefault("entries", {})[agent_id] = \
                render_agent(doc)
            replace.append("agents.entries.%s" % agent_id)
        if missing or extra:
            bindings_touch = True
        for chan in doc.get("channels") or []:
            settings = chan.get("settings")
            if settings is None or not chan_diffs:
                continue
            ctype = chan.get("type")
            account = chan.get("account")
            if channel_scope(libs, ctype) == "channel":
                patch.setdefault("channels", {})[ctype] = copy.deepcopy(settings)
                replace.append("channels.%s" % ctype)
            else:
                patch.setdefault("channels", {}).setdefault(ctype, {}) \
                    .setdefault("accounts", {})[account] = copy.deepcopy(settings)
                replace.append("channels.%s.accounts.%s" % (ctype, account))

    if bindings_touch:
        patch["bindings"] = rebuild_bindings(live_bindings, docs, libs, apply_ids)
        replace.append("bindings")
    return patch, replace, changed, total


# ---------------------------------------------------------------- E2: helpers

DEFAULT_OC_CMD = "sudo -u openclaw env HOME=/srv/openclaw /usr/local/bin/openclaw"


def questionnaire_header(agent_id, generator):
    return (
        "# Анкета агента «%s» (%s, %s).\n"
        "# Источник истины для agents.entries.%s, route-строк bindings и настроек\n"
        "# канала. Сгенерировано oc-agent-factory.py %s; критерий приёма:\n"
        "# plan → «0 изменений». Правки: руками здесь → validate → plan → apply.\n"
        "# См. agents/README.md."
        % (agent_id, API_VERSION, KIND, agent_id, generator)
    )


def apply_patch_obj(base, patch, replace_paths=()):
    """Семантика `oc config patch` в чистом Python (для --simulate и тестов):

    объекты сливаются рекурсивно, массивы/скаляры заменяются, null удаляет путь;
    replace_paths — полная замена объекта/массива по пути вместо слияния.
    """
    out = copy.deepcopy(base)
    replace_paths = set(replace_paths)

    def merge(dst, src, path):
        for key, val in src.items():
            sub = "%s.%s" % (path, key) if path else str(key)
            if val is None:
                dst.pop(key, None)
            elif sub in replace_paths:
                dst[key] = copy.deepcopy(val)
            elif isinstance(val, dict) and isinstance(dst.get(key), dict):
                merge(dst[key], val, sub)
            else:
                dst[key] = copy.deepcopy(val)

    merge(out, patch, "")
    return out


def backup_file(path, backup_dir, suffix):
    """Снимок файла перед записью (грабли §1.3). Возвращает путь снимка."""
    os.makedirs(backup_dir, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    dst = os.path.join(backup_dir, "%s.%s.%s" % (os.path.basename(path), stamp, suffix))
    shutil.copy2(path, dst)
    return dst


def run_oc_raw(oc_cmd, args):
    """Произвольная команда oc (например agents delete). Возвращает exit-код."""
    full = shlex.split(oc_cmd) + list(args)
    print("  $ %s" % " ".join(full))
    proc = subprocess.run(full, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    for stream in (proc.stdout, proc.stderr):
        if stream and stream.strip():
            print("    " + stream.strip().replace("\n", "\n    "))
    return proc.returncode


def run_oc(oc_cmd, patch_path, replace_paths, dry_run):
    """Одна валидируемая запись через `oc config patch`. Возвращает exit-код."""
    args = ["config", "patch", "--file", patch_path]
    for rp in replace_paths:
        args += ["--replace-path", rp]
    if dry_run:
        args.append("--dry-run")
    return run_oc_raw(oc_cmd, args)


# Обход gateway-транспорта для `oc agents delete`: при живом gateway удаление
# идёт через его runtime-метод, который отвечает «agent not found» для агентов,
# пересозданных после destroy (tombstone в agent_deletion_journal не занят —
# его занимает только `oc agents add`). С недоступным URL CLI берёт локальный
# путь (replaceConfigFile + allowedAgentRosterRemovals) — работает по файлу.
GATEWAY_BYPASS_ENV = ["OPENCLAW_GATEWAY_URL=http://127.0.0.1:1",
                      "OPENCLAW_GATEWAY_TOKEN=oc-agent-factory-bypass"]


def run_oc_delete(oc_cmd, agent_id, bypass_gateway):
    """`oc agents delete <id> --force`; bypass_gateway — мимо gateway."""
    parts = shlex.split(oc_cmd)
    if bypass_gateway:
        if len(parts) >= 2 and (parts[-2] == "env" or "=" in parts[-2]):
            parts = parts[:-1] + GATEWAY_BYPASS_ENV + parts[-1:]
        else:
            parts = ["env"] + GATEWAY_BYPASS_ENV + parts
    return run_oc_raw(" ".join(parts), ["agents", "delete", agent_id, "--force"])


def scaffold_agent(agent_id, entry):
    """Каркас каталогов нового агента (план §2: workspace + agentDir)."""
    if os.name != "posix":
        print("  (scaffold: не-posix — каталоги не создаются)")
        return
    for key, group, mode in (("workspace", "shared", 0o2775),
                             ("agentDir", "openclaw", 0o755)):
        path = entry.get(key)
        if not path:
            continue
        try:
            os.makedirs(path, exist_ok=True)
            try:
                import grp
                import pwd
                os.chown(path, pwd.getpwnam("openclaw").pw_uid,
                         grp.getgrnam(group).gr_gid)
                os.chmod(path, mode)
            except (ImportError, KeyError, OSError) as exc:
                print("  ! %s: права не выставлены (%s)" % (path, exc))
            print("  + scaffold %s: %s" % (key, path))
        except OSError as exc:
            print("  ! scaffold %s: %s — не создан (%s)" % (key, path, exc))


def default_workspace(agent_id):
    title = "".join(part.capitalize() for part in agent_id.split("-"))
    return "/srv/shared/Projects/%s" % title


def _resolve_path(node, dotted, create_last):
    """Разбор dotted-пути с учётом составных ключей (model id содержат точки).

    На каждом уровне выбирается самый длинный существующий ключ-префикс остатка
    пути; create_last разрешает создание финального сегмента (--set).
    Возвращает (родительский dict, финальный ключ)."""
    rest = dotted
    cur = node
    while True:
        if not isinstance(cur, dict):
            sys.exit("edit: путь «%s» упирается в не-объект" % dotted)
        match = None
        for key in sorted(cur, key=len, reverse=True):
            if rest == key or rest.startswith(key + "."):
                match = key
                break
        if match is not None:
            if rest == match:
                return cur, match
            cur = cur[match]
            rest = rest[len(match) + 1:]
            continue
        if not create_last:
            sys.exit("edit: ключ «%s» не найден (путь «%s»)" % (rest, dotted))
        if "." not in rest:
            return cur, rest
        parts = rest.split(".")
        for part in parts[:-1]:
            nxt = cur.get(part)
            if not isinstance(nxt, dict):
                nxt = {}
                cur[part] = nxt
            cur = nxt
        return cur, parts[-1]


def set_dotted(doc, dotted, value):
    parent, key = _resolve_path(doc, dotted, create_last=True)
    parent[key] = value


def unset_dotted(doc, dotted):
    parent, key = _resolve_path(doc, dotted, create_last=False)
    parent.pop(key, None)


# ---------------------------------------------------------------- E2: new/edit

def find_doc(docs, agent_id):
    for fname, doc in docs:
        if doc.get("id") == agent_id:
            return fname, doc
    return None, None


def cmd_new(args, agents_dir, libs):
    """Анкета нового агента из библиотек. Конфиг НЕ трогается (правки — через apply)."""
    agent_id = args.ids[0] if args.ids else None
    if not agent_id or not re.match(r"^[a-z][a-z0-9-]*$", agent_id):
        sys.exit("new: нужен --id вида [a-z][a-z0-9-]*")
    path = os.path.join(agents_dir, agent_id + ".yaml")
    if os.path.exists(path):
        sys.exit("new: анкета уже существует: %s" % path)

    stacks = libs.get("_stacks") or {}
    toolsets = libs.get("_toolsets") or {}
    roles = libs.get("_roles") or {}

    stack_name = args.stack
    if not stack_name:
        sys.exit("new: нужен --stack (model/models/modelPolicy.allow берутся из стека)")
    stack = stacks.get(stack_name) if stack_name else None
    if stack_name and stack is None:
        sys.exit("new: стек «%s» не найден в _stacks.yaml" % stack_name)
    if stack and stack.get("frozen"):
        sys.exit("new: стек «%s» заморожен (план §11)" % stack_name)

    role_name = args.role
    role = roles.get(role_name) if role_name else None
    if role_name and role is None:
        sys.exit("new: роль «%s» не найдена в _roles.yaml" % role_name)

    # роль подсказывает toolset (см. _roles.yaml), явный --toolset главнее
    toolset_name = args.toolset or (role or {}).get("toolset")
    toolset = toolsets.get(toolset_name) if toolset_name else None
    if toolset_name and toolset is None:
        sys.exit("new: toolset «%s» не найден в _toolsets.yaml" % toolset_name)

    channels = []
    chan_lib = libs.get("_channels") or {}
    for spec in args.channel or []:
        ctype, sep, account = spec.partition(":")
        if not sep or not account:
            sys.exit("new: --channel ждёт type:account, получено «%s»" % spec)
        node = chan_lib.get(ctype)
        if node is None:
            sys.exit("new: канал «%s» не найден в _channels.yaml" % ctype)
        if node.get("kind") == "plugin":
            sys.exit("new: «%s» — плагин (kind: plugin), а не канал; подключение "
                     "вручную — см. agents/_channels.yaml" % ctype)
        if node.get("disabled"):
            sys.exit("new: канал «%s» отключён в _channels.yaml (disabled: true)"
                     % ctype)
        presets = node.get("presets") or {}
        preset_name = node.get("default")
        if not preset_name and len(presets) == 1:
            preset_name = next(iter(presets))
        if not preset_name and len(presets) > 1:
            sys.exit("new: у канала «%s» несколько пресетов (%s) — задайте default "
                     "в _channels.yaml" % (ctype, ", ".join(sorted(presets))))
        entry = {"type": ctype, "account": account}
        if preset_name:
            entry["preset"] = preset_name
            tmpl = (presets.get(preset_name) or {}).get("settingsTemplate")
            if tmpl:
                entry["settings"] = copy.deepcopy(tmpl)
                print("  канал %s/%s: settings из пресета «%s» — проверьте "
                      "tokenFile/секреты и allowFrom" % (ctype, account, preset_name))
        channels.append(entry)

    doc = {"apiVersion": API_VERSION, "kind": KIND, "id": agent_id,
           "origin": "factory"}
    if stack_name:
        doc["stack"] = stack_name
    if role_name:
        doc["role"] = role_name
    if toolset_name:
        doc["toolset"] = toolset_name
    doc["channels"] = channels
    doc["workspace"] = args.workspace or default_workspace(agent_id)
    doc["agentDir"] = (args.agent_dir
                       or "/srv/openclaw/.openclaw/agents/%s/agent" % agent_id)
    doc["identity"] = {"name": args.name or agent_id}
    if args.emoji:
        doc["identity"]["emoji"] = args.emoji
    if stack:  # стек по-умолчанию: model/models/modelPolicy.allow (решение 2026-10-14)
        for key in ("model", "models", "modelPolicy"):
            if stack.get(key) is not None:
                doc[key] = copy.deepcopy(stack[key])
    if toolset and toolset.get("tools") is not None:
        doc["tools"] = copy.deepcopy(toolset["tools"])
    if role and role.get("subagents") is not None:
        doc["subagents"] = copy.deepcopy(role["subagents"])
    doc["thinkingDefault"] = args.thinking or "max"

    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(dump_yaml(doc, questionnaire_header(agent_id, "new")))
    print("[OK] new %s -> %s" % (agent_id, path))
    print("Дальше: validate → plan → apply --yes")
    return 0


def cmd_edit(args, agents_dir):
    """Точечные правки анкеты (--set path=value / --unset path); конфиг не трогается."""
    if not args.ids or len(args.ids) != 1:
        sys.exit("edit: нужен ровно один --id")
    agent_id = args.ids[0]
    path = os.path.join(agents_dir, agent_id + ".yaml")
    if not os.path.exists(path):
        sys.exit("edit: анкета не найдена: %s" % path)
    if not (args.set_values or args.unset_values):
        sys.exit("edit: нужны --set path=value и/или --unset path")

    doc = load_yaml(path) or {}
    for spec in args.set_values or []:
        key, sep, raw = spec.partition("=")
        if not sep:
            sys.exit("edit: --set ждёт path=value, получено «%s»" % spec)
        try:
            value = yaml.safe_load(raw)
        except yaml.YAMLError:
            value = raw
        set_dotted(doc, key, value)
        print("  set %s = %s" % (key, fmt_val(value)))
    for key in args.unset_values or []:
        unset_dotted(doc, key)
        print("  unset %s" % key)

    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(dump_yaml(doc, questionnaire_header(agent_id, "edit")))
    print("[OK] edit %s — дальше: validate → plan → apply" % path)
    return 0


# ---------------------------------------------------------------- E2: apply/destroy

def cmd_apply(config_path, agents_dir, libs, ids, dry_run=False, yes=False,
              simulate=None, backup_dir=None, oc_cmd=DEFAULT_OC_CMD):
    """validate → plan → бэкап → oc config patch --dry-run → запись → контроль (plan=0).

    Без --yes после успешного dry-run ничего не пишется (exit 2).
    --simulate PATH: прогнать merge-семантику локально, записать смерженный конфиг
    в PATH и не трогать реальный конфиг/сервер.
    """
    with open(config_path, encoding="utf-8") as fh:
        cfg = json.load(fh)
    if cmd_validate(agents_dir, libs, cfg=cfg) != 0:
        print("apply: validate провален — ничего не применяю")
        return 1
    docs, _ = load_docs(agents_dir)
    if ids:
        wanted = set(ids)
        docs = [(f, d) for f, d in docs if d.get("id") in wanted]
        known = {d.get("id") for _, d in docs}
        for aid in ids:
            if aid not in known:
                sys.exit("apply: анкета «%s» не найдена в %s" % (aid, agents_dir))

    patch, replace, changed, total = build_patch(cfg, docs, libs)
    if not patch:
        print("apply: нечего применять (0 изменений)")
        return 0

    print("apply: изменения по агентам: %s (всего %d)" %
          (", ".join(sorted(changed)), total))
    for aid in sorted(changed):
        entry_diffs, missing, extra, chan_diffs = changed[aid]
        for path, live, wanted_val in entry_diffs + chan_diffs:
            print("  %s: %s -> %s" % (path, fmt_val(live), fmt_val(wanted_val)))
        for row in missing:
            print("  bindings+%r" % (row,))
        for row in extra:
            print("  bindings-%r" % (row,))

    entries = (cfg.get("agents") or {}).get("entries") or {}
    new_ids = [d.get("id") for _, d in docs if d.get("id") not in entries]

    if simulate:
        merged = apply_patch_obj(cfg, patch, replace)
        with open(simulate, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(merged, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
        print("apply --simulate: смерженный конфиг -> %s (реальный конфиг не тронут)" % simulate)
        return 0

    stamp = time.strftime("%Y%m%d-%H%M%S")
    backup_dir = backup_dir or "/srv/openclaw/backups/factory"
    os.makedirs(backup_dir, exist_ok=True)
    backup = backup_file(config_path, backup_dir, "pre-apply")
    patch_path = os.path.join(backup_dir, "patch-%s.json5" % stamp)
    with open(patch_path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(patch, ensure_ascii=False, indent=1))
    print("бэкап конфига -> %s" % backup)
    print("патч -> %s" % patch_path)

    if run_oc(oc_cmd, patch_path, replace, dry_run=True) != 0:
        print("apply: oc config patch --dry-run провалился — конфиг не изменён")
        return 1
    if dry_run:
        print("apply --dry-run: проверка прошла, запись не выполнялась")
        return 0
    if not yes:
        print("apply: dry-run ok; для записи добавьте --yes")
        return 2

    if run_oc(oc_cmd, patch_path, replace, dry_run=False) != 0:
        print("apply: ЗАПИСЬ ПРОВАЛЕНА; откат: cp %s %s" % (backup, config_path))
        return 1

    for aid in new_ids:  # каркас каталогов только для создаваемых агентов
        _, doc = find_doc(docs, aid)
        scaffold_agent(aid, render_agent(doc))

    with open(config_path, encoding="utf-8") as fh:
        fresh = json.load(fh)
    _, _, left, left_total = build_patch(fresh, docs, libs)
    if left:
        print("apply: КОНТРОЛЬ провалился — осталось %d изменений, см. plan" % left_total)
        return 1
    print("apply: ok — контрольный plan даёт 0 изменений")
    return 0


def cmd_destroy(config_path, agents_dir, agent_id, confirm=False,
                dry_run=False, simulate=None, backup_dir=None,
                oc_cmd=DEFAULT_OC_CMD):
    """Удаление агента: запись — `oc agents delete`, данные — в export-снимок.

    Грабли (2026-10-20): `oc config patch/set/unset` НЕ удаляют записи ростера
    («Config write would drop agent roster entries without an explicit deletion»);
    единственное явное удаление даёт `oc agents delete`, но он прунит workspace/state.
    Поэтому destroy: (1) переносит workspace/agentDir в снимок (данные не теряются),
    (2) `oc agents delete <id> --force` (при отказе gateway — повтор с обходом
    транспорта: локальный fallback снимает tombstone-грабли), (3) добивает
    route-строки через `oc config patch --replace-path bindings`. Обязателен
    --confirm; перед записью — бэкап конфига и снимок анкеты (план §10)."""
    if not agent_id:
        sys.exit("destroy: нужен --id")
    with open(config_path, encoding="utf-8") as fh:
        cfg = json.load(fh)
    entries = (cfg.get("agents") or {}).get("entries") or {}
    bindings = cfg.get("bindings") or []
    entry = entries.get(agent_id)
    rows = [b for b in bindings
            if b.get("type") == "route" and b.get("agentId") == agent_id]
    docs, _ = load_docs(agents_dir)
    fname, doc = find_doc(docs, agent_id)
    if entry is None and not rows and doc is None:
        print("destroy: %s не найден ни в конфиге, ни в анкетах — нечего удалять" % agent_id)
        return 0

    print("destroy %s — будет удалено из конфига:" % agent_id)
    if entry is not None:
        print("  agents.entries.%s (workspace: %s; agentDir: %s)"
              % (agent_id, entry.get("workspace"), entry.get("agentDir")))
    for row in rows:
        print("  bindings%r" % (binding_tuple(row),))
    own_settings = ["%s/%s" % (c.get("type"), c.get("account"))
                    for c in (doc or {}).get("channels") or [] if c.get("settings")]
    if own_settings:
        print("  ! settings каналов остаются в конфиге (при необходимости — вручную): %s"
              % ", ".join(own_settings))
    print("  workspace/agentDir ПЕРЕМЕЩАЮТСЯ в снимок (данные не теряются)")

    if not confirm:
        print("destroy: предпросмотр; для записи нужен --confirm")
        return 2

    patch = {"agents": {"entries": {agent_id: None}}}  # конечный вид (для --simulate)
    replace = []
    if rows:
        patch["bindings"] = [b for b in bindings
                             if not (b.get("type") == "route"
                                     and b.get("agentId") == agent_id)]
        replace.append("bindings")

    if simulate:
        merged = apply_patch_obj(cfg, patch, replace)
        with open(simulate, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(merged, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
        print("destroy --simulate: конечный вид конфига -> %s (реальный конфиг не тронут)" % simulate)
        return 0

    if dry_run:
        print("destroy --dry-run: ок, ничего не изменено; план:")
        print("  mv workspace/agentDir -> снимок; oc agents delete %s --force;"
              " bindings-патч при необходимости" % agent_id)
        return 0

    stamp = time.strftime("%Y%m%d-%H%M%S")
    backup_dir = backup_dir or "/srv/openclaw/backups/factory"
    snap_dir = os.path.join(backup_dir, "destroy-%s-%s" % (agent_id, stamp))
    os.makedirs(snap_dir, exist_ok=True)
    backup = backup_file(config_path, backup_dir, "pre-destroy")
    with open(os.path.join(snap_dir, "entry.json"), "w",
              encoding="utf-8", newline="\n") as fh:
        json.dump({"entry": entry, "bindings": rows}, fh, ensure_ascii=False, indent=1)
    if fname:
        shutil.copy2(os.path.join(agents_dir, fname), os.path.join(snap_dir, fname))
    print("бэкап конфига -> %s" % backup)
    print("export-снимок -> %s" % snap_dir)

    # 1) данные агента — в снимок (иначе oc agents delete их прунет).
    for key in ("workspace", "agentDir"):
        path = (entry or {}).get(key)
        if not path or not os.path.exists(path):
            continue
        dst = os.path.join(snap_dir, "data-%s" % key)
        shutil.move(path, dst)
        print("  данные %s -> %s" % (key, dst))

    # 2) явное удаление записи ростера (единственный разрешённый путь).
    if entry is not None:
        rc = run_oc_delete(oc_cmd, agent_id, bypass_gateway=False)
        if rc != 0:
            print("  ! удаление через gateway провалилось (runtime отстаёт или "
                  "tombstone в agent_deletion_journal); повтор с обходом gateway")
            rc = run_oc_delete(oc_cmd, agent_id, bypass_gateway=True)
        if rc != 0:
            print("destroy: oc agents delete провалился; данные — в снимке; "
                  "откат конфига: cp %s %s" % (backup, config_path))
            return 1

    # 3) route-строки, которые могли остаться, — патчем (roster guard не мешает).
    with open(config_path, encoding="utf-8") as fh:
        fresh = json.load(fh)
    live_rows = [b for b in (fresh.get("bindings") or [])
                 if b.get("type") == "route" and b.get("agentId") == agent_id]
    if live_rows:
        patch_path = os.path.join(snap_dir, "patch-bindings.json5")
        patch2 = {"bindings": [b for b in (fresh.get("bindings") or [])
                               if not (b.get("type") == "route"
                                       and b.get("agentId") == agent_id)]}
        with open(patch_path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(patch2, ensure_ascii=False, indent=1))
        if run_oc(oc_cmd, patch_path, ["bindings"], dry_run=False) != 0:
            print("destroy: bindings-патч провалился — откат: cp %s %s"
                  % (backup, config_path))
            return 1

    if fname:  # анкету убираем только после успешной записи
        os.remove(os.path.join(agents_dir, fname))
        print("анкета %s убрана (снимок в %s)" % (fname, snap_dir))

    with open(config_path, encoding="utf-8") as fh:
        fresh = json.load(fh)
    gone_entry = agent_id not in ((fresh.get("agents") or {}).get("entries") or {})
    gone_rows = not [b for b in (fresh.get("bindings") or [])
                     if b.get("type") == "route" and b.get("agentId") == agent_id]
    if not (gone_entry and gone_rows):
        print("destroy: КОНТРОЛЬ провалился — запись/строки агента остались в конфиге")
        return 1
    print("destroy: ok — запись и route-строки «%s» удалены; данные — в снимке; "
          "остальные агенты не тронуты" % agent_id)
    return 0


# ---------------------------------------------------------------- export

def cmd_export(cfg, agents_dir, libs):
    entries = (cfg.get("agents") or {}).get("entries") or {}
    bindings = cfg.get("bindings") or []
    channels = cfg.get("channels") or {}
    claimed_channel_scope = {}
    count = 0

    for agent_id in sorted(entries):
        entry = copy.deepcopy(entries[agent_id])
        entry.pop("name", None)  # восстанавливается рендером как name := id
        rows = [b for b in bindings if b.get("agentId") == agent_id]

        chan_list = []
        for row in rows:
            match = row.get("match") or {}
            ctype, account = match.get("channel"), match.get("accountId")
            settings = None
            if channel_scope(libs, ctype) == "channel":
                if ctype in claimed_channel_scope:
                    print("  ! %s: канал %s (scope=channel) уже описан анкетой %s — "
                          "settings не дублирую"
                          % (agent_id, ctype, claimed_channel_scope[ctype]))
                else:
                    claimed_channel_scope[ctype] = agent_id
                    settings = copy.deepcopy(channels.get(ctype) or {})
            else:
                acc = ((channels.get(ctype) or {}).get("accounts") or {}).get(account)
                settings = copy.deepcopy(acc) if acc is not None else None
            item = {"type": ctype, "account": account}
            if settings is not None:
                item["settings"] = settings
            chan_list.append(item)

        path = os.path.join(agents_dir, agent_id + ".yaml")
        old = {}
        if os.path.exists(path):
            try:
                old = load_yaml(path) or {}
            except yaml.YAMLError:
                old = {}

        doc = {"apiVersion": API_VERSION, "kind": KIND, "id": agent_id,
               "origin": "migrated"}
        for key in ("stack", "role", "toolset", "notes", "projects", "reports"):
            if key in old:  # аннотации сохраняем при перегенерации
                doc[key] = old[key]
        doc["channels"] = chan_list
        for key in AGENT_KEY_ORDER:
            if key in entry:
                doc[key] = entry.pop(key)
        for key, val in entry.items():  # прочие ключи записи — verbatim
            if key != "name":
                doc[key] = val

        header = (
            "# Анкета агента «%s» (%s, %s).\n"
            "# Источник истины для agents.entries.%s, route-строк bindings и настроек\n"
            "# канала. Сгенерировано oc-agent-factory.py export; критерий приёма:\n"
            "# plan → «0 изменений». Правки: руками здесь → validate → plan → apply.\n"
            "# См. agents/README.md."
            % (agent_id, API_VERSION, KIND, agent_id)
        )
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(dump_yaml(doc, header))
        count += 1
        print("[OK] export %s -> %s" % (agent_id, path))

    print("export: %d анкет(ы) записано в %s" % (count, agents_dir))
    return 0


# ---------------------------------------------------------------- validate

def check_secret_refs(node, where, problems, warns, check_secrets):
    """Рекурсивно ищет tokenFile/secretRef; значения секретов в анкетах запрещены."""
    if isinstance(node, dict):
        for key, val in node.items():
            if key in ("tokenFile", "secretRef") and isinstance(val, str):
                if not val.startswith("/srv/"):
                    warns.append("%s: %s=%s не похож на абсолютный путь секрета"
                                 % (where, key, val))
                elif check_secrets and not os.path.exists(val):
                    problems.append("%s: секрет НЕ найден: %s" % (where, val))
            else:
                check_secret_refs(val, where, problems, warns, check_secrets)
    elif isinstance(node, list):
        for item in node:
            check_secret_refs(item, where, problems, warns, check_secrets)


def cmd_validate(agents_dir, libs, check_secrets=False, cfg=None):
    docs, errors = load_docs(agents_dir)
    problems = list(errors)   # блокируют (exit 1)
    warns = []                # не блокируют (exit 0)
    stacks = libs.get("_stacks") or {}
    toolsets = libs.get("_toolsets") or {}
    roles = libs.get("_roles") or {}
    chan_lib = libs.get("_channels") or {}
    seen_ids = {}

    for fname, doc in docs:
        where = fname
        agent_id = doc.get("id")
        if not agent_id:
            problems.append("%s: нет id" % where)
            continue
        if agent_id in seen_ids:
            problems.append("%s: id «%s» уже занят файлом %s"
                            % (where, agent_id, seen_ids[agent_id]))
        seen_ids[agent_id] = fname
        if doc.get("apiVersion") != API_VERSION:
            problems.append("%s: apiVersion != %s" % (where, API_VERSION))
        if doc.get("kind") != KIND:
            problems.append("%s: kind != %s" % (where, KIND))
        if fname != agent_id + ".yaml":
            problems.append("%s: имя файла != id + '.yaml'" % where)

        stack_name = doc.get("stack")
        if stack_name and stack_name not in stacks:
            problems.append("%s: stack «%s» не найден в _stacks.yaml"
                            % (where, stack_name))
        elif stack_name:
            stack = stacks[stack_name] or {}
            stack_primary = ((stack.get("model") or {}).get("primary"))
            doc_primary = ((doc.get("model") or {}).get("primary"))
            if stack_primary and doc_primary and stack_primary != doc_primary:
                warns.append("%s: model.primary «%s» расходится со стеком «%s» (%s)"
                             % (where, doc_primary, stack_name, stack_primary))

        toolset_name = doc.get("toolset")
        if toolset_name and toolset_name not in toolsets:
            problems.append("%s: toolset «%s» не найден в _toolsets.yaml"
                            % (where, toolset_name))
        role_name = doc.get("role")
        if role_name and role_name not in roles:
            problems.append("%s: role «%s» не найдена в _roles.yaml"
                            % (where, role_name))

        # modelPolicy.allow — жёсткий allowlist (решение 2026-10-14).
        # origin: migrated → предупреждение (включение allowlist — отдельным шагом
        # после миграции, чтобы не менять конфиг); для новых агентов — обязательно.
        policy = doc.get("modelPolicy") or {}
        allow = policy.get("allow")
        primary = ((doc.get("model") or {}).get("primary"))
        if not allow:
            if doc.get("origin") == "migrated":
                warns.append("%s: нет modelPolicy.allow (migrated) — включить "
                             "отдельным шагом после миграции" % where)
            else:
                problems.append("%s: НЕТ modelPolicy.allow — жёсткий allowlist "
                                "обязателен для новых агентов" % where)
        elif primary and primary not in allow:
            problems.append("%s: model.primary «%s» не входит в modelPolicy.allow"
                            % (where, primary))

        # subagents.allowAgents — только известные id (свои и чужие анкеты).
        allow_agents = ((doc.get("subagents") or {}).get("allowAgents")) or []
        for ref in allow_agents:
            if ref != agent_id and ref + ".yaml" not in [f for f, _ in docs]:
                problems.append("%s: subagents.allowAgents ссылается на неизвестного "
                                "агента «%s»" % (where, ref))

        # Per-entry subagents (схема 2026.8.2, dry-run 2026-10-20): допустимы
        # только delegationMode, allowAgents, model, thinking, requireAgentId.
        # Лимиты — глобально (agents.defaults.subagents).
        SUBAGENTS_GLOBAL_ONLY = {"maxSpawnDepth", "maxConcurrent",
                                 "maxChildrenPerAgent", "runTimeoutSeconds",
                                 "announceTimeoutMs", "archiveAfterMinutes"}
        SUBAGENTS_ENTRY_KEYS = {"delegationMode", "allowAgents", "model",
                                "thinking", "requireAgentId"}
        for key in (doc.get("subagents") or {}):
            if key in SUBAGENTS_GLOBAL_ONLY:
                problems.append("%s: subagents.%s — глобальный ключ "
                                "(agents.defaults.subagents), per-entry его нет"
                                % (where, key))
            elif key not in SUBAGENTS_ENTRY_KEYS:
                warns.append("%s: subagents.%s — неизвестен схеме per-entry "
                             "(допустимы: %s)" % (where, key,
                                                  ", ".join(sorted(SUBAGENTS_ENTRY_KEYS))))

        # Секреты — только ссылки (tokenFile/secretRef).
        check_secret_refs(doc.get("channels") or [], where, problems, warns,
                          check_secrets)

        # Каналы: type/account обязательны; тип — из _channels.yaml; пресеты
        # kind: plugin каналом не являются; disabled-каналы не использовать.
        for chan in doc.get("channels") or []:
            if not chan.get("type") or not chan.get("account"):
                problems.append("%s: канал без type/account: %s" % (where, chan))
                continue
            ctype = chan.get("type")
            node = chan_lib.get(ctype)
            if node is None:
                problems.append("%s: канал type=%s не найден в _channels.yaml"
                                % (where, ctype))
            elif node.get("kind") == "plugin":
                problems.append("%s: type=%s — плагин (kind: plugin), не канал "
                                "(подключение вручную, см. _channels.yaml)"
                                % (where, ctype))
            elif node.get("disabled"):
                problems.append("%s: канал type=%s отключён в _channels.yaml"
                                % (where, ctype))

    # Конфликт претензий на settings канала с scope=channel.
    claims = {}
    for fname, doc in docs:
        for chan in doc.get("channels") or []:
            ctype = chan.get("type")
            if channel_scope(libs, ctype) == "channel" and chan.get("settings"):
                if ctype in claims:
                    problems.append("канал «%s» (scope=channel) описан settings в двух "
                                    "анкетах: %s и %s" % (ctype, claims[ctype], fname))
                else:
                    claims[ctype] = fname

    # Плагиновые пресеты: pluginId должен быть в plugins.allow живого конфига
    # (план §9: «пресет канала = +id в allowlist»). Bundled-каналы id не требуют —
    # их плагин активируется сам при enabled: true (oc config schema, 2026-10-20).
    if cfg is not None:
        allow = ((cfg.get("plugins") or {}).get("allow")) or []
        for ctype, node in sorted(chan_lib.items()):
            if (node or {}).get("kind") != "plugin":
                continue
            pid = node.get("pluginId") or ctype
            if allow and pid not in allow:
                warns.append("_channels.yaml: плагин «%s» (пресеты: %s) не в "
                             "plugins.allow (%d id) — для подключения добавить id"
                             % (pid,
                                ", ".join(sorted((node.get("presets") or {}))),
                                len(allow)))

    print("validate: %d анкет, %d ошибок, %d предупреждений"
          % (len(docs), len(problems), len(warns)))
    for msg in problems:
        print("  X " + msg)
    for msg in warns:
        print("  ! " + msg)
    return 1 if problems else 0


# ---------------------------------------------------------------- plan

def cmd_plan(cfg, agents_dir, libs, emit_patch=None):
    docs, errors = load_docs(agents_dir)
    problems = list(errors)
    entries = (cfg.get("agents") or {}).get("entries") or {}
    bindings = cfg.get("bindings") or []
    channels = cfg.get("channels") or {}

    frag, rows = render_channels(docs, libs)
    changes = 0

    for fname, doc in docs:
        agent_id = doc.get("id")
        if not agent_id:
            problems.append("%s: нет id — пропущен" % fname)
            continue

        out = []
        live_entry = entries.get(agent_id)
        wanted_entry = render_agent(doc)
        if live_entry is None:
            out.append(("agents.entries.%s" % agent_id, MISSING, wanted_entry))
        else:
            diff_value("", live_entry, wanted_entry, out)

        want_rows = sorted(binding_tuple(r) for r in rows if r["agentId"] == agent_id)
        live_rows = sorted(binding_tuple(b) for b in bindings
                           if b.get("agentId") == agent_id)
        for miss in [r for r in want_rows if r not in live_rows]:
            out.append(("bindings%r" % (miss,), MISSING, miss))
        for extra in [r for r in live_rows if r not in want_rows]:
            out.append(("bindings%r" % (extra,), extra, MISSING))

        for chan in doc.get("channels") or []:
            ctype, account = chan.get("type"), chan.get("account")
            settings = chan.get("settings")
            if settings is None:
                continue
            if channel_scope(libs, ctype) == "channel":
                live_set = channels.get(ctype)
                diff_value("channels.%s" % ctype, live_set, settings, out)
            else:
                live_set = ((channels.get(ctype) or {}).get("accounts") or {}).get(account)
                diff_value("channels.%s.accounts.%s" % (ctype, account),
                           live_set, settings, out)

        if out:
            changes += len(out)
            print("ИЗМЕНЕНИЯ %s:" % agent_id)
            for path, live, wanted in out:
                print("  %s: %s -> %s" % (path, fmt_val(live), fmt_val(wanted)))
        else:
            print("OK %s: 0 изменений" % agent_id)

    # В конфиге есть записи, которых нет в анкетах — план их не трогает.
    known = {doc.get("id") for _, doc in docs}
    for entry_id in sorted(entries):
        if entry_id not in known:
            print("! %s: есть в конфиге, но анкеты нет — не управляется" % entry_id)

    if emit_patch:
        os.makedirs(emit_patch, exist_ok=True)
        patch, replace, _, _ = build_patch(cfg, docs, libs)
        ppath = os.path.join(emit_patch, "patch.json5")
        with open(ppath, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(patch, ensure_ascii=False, indent=1))
        rpath = os.path.join(emit_patch, "patch.replace-paths.txt")
        with open(rpath, "w", encoding="utf-8", newline="\n") as fh:
            fh.write("\n".join(replace) + ("\n" if replace else ""))
        print("patch -> %s (replace-paths -> %s)" % (ppath, rpath))

    print("plan: %d изменений" % changes)
    return 2 if changes or problems else 0


# ---------------------------------------------------------------- main

def main(argv=None):
    ap = argparse.ArgumentParser(prog="oc-agent-factory",
                                 description="«Фабрика агентов» OPF-8 (E2–E3: "
                                             "new/edit/export/validate/plan/apply/destroy)")
    ap.add_argument("command",
                    choices=("new", "edit", "export", "validate", "plan",
                             "apply", "destroy"))
    ap.add_argument("--config", default="/srv/openclaw/.openclaw/openclaw.json",
                    help="путь к openclaw.json")
    ap.add_argument("--agents-dir", default="agents",
                    help="каталог анкет (agents/*.yaml)")
    ap.add_argument("--id", dest="ids", action="append", default=None,
                    help="id агента (new/edit/destroy — один; apply — фильтр)")
    ap.add_argument("--check-secrets", action="store_true",
                    help="validate: проверять существование tokenFile/secretRef")
    ap.add_argument("--emit-patch", default=None,
                    help="plan: записать patch.json5 + patch.replace-paths.txt в каталог")
    # new
    ap.add_argument("--stack", default=None, help="new: стек из _stacks.yaml")
    ap.add_argument("--toolset", default=None, help="new: тулсет из _toolsets.yaml")
    ap.add_argument("--role", default=None, help="new: роль из _roles.yaml")
    ap.add_argument("--channel", action="append", default=None, metavar="TYPE:ACCOUNT",
                    help="new: канал (repeatable)")
    ap.add_argument("--name", default=None, help="new: identity.name")
    ap.add_argument("--emoji", default=None, help="new: identity.emoji")
    ap.add_argument("--workspace", default=None, help="new: workspace (default: /srv/shared/Projects/<Id>)")
    ap.add_argument("--agent-dir", default=None, help="new: agentDir")
    ap.add_argument("--thinking", default=None, help="new: thinkingDefault (default: max)")
    # edit
    ap.add_argument("--set", dest="set_values", action="append", default=None,
                    metavar="PATH=VALUE", help="edit: установить значение (repeatable)")
    ap.add_argument("--unset", dest="unset_values", action="append", default=None,
                    metavar="PATH", help="edit: удалить ключ (repeatable)")
    # apply/destroy
    ap.add_argument("--dry-run", action="store_true",
                    help="apply/destroy: только oc config patch --dry-run")
    ap.add_argument("--yes", action="store_true",
                    help="apply: разрешить запись (иначе только dry-run)")
    ap.add_argument("--confirm", action="store_true",
                    help="destroy: подтвердить удаление")
    ap.add_argument("--simulate", default=None, metavar="PATH",
                    help="apply/destroy: смержить локально в PATH, конфиг не трогать")
    ap.add_argument("--backup-dir", default=None,
                    help="каталог бэкапов (default: /srv/openclaw/backups/factory)")
    ap.add_argument("--oc-cmd", default=DEFAULT_OC_CMD,
                    help="команда вызова oc (default: %s)" % DEFAULT_OC_CMD)
    args = ap.parse_args(argv)

    libs = load_libs(args.agents_dir)
    if args.command == "new":
        return cmd_new(args, args.agents_dir, libs)
    if args.command == "edit":
        return cmd_edit(args, args.agents_dir)
    if args.command == "validate":
        cfg = None
        if os.path.exists(args.config):
            with open(args.config, encoding="utf-8") as fh:
                cfg = json.load(fh)
        return cmd_validate(args.agents_dir, libs, args.check_secrets, cfg)

    if not os.path.exists(args.config):
        sys.exit("НЕТ конфига: %s" % args.config)
    with open(args.config, encoding="utf-8") as fh:
        cfg = json.load(fh)

    if args.command == "export":
        return cmd_export(cfg, args.agents_dir, libs)
    if args.command == "plan":
        return cmd_plan(cfg, args.agents_dir, libs, args.emit_patch)
    if args.command == "apply":
        return cmd_apply(args.config, args.agents_dir, libs, args.ids,
                         dry_run=args.dry_run, yes=args.yes,
                         simulate=args.simulate, backup_dir=args.backup_dir,
                         oc_cmd=args.oc_cmd)
    return cmd_destroy(args.config, args.agents_dir,
                       args.ids[0] if args.ids else None,
                       confirm=args.confirm, dry_run=args.dry_run,
                       simulate=args.simulate, backup_dir=args.backup_dir,
                       oc_cmd=args.oc_cmd)


if __name__ == "__main__":
    sys.exit(main())



