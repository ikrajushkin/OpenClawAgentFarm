#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""oc-project-digest — дайджест проектов агента (OPF-9/T8, E6).

Собирает по workspace агента (projects.yaml + деревья проектов):
  результаты — файлы проектов, изменённые за период (+ RESULT:-записи журналов);
  проблемы   — PROBLEM:-записи журналов + failed/lost фоновые задачи;
  фон        — задачи/automations с тегом проекта `proj-<id>` (openclaw tasks list);
  ресурсы    — openclaw gateway usage-cost (per agent, дни/токены/стоимость);
  бюджеты    — budgetUsdPerDay из projects.yaml vs факт за день (soft, без стопа).

Вывод — Markdown в stdout (для automation `--announce` в канал владельца),
опционально копия в <workspace>/logs/digests/. Дайджест печатается всегда
(«пустой» отчёт — тоже отчёт).

Запуск вручную:
  python3 oc-project-digest.py --workspace /srv/shared/Projects/Service --days 1
"""
import argparse
import json
import os
import subprocess
import sys
import time

MARK_RESULT = "RESULT:"
MARK_PROBLEM = "PROBLEM:"
LOG_TAIL_MAX = 12          # сколько маркированных записей на проект
FILE_LIST_MAX = 10         # сколько файлов показывать на проект


def json_str(val):
    """Раскрыть JSON-строку в кавычках (title/description рендерятся json.dumps)."""
    try:
        return json.loads(val)
    except (ValueError, TypeError):
        return val.strip('"')


def read_projects_yaml(path):
    """Мини-парсер projects.yaml (формат генерит oc-agent-factory, ADR-006).

    Возвращает (agent_id, workspace, [project_dict...]) — без внешних библиотек.
    """
    agent, workspace = "", ""
    projects, cur = [], None
    with open(path, encoding="utf-8") as fh:
        for raw in fh:
            s = raw.strip()
            if not s or s.startswith("#"):
                continue
            if s.startswith("agent:"):
                agent = s.split(":", 1)[1].strip()
            elif s.startswith("workspace:"):
                workspace = s.split(":", 1)[1].strip()
            elif s.startswith("- id:"):
                if cur:
                    projects.append(cur)
                cur = {"id": s.split(":", 1)[1].strip()}
            elif cur and s.startswith("title:"):
                cur["title"] = json_str(s.split(":", 1)[1].strip())
            elif cur and s.startswith("dir:"):
                cur["dir"] = s.split(":", 1)[1].strip()
            elif cur and s.startswith("description:"):
                cur["description"] = json_str(s.split(":", 1)[1].strip())
            elif cur and s.startswith("budgetUsdPerDay:"):
                try:
                    cur["budgetUsdPerDay"] = float(s.split(":", 1)[1].strip())
                except ValueError:
                    pass
    if cur:
        projects.append(cur)
    return agent, workspace, projects


def run_json(cmd, timeout=60):
    """Запустить CLI и распарсить JSON; None — ошибка (нет CLI/сервера)."""
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=timeout)
        if r.returncode != 0:
            return None
        return json.loads(r.stdout.decode("utf-8", "replace"))
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return None


def collect_files(proj_dir, since_ts):
    """Файлы проекта, изменённые с since_ts: (changed, log_records)."""
    changed, log_records = [], []
    for root, _dirs, files in os.walk(proj_dir):
        for fname in files:
            fpath = os.path.join(root, fname)
            try:
                mtime = os.path.getmtime(fpath)
            except OSError:
                continue
            if mtime < since_ts:
                continue
            rel = os.path.relpath(fpath, proj_dir)
            changed.append((mtime, rel))
            if rel.startswith("logs"):
                try:
                    with open(fpath, encoding="utf-8") as fh:
                        for line in fh:
                            s = line.strip()
                            if s.startswith(MARK_RESULT):
                                log_records.append((MARK_RESULT, rel, s))
                            elif s.startswith(MARK_PROBLEM):
                                log_records.append((MARK_PROBLEM, rel, s))
                except (OSError, UnicodeDecodeError):
                    pass
    changed.sort(reverse=True)
    log_records.sort(key=lambda t: t[0], reverse=True)
    return changed, log_records


def collect_tasks(oc_cmd, agent_id, since_ts):
    """Фоновые задачи агента с тегами проектов (proj-<id> в name/label/runId)."""
    data = run_json([oc_cmd, "tasks", "list", "--json"])
    if not data:
        return None
    rows = []
    for task in (data.get("tasks") or []):
        created = (task.get("createdAt") or 0) / 1000.0
        if since_ts and created < since_ts:
            continue
        if agent_id and task.get("agentId") and task.get("agentId") != agent_id:
            continue
        hay = " ".join(str(task.get(k) or "") for k in ("label", "task", "runId"))
        rows.append({"status": task.get("status"),
                     "label": task.get("label") or task.get("task") or task.get("taskId"),
                     "hay": hay, "when": created})
    return rows


def collect_usage(oc_cmd, agent_id, days):
    """usage-cost агента: (daily_list, total_cost)."""
    args = [oc_cmd, "gateway", "usage-cost", "--days", str(days), "--json"]
    if agent_id:
        args += ["--agent", agent_id]
    data = run_json(args, timeout=90)
    if not data:
        return None, None
    daily = data.get("daily") or []
    total = sum(float(d.get("totalCost") or 0) for d in daily)
    return daily, total


def project_tasks(rows, proj_id):
    """Задачи с тегом proj-<id>."""
    tag = "proj-%s" % proj_id
    return [r for r in (rows or []) if tag in r["hay"]]


def md_escape(text):
    return (text or "").replace("|", "\\|").replace("\n", " ")


def build_digest(ws, agent_id, projects, days, tasks_rows, usage_daily,
                 usage_total, now):
    since_ts = now - days * 86400
    out = ["# Дайджест проектов %s — %s (за %d дн.)"
           % (agent_id, time.strftime("%Y-%m-%d %H:%M"), days), ""]
    budget_total = 0.0

    out.append("## Результаты")
    any_result = False
    for p in projects:
        pdir = os.path.join(ws, p["dir"])
        changed, log_records = collect_files(pdir, since_ts)
        results = [r for r in log_records if r[0] == MARK_RESULT]
        if not changed and not results:
            continue
        any_result = True
        out.append("### %s (`%s`)" % (p.get("title") or p["id"], p["id"]))
        for _mtime, rel in changed[:FILE_LIST_MAX]:
            out.append("- файл: `%s`" % rel.replace(os.sep, "/"))
        if len(changed) > FILE_LIST_MAX:
            out.append("- … ещё %d файл(ов)" % (len(changed) - FILE_LIST_MAX))
        for _mark, rel, line in results[:LOG_TAIL_MAX]:
            out.append("- %s" % md_escape(line[:300]))
    if not any_result:
        out.append("- изменений за период нет")
    out.append("")

    out.append("## Проблемы")
    any_problem = False
    for p in projects:
        pdir = os.path.join(ws, p["dir"])
        _changed, log_records = collect_files(pdir, since_ts)
        problems = [r for r in log_records if r[0] == MARK_PROBLEM]
        failed = [t for t in project_tasks(tasks_rows, p["id"])
                  if t["status"] in ("failed", "timed_out", "lost")]
        if not problems and not failed:
            continue
        any_problem = True
        out.append("### %s (`%s`)" % (p.get("title") or p["id"], p["id"]))
        for _mark, rel, line in problems[:LOG_TAIL_MAX]:
            out.append("- %s" % md_escape(line[:300]))
        for t in failed[:FILE_LIST_MAX]:
            out.append("- задача [%s] %s"
                       % (t["status"], md_escape(str(t["label"])[:120])))
    if not any_problem:
        out.append("- проблем не зафиксировано")
    out.append("")

    out.append("## Фоновые задачи")
    any_task = False
    for p in projects:
        rows = project_tasks(tasks_rows, p["id"])
        if not rows:
            continue
        any_task = True
        out.append("### %s (`%s`): %d задач(и)"
                   % (p.get("title") or p["id"], p["id"], len(rows)))
        for t in rows[:FILE_LIST_MAX]:
            out.append("- [%s] %s" % (t["status"], md_escape(str(t["label"])[:120])))
    if tasks_rows is None:
        out.append("- список задач недоступен (openclaw tasks)")
    elif not any_task:
        out.append("- задач с тегами `proj-<id>` за период нет")
    out.append("")

    out.append("## Ресурсы и бюджеты")
    if usage_daily is None:
        out.append("- usage-cost недоступен")
    else:
        out.append("- агент `%s`: $%.4f за %d дн. (токены: %s)"
                   % (agent_id, usage_total or 0, days,
                      "{:,}".format(sum(int(d.get("totalTokens") or 0)
                                        for d in usage_daily)).replace(",", " ")))
        last = [d for d in usage_daily if (d.get("totalCost") or 0) > 0]
        if last:
            d = last[-1]
            out.append("- последний день с расходом %s: $%.4f"
                       % (d.get("date"), float(d.get("totalCost") or 0)))
    for p in projects:
        if p.get("budgetUsdPerDay") is not None:
            budget_total += float(p["budgetUsdPerDay"])
    if budget_total > 0:
        over = (usage_total or 0) / max(days, 1) > budget_total
        note = ("⚠ расход за день выше суммарного бюджета проектов ($%.2f)"
                % budget_total) if over else ("расхода нет" if not usage_total
                                              else "в пределах бюджета")
        out.append("- бюджеты проектов: $%.2f/день (soft, без стопа) — %s"
                   % (budget_total, note))
    else:
        out.append("- бюджеты проектов не заданы")
    out.append("")
    return "\n".join(out)


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(prog="oc-project-digest",
                                 description="Дайджест проектов агента (E6/T8)")
    ap.add_argument("--workspace", default=None,
                    help="workspace агента (default: workspace из projects.yaml)")
    ap.add_argument("--projects-yaml", default=None,
                    help="путь к projects.yaml (default: <workspace>/projects.yaml)")
    ap.add_argument("--agent", default=None,
                    help="id агента (default: agent из projects.yaml)")
    ap.add_argument("--days", type=int, default=1, help="период в днях (default: 1)")
    ap.add_argument("--save", action="store_true",
                    help="сохранить копию в <workspace>/logs/digests/")
    ap.add_argument("--oc-cmd", default="openclaw", help="команда openclaw")
    args = ap.parse_args(argv)

    ws = args.workspace
    py_path = args.projects_yaml or (os.path.join(ws, "projects.yaml")
                                     if ws else None)
    if not py_path or not os.path.exists(py_path):
        sys.exit("НЕТ projects.yaml: %s" % py_path)
    agent_yaml, ws_yaml, projects = read_projects_yaml(py_path)
    ws = ws or ws_yaml or os.path.dirname(py_path)
    agent_id = args.agent or agent_yaml
    if not projects:
        sys.exit("projects.yaml: реестр проектов пуст")

    now = time.time()
    tasks_rows = collect_tasks(args.oc_cmd, agent_id, now - args.days * 86400)
    usage_daily, usage_total = collect_usage(args.oc_cmd, agent_id, args.days)
    text = build_digest(ws, agent_id, projects, args.days, tasks_rows,
                        usage_daily, usage_total, now)

    if args.save:
        ddir = os.path.join(ws, "logs", "digests")
        os.makedirs(ddir, exist_ok=True)
        path = os.path.join(ddir, "digest-%s.md" % time.strftime("%Y%m%d-%H%M%S"))
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text + "\n")
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())