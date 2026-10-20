#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""oc-agent-factory — «Фабрика агентов» OpenClaw (OPF-8).

Анкеты agents/*.yaml (git — источник истины) ↔ openclaw.json (производный артефакт).

Команды этапа E1 (конфиг НЕ изменяется, только чтение):
  export   — openclaw.json → agents/<id>.yaml (verbatim-зеркало управляемых фрагментов)
  validate — проверка анкет и библиотек agents/_*.yaml
  plan     — diff «анкета → конфиг» по управляемым поддеревьям; exit 2, если есть изменения

Принципы (решения 2026-10-14):
  * миграция минимально-инвазивна: export обязан давать plan «0 изменений» по всем агентам;
  * правки конфига — только через анкету + plan перед apply (apply — этап E2, сюда не входит);
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
Запуск: python3 oc-agent-factory.py export|validate|plan [--config PATH]
        [--agents-dir PATH] [--check-secrets] [--emit-patch DIR]
"""

import argparse
import copy
import json
import os
import sys

try:
    import yaml
except ImportError:  # pragma: no cover
    sys.exit("ТРЕБУЕТСЯ PyYAML (python3-yaml / pip install pyyaml); проверено: 6.0.3")

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


def cmd_validate(agents_dir, libs, check_secrets=False):
    docs, errors = load_docs(agents_dir)
    problems = list(errors)   # блокируют (exit 1)
    warns = []                # не блокируют (exit 0)
    stacks = libs.get("_stacks") or {}
    toolsets = libs.get("_toolsets") or {}
    roles = libs.get("_roles") or {}
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

        # Секреты — только ссылки (tokenFile/secretRef).
        check_secret_refs(doc.get("channels") or [], where, problems, warns,
                          check_secrets)

        # Каналы: type/account обязательны.
        for chan in doc.get("channels") or []:
            if not chan.get("type") or not chan.get("account"):
                problems.append("%s: канал без type/account: %s" % (where, chan))

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
        for fname, doc in docs:
            agent_id = doc.get("id")
            if not agent_id:
                continue
            agent_frag, agent_rows = render_channels([(fname, doc)], libs)
            patch = {
                "agents": {"entries": {agent_id: render_agent(doc)}},
                "bindings": agent_rows,
                "channels": agent_frag,
            }
            path = os.path.join(emit_patch, "patch-%s.json5" % agent_id)
            with open(path, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(json.dumps(patch, ensure_ascii=False, indent=1))
            print("patch -> %s" % path)

    print("plan: %d изменений" % changes)
    return 2 if changes or problems else 0


# ---------------------------------------------------------------- main

def main(argv=None):
    ap = argparse.ArgumentParser(prog="oc-agent-factory",
                                 description="«Фабрика агентов» OPF-8 (E1: "
                                             "export/validate/plan, только чтение)")
    ap.add_argument("command", choices=("export", "validate", "plan"))
    ap.add_argument("--config", default="/srv/openclaw/.openclaw/openclaw.json",
                    help="путь к openclaw.json")
    ap.add_argument("--agents-dir", default="agents",
                    help="каталог анкет (agents/*.yaml)")
    ap.add_argument("--check-secrets", action="store_true",
                    help="validate: проверять существование tokenFile/secretRef")
    ap.add_argument("--emit-patch", default=None,
                    help="plan: записать patch-*.json5 в каталог")
    args = ap.parse_args(argv)

    libs = load_libs(args.agents_dir)
    if args.command == "validate":
        return cmd_validate(args.agents_dir, libs, args.check_secrets)

    if not os.path.exists(args.config):
        sys.exit("НЕТ конфига: %s" % args.config)
    with open(args.config, encoding="utf-8") as fh:
        cfg = json.load(fh)

    if args.command == "export":
        return cmd_export(cfg, args.agents_dir, libs)
    return cmd_plan(cfg, args.agents_dir, libs, args.emit_patch)


if __name__ == "__main__":
    sys.exit(main())



