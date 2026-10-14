#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Генератор графа знаний из строк `Связи[ИСТОЧНИК]: тип=цель …` в docs/.

Пишет docs/Граф-знаний.md (Mermaid + плоский список для grep). Конвенция и словарь типов —
docs/СВЯЗИ-конвенция.md. Только stdlib. Запуск: python scripts/gen-knowledge-graph.py
Ожидает размещение в <repo>/scripts/ (docs/ ищется как ../docs относительно этого файла).
"""
import re
import sys
from pathlib import Path

# Принудительный UTF-8 вывод — иначе кириллица в print() падает под cp1252
# (например, когда скрипт вызывает git-хук вне окружения с PYTHONIOENCODING). НЕ УДАЛЯТЬ.
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
OUT = DOCS / "Граф-знаний.md"
SKIP = {OUT.name, "СВЯЗИ-конвенция.md"}  # сам граф и конвенцию не парсим

# ─────────────────────────── CUSTOMIZE (под проект) ───────────────────────────
# Маркер-слово инлайн-строки связей. По умолчанию кириллическое «Связи»; можно заменить
# (напр. "Links") — тогда правь и примеры в СВЯЗИ-конвенция.md.
MARKER = "Связи"

# Закрытый словарь типов рёбер (канонические). Инверсные формы разворачиваются в INVERSE.
KNOWN = {"supersedes", "implements", "closes", "reopens", "blocks",
         "causes", "recurs", "relates", "depends-on"}
SYMMETRIC = {"relates"}  # у симметричных рёбер направление нормализуется (сортировкой)
INVERSE = {
    "superseded-by": "supersedes", "implemented-by": "implements",
    "closed-by": "closes", "blocked-by": "blocks",
    "caused-by": "causes", "depended-on-by": "depends-on",
}

# Классы узлов для раскраски Mermaid — по префиксу ID. Подстрой под свою схему ID
# (ниже: ADR-<n>, инцидент §<n.n>, долги OPF/NP/PS/SC/HL-<n>, спринт С<n>, требование ТЗ…).
def node_class(nid):
    if re.match(r"ADR-\d+", nid):                  return "adr"
    if re.match(r"§\d+\.\d+", nid):                return "incident"
    if re.match(r"(OPF|NP|PS|SC|HL)-\d+", nid):    return "debt"
    if re.match(r"С\d", nid):                      return "sprint"   # кириллическая С
    if nid.startswith("ТЗ"):                       return "req"
    return "concept"
# ───────────────────────────────────────────────────────────────────────────────

LINE_RE = re.compile(re.escape(MARKER) + r"\[(?P<src>[^\]]+)\]:\s*(?P<body>.+)$")


def norm_id(s):
    s = s.strip()
    if re.fullmatch(r"\d+\.\d+", s):   # голый N.N -> §N.N (инцидент/раздел Грабли)
        s = "§" + s
    return s


def parse():
    edges, warns = set(), []
    for p in sorted(DOCS.rglob("*.md")):
        if p.name in SKIP:
            continue
        for ln, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            m = LINE_RE.search(line)
            if not m:
                continue
            src = norm_id(m.group("src"))
            for clause in re.split(r"[·;]", m.group("body")):
                clause = clause.strip()
                if not clause:
                    continue
                if "=" not in clause:
                    warns.append(f"{p.name}:{ln} нет '=': {clause!r}"); continue
                typ, tgts = clause.split("=", 1)
                typ = typ.strip()
                swap = typ in INVERSE
                t = INVERSE.get(typ, typ)
                if t not in KNOWN:
                    warns.append(f"{p.name}:{ln} неизвестный тип: {typ!r}"); continue
                for tgt in tgts.split(","):
                    tgt = norm_id(tgt)
                    if not tgt:
                        continue
                    a, b = (tgt, src) if swap else (src, tgt)
                    if t in SYMMETRIC:
                        a, b = sorted([a, b])
                    edges.add((a, t, b))
    return sorted(edges), warns


def render(edges):
    nodes, order = {}, []
    def nid(x):
        if x not in nodes:
            nodes[x] = f"n{len(nodes)}"; order.append(x)
        return nodes[x]
    for a, _, b in edges:
        nid(a); nid(b)
    out = ["```mermaid", "graph LR"]
    for real in order:
        out.append(f'  {nodes[real]}["{real}"]:::{node_class(real)}')
    for a, t, b in edges:
        out.append(f"  {nodes[a]} -->|{t}| {nodes[b]}")
    out += [
        "  classDef adr fill:#E7EEF7,stroke:#3A63E0,color:#16233B;",
        "  classDef incident fill:#FBECEC,stroke:#D64550,color:#16233B;",
        "  classDef debt fill:#FCF3E2,stroke:#C77F0A,color:#16233B;",
        "  classDef sprint fill:#E4F5EC,stroke:#078A5A,color:#16233B;",
        "  classDef req fill:#EDE7F7,stroke:#6A4FCF,color:#16233B;",
        "  classDef concept fill:#EEF2F9,stroke:#6E7E98,color:#16233B;",
        "```",
    ]
    return "\n".join(out), len(order)


def main():
    edges, warns = parse()
    mermaid, n_nodes = render(edges)
    tbl = "\n".join(f"- {a} —{t}→ {b}" for a, t, b in edges) or "_(связей пока нет)_"
    text = (
        "# Граф знаний — типизированные связи (АВТОГЕН)\n\n"
        "> **Не править вручную.** Генерируется из строк `Связи[…]` в `docs/` по конвенции\n"
        "> [`СВЯЗИ-конвенция.md`](СВЯЗИ-конвенция.md). Перегенерировать: `python scripts/gen-knowledge-graph.py`.\n\n"
        f"{mermaid}\n\n## Список связей (для grep)\n\n{tbl}\n"
    )
    if "--check" in sys.argv:
        current = OUT.read_text(encoding="utf-8") if OUT.exists() else ""
        if current != text:
            print("STALE: docs/Граф-знаний.md не соответствует рёбрам → python scripts/gen-knowledge-graph.py")
            for w in warns:
                print("WARN:", w)
            sys.exit(1)
        print(f"OK (--check): граф актуален, {len(edges)} рёбер")
    else:
        OUT.write_text(text, encoding="utf-8", newline="\n")  # LF всегда → идемпотентно в git
        print(f"OK: {len(edges)} рёбер, {n_nodes} узлов → docs/{OUT.name}")
    for w in warns:
        print("WARN:", w)


if __name__ == "__main__":
    main()