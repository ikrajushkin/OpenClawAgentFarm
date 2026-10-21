#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""oc-reports — синхронизация автоматизаций-дайджестов из анкет агентов (E6/T8).

Источник истины — анкета (agents/*.yaml), поле `reports.digest`:

  reports:
    digest:
      schedule: "0 9 * * *"        # cron (5/6 полей)
      tz: Europe/Moscow            # IANA (необязательно)
      channel: telegram            # канал доставки
      account: service             # аккаунт канала (multi-account)
      to: "10292232"               # chatId/номер владельца
      days: 1                      # период дайджеста (дни)
      enabled: true                # false — automation выключена

Скрипт управляет automation OpenClaw (command job без агентского хода):
stdout oc-project-digest.py → `--announce` в канал владельца. Имя automation —
`factory-digest-<agent>`, declaration-key `factory:<agent>:digest` (идемпотентность).

  python3 oc-reports.py --diff   # что изменится (read-only)
  python3 oc-reports.py --apply  # создать/выровнять автоматизации
  python3 oc-reports.py --apply --prune  # + удалить лишние factory-digest-*

Запускать от пользователя openclaw (или с HOME=/srv/openclaw) — нужен доступ
к gateway CLI.
"""
import argparse
import importlib.util
import json
import os
import subprocess
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

JOB_PREFIX = "factory-digest-"
DECL_PREFIX = "factory:"
DIGEST_SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "oc-project-digest.py")


def load_factory_docs(agents_dir):
    """Анкеты через oc-agent-factory.load_docs (PyYAML) — тот же формат."""
    factory_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "oc-agent-factory.py")
    spec = importlib.util.spec_from_file_location("oc_agent_factory", factory_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    docs, errors = mod.load_docs(agents_dir)
    return docs, errors


def digest_spec(doc):
    """Желаемое состояние automation из анкеты; None — дайджест не настроен."""
    reports = doc.get("reports") or {}
    digest = reports.get("digest") or {}
    if not digest.get("schedule"):
        return None
    agent = doc.get("id") or doc.get("agent")
    if not agent:
        return None
    ws = doc.get("workspace") or ""
    days = int(digest.get("days") or 1)
    command = "python3 %s --workspace %s --days %d --save" % (
        DIGEST_SCRIPT, ws, days)
    return {
        "agent": agent,
        "name": JOB_PREFIX + agent,
        "display_name": "Дайджест проектов %s" % agent,
        "schedule": digest["schedule"],
        "tz": digest.get("tz") or "",
        "channel": digest.get("channel") or "telegram",
        "account": digest.get("account") or "",
        "to": str(digest.get("to") or ""),
        "days": days,
        "command": command,
        "enabled": bool(digest.get("enabled", True)),
        "declaration_key": "%s%s:digest" % (DECL_PREFIX, agent),
        "workspace": ws,
    }


def run_oc(oc_cmd, args):
    """Запуск openclaw CLI; (returncode, stdout, stderr)."""
    try:
        r = subprocess.run([oc_cmd] + list(args), capture_output=True, timeout=60)
        return (r.returncode, r.stdout.decode("utf-8", "replace"),
                r.stderr.decode("utf-8", "replace"))
    except (OSError, subprocess.TimeoutExpired) as exc:
        return (99, "", str(exc))


def list_jobs(oc_cmd):
    """Текущие automations: {name: job}; None — CLI недоступен."""
    rc, out, _err = run_oc(oc_cmd, ["automations", "list", "--json"])
    if rc != 0:
        return None
    try:
        data = json.loads(out)
    except ValueError:
        return None
    jobs = {}
    for job in (data.get("jobs") or []):
        name = job.get("name")
        if name:
            jobs[name] = job
    return jobs


def add_flags(spec):
    """Флаги automations add/edit из спека."""
    flags = ["--cron", spec["schedule"], "--name", spec["name"],
             "--display-name", spec["display_name"], "--agent", spec["agent"],
             "--command", spec["command"], "--announce",
             "--channel", spec["channel"], "--to", spec["to"],
             "--best-effort-deliver", "--timeout-seconds", "300"]
    if spec["tz"]:
        flags += ["--tz", spec["tz"]]
    if spec["account"]:
        flags += ["--account", spec["account"]]
    return flags


def add_job(oc_cmd, spec):
    rc, out, err = run_oc(oc_cmd, ["automations", "add"] + add_flags(spec) +
                          ["--declaration-key", spec["declaration_key"]] +
                          (["--disabled"] if not spec["enabled"] else []))
    return rc, out, err


def edit_job(oc_cmd, job, spec):
    """Patch-выравнивание automation; enable/disable по enabled."""
    rc, out, err = run_oc(oc_cmd, ["automations", "edit", job["id"]] +
                          add_flags(spec))
    if rc != 0:
        return rc, out, err
    was_enabled = bool(job.get("enabled", True))
    if spec["enabled"] and not was_enabled:
        rc, out, err = run_oc(oc_cmd, ["automations", "enable", job["id"]])
    elif not spec["enabled"] and was_enabled:
        rc, out, err = run_oc(oc_cmd, ["automations", "disable", job["id"]])
    return rc, out, err


def sync(oc_cmd, agents_dir, apply=False, prune=False):
    """diff (по умолчанию) или apply. Возвращает код выхода."""
    docs, errors = load_factory_docs(agents_dir)
    for msg in errors:
        print("Анкета: %s" % msg)
    specs = []
    for _fname, doc in docs:
        spec = digest_spec(doc)
        if spec:
            specs.append(spec)
        elif doc.get("reports"):
            print("[%s] reports заданы, но schedule дайджеста пуст — пропуск"
                  % doc.get("id"))
    if not specs:
        print("Анкет с настроенным reports.digest нет — нечего синхронизировать")
        return 0

    jobs = list_jobs(oc_cmd)
    if jobs is None:
        print("ОШИБКА: openclaw automations list недоступен (gateway/CLI)")
        return 1

    changes = 0
    wanted = set()
    for spec in specs:
        wanted.add(spec["name"])
        job = jobs.get(spec["name"])
        if job is None:
            print("СОЗДАТЬ: %s (агент %s, cron %s, → %s@%s:%s)"
                  % (spec["name"], spec["agent"], spec["schedule"],
                     spec["channel"], spec["account"], spec["to"]))
            changes += 1
            if apply:
                rc, out, err = add_job(oc_cmd, spec)
                if rc != 0:
                    print("  ОШИБКА add: %s" % (err or out)[:300])
                    return 1
                print("  ok")
            continue
        enabled_ok = bool(job.get("enabled", True)) == spec["enabled"]
        if enabled_ok:
            print("ЕСТЬ: %s (id %s, enabled=%s)"
                  % (spec["name"], job["id"][:8], job.get("enabled")))
        else:
            print("ВЫРОВНЯТЬ: %s (enabled=%s → %s)"
                  % (spec["name"], job.get("enabled"), spec["enabled"]))
            changes += 1
            if apply:
                rc, out, err = edit_job(oc_cmd, job, spec)
                if rc != 0:
                    print("  ОШИБКА edit: %s" % (err or out)[:300])
                    return 1
                print("  ok")

    extra = [n for n in jobs if n.startswith(JOB_PREFIX) and n not in wanted]
    for name in sorted(extra):
        if prune:
            print("УДАЛИТЬ: %s (нет в анкетах, --prune)" % name)
            changes += 1
            if apply:
                rc, out, err = run_oc(oc_cmd, ["automations", "rm", jobs[name]["id"]])
                if rc != 0:
                    print("  ОШИБКА rm: %s" % (err or out)[:300])
                    return 1
                print("  ok")
        else:
            print("ЛИШНИЙ: %s (нет в анкетах; удалить: --apply --prune)" % name)

    if not apply and changes:
        print("\nИзменений: %d — применить: oc-reports.py --apply" % changes)
    elif not changes:
        print("\nДрейфов нет")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog="oc-reports",
                                 description="Синхронизация automation-дайджестов (E6)")
    ap.add_argument("--agents-dir", default=os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "agents"),
        help="каталог анкет")
    ap.add_argument("--apply", action="store_true", help="применить изменения")
    ap.add_argument("--diff", action="store_true",
                    help="только показать изменения (по умолчанию)")
    ap.add_argument("--prune", action="store_true",
                    help="удалить лишние factory-digest-* (только с --apply)")
    ap.add_argument("--oc-cmd", default="openclaw", help="команда openclaw")
    args = ap.parse_args(argv)
    return sync(args.oc_cmd, args.agents_dir, apply=args.apply,
                prune=args.prune)


if __name__ == "__main__":
    sys.exit(main())