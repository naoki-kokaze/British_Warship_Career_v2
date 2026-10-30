"""v1 RDF（LLM 生成）の状態と、規則v1 の Presence（presences.csv）を、艦ごと・月ごとに比べる（状態の層の照合）

方針（2026-10-07 ユーザー承認。対応表 §11）
    - 月ごとに、その月に重なる Presence の状態の集合を v1・v2 それぞれで作り、任務上の地位の軸と工事の軸を別々に比べる。
      v1 は1軸なので、:UnderRepair・:UnderFitting を工事の軸、それ以外を任務上の地位の軸とみなす
    - Presence の期間：始まりの月から終わりの月まで（両端を含む。移り変わりの月は両方の状態を持つ）。
      年までの日付は、始まりなら1月、終わりなら12月。
    - 比べるための補い（記録の層は変えない）：終わりがない・終わりが始まりより前の Presence は、同じ軸の次の Presence の
      始まりの前の月まで延ばす。次がなければ、その艦の最後の日付つきの出来事の月まで。v1・v2 の両方に同じ扱いをする。
      工事の軸は延ばさない（始まりの月だけ）
    - v1 の期間の読み方：時間ノードの P79/P80/P82 の日付、なければ P182i の出来事の終わり・P182 の出来事の始まり。
      v1 は Presence から艦へ P195i を逆向きに付けている（精査報告 §2 A）ので、その向きで読む
    - 月ごとの判定（地位の軸）：
        same       集合が同じ
        overlap    共通の状態がある（移り変わりの月など）
        differ     共通の状態がない
        v1_none / v2_none  片方にその月の状態がない
    - 判定が同じ月の続きを「区間」にまとめ、裁定（第3段階）の抽出に使う

入力（読み取りのみ）: ../sources/v1/ship_careers_combined.ttl、../outputs/rules_v1/presences.csv
出力: ../outputs/rules_v1/v1_vs_v2_states_runs.csv（区間）・v1_vs_v2_states_summary.json
依存: rdflib（サンドボックスの外で実行）
"""
import collections
import csv
import json
import logging
import os
import re

from rdflib import Graph, Namespace
from rdflib.namespace import RDF

logging.getLogger("rdflib").setLevel(logging.ERROR)
HERE = os.path.dirname(os.path.abspath(__file__))
TTL = os.path.join(HERE, "../sources/v1/ship_careers_combined.ttl")
PRESENCES = os.path.join(HERE, "../outputs/rules_v1/presences.csv")
EVENTS = os.path.join(HERE, "../outputs/rules_v1/events.csv")
OUT = os.path.join(HERE, "../outputs/rules_v1")
CRM = Namespace("http://www.cidoc-crm.org/cidoc-crm/")
W = Namespace("http://www.example.com/ontology/warship#")
WORK = {"UnderRepair", "UnderFitting", "UnderRepairAndFitting"}


def month(d, end=False):
    """'1864-07-07' / '1864-07' / '1864' → 月の通し番号（年*12+月-1）"""
    m = re.match(r"(\d{4})(?:-(\d{2}))?", str(d or ""))
    if not m:
        return None
    y = int(m.group(1))
    mo = int(m.group(2)) if m.group(2) else (12 if end else 1)
    return y * 12 + mo - 1


def label(mi):
    return f"{mi // 12:04d}-{mi % 12 + 1:02d}"


def event_dates(g, ev):
    ts = g.value(ev, CRM["P4_has_time-span"])
    if ts is None:
        return None, None
    p82 = g.value(ts, CRM.P82_at_some_time_within)
    b = g.value(ts, CRM.P79_beginning_is_qualified_by) or p82
    e = g.value(ts, CRM.P80_end_is_qualified_by) or p82
    return b, e


def load_v1():
    g = Graph().parse(TTL, format="turtle")
    out = collections.defaultdict(list)
    last = {}
    for ev in g.subjects(CRM["P4_has_time-span"], None):
        m = re.search(r"event_([A-Z0-9]+_\d{4})_", str(ev))
        if m:
            b, e = event_dates(g, ev)
            mo = month(e or b, end=True)
            if mo is not None:
                last[m.group(1)] = max(last.get(m.group(1), mo), mo)
    for p in g.subjects(RDF.type, CRM.E93_Presence):
        ship = g.value(p, CRM.P195i_had_presence)
        st = g.value(p, W.has_operational_status)
        ts = g.value(p, CRM.P164_is_temporally_specified_by)
        if ship is None or st is None or ts is None:
            continue
        p82 = g.value(ts, CRM.P82_at_some_time_within)
        b = g.value(ts, CRM.P79_beginning_is_qualified_by) or p82
        e = g.value(ts, CRM.P80_end_is_qualified_by) or p82
        if b is None:
            sev = g.value(ts, CRM.P182i_starts_after_or_with_the_end_of)
            if sev is not None:
                b = event_dates(g, sev)[1] or event_dates(g, sev)[0]
        if e is None:
            eev = g.value(ts, CRM.P182_ends_before_or_with_the_start_of)
            if eev is not None:
                e = event_dates(g, eev)[0] or event_dates(g, eev)[1]
        if b is None and (ts, RDF.type, CRM["E52_Time-Span"]) not in g:   # P164 が出来事を指している例外（4件）
            b, e = event_dates(g, ts)
        status = str(st).split("#")[-1]
        out[str(ship).split("/")[-1]].append({"id": str(p).split("/")[-1], "status": status,
                                              "axis": "work" if status in WORK else "service",
                                              "begin": month(b), "end": month(e, end=True)})
    return out, last


def load_v2():
    out = collections.defaultdict(list)
    last = {}
    for ev in csv.DictReader(open(EVENTS, encoding="utf-8-sig")):
        mo = month(ev["end"] or ev["begin"], end=True)
        if mo is not None:
            last[ev["ship"]] = max(last.get(ev["ship"], mo), mo)
    for p in csv.DictReader(open(PRESENCES, encoding="utf-8-sig")):
        out[p["ship"]].append({"id": p["id"], "status": p["status"], "axis": p["axis"],
                               "begin": month(p["begin"]), "end": month(p["end"], end=True)})
    return out, last


def months_of(presences, axis, last_month):
    """{月: {状態}}。終わりがない・逆転している Presence は、次の Presence の前の月（なければ last_month）まで"""
    out = collections.defaultdict(set)
    open_ended = inverted = 0
    ps = sorted((p for p in presences if p["axis"] == axis and p["begin"] is not None), key=lambda p: p["begin"])
    for i, p in enumerate(ps):
        end = p["end"]
        if end is None or end < p["begin"]:
            if end is None:
                open_ended += 1
            else:
                inverted += 1
            if axis == "work":   # 工事は原文に期間がある。延ばさず始まりの月だけ
                end = p["begin"]
            else:
                nxt = [q["begin"] for q in ps[i + 1:] if q["begin"] > p["begin"]]
                end = max(p["begin"], (nxt[0] - 1) if nxt else (last_month or p["begin"]))
        for m in range(p["begin"], end + 1):
            out[m].add(p["status"])
    return out, open_ended, inverted


def judge(a, b):
    if not a and not b:
        return None
    if not a:
        return "v1_none"
    if not b:
        return "v2_none"
    if a == b:
        return "same"
    return "overlap" if a & b else "differ"


def main():
    (v1, last1), (v2, last2) = load_v1(), load_v2()
    runs, summary = [], {"ships_v1": len(v1), "ships_v2": len(v2)}
    for axis in ("service", "work"):
        months = collections.Counter()
        confusion = collections.Counter()
        notes = collections.Counter()
        for ship in sorted(set(v1) | set(v2)):
            a, oa, ia = months_of(v1.get(ship, []), axis, last1.get(ship))
            b, ob, ib = months_of(v2.get(ship, []), axis, last2.get(ship))
            notes.update({"v1_open_ended": oa, "v1_inverted": ia, "v2_open_ended": ob, "v2_inverted": ib})
            cur = None
            for m in sorted(set(a) | set(b)):
                j = judge(a.get(m, set()), b.get(m, set()))
                months[j] += 1
                if len(a.get(m, ())) == 1 and len(b.get(m, ())) == 1:
                    confusion[(next(iter(a[m])), next(iter(b[m])))] += 1
                key = (j, "+".join(sorted(a.get(m, ()))), "+".join(sorted(b.get(m, ()))))
                if cur and cur["key"] == key and cur["to_m"] == m - 1:
                    cur["to_m"] = m
                else:
                    cur = {"key": key, "from_m": m, "to_m": m, "ship": ship}
                    runs.append(cur)
            for r in runs:
                r.setdefault("axis", axis)
        total = sum(months.values())
        summary[axis] = {
            "ship_months": total,
            "results": {k: {"months": v, "share": round(v / total, 3)} for k, v in months.most_common()},
            "confusion_single_status_v1_by_v2": {f"{x} | {y}": n for (x, y), n in confusion.most_common()},
            "notes": dict(notes),
        }

    fields = ["ship", "axis", "result", "from", "to", "months", "v1_status", "v2_status"]
    with open(os.path.join(OUT, "v1_vs_v2_states_runs.csv"), "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in runs:
            j, sa, sb = r["key"]
            w.writerow({"ship": r["ship"], "axis": r["axis"], "result": j, "from": label(r["from_m"]),
                        "to": label(r["to_m"]), "months": r["to_m"] - r["from_m"] + 1, "v1_status": sa, "v2_status": sb})
    json.dump(summary, open(os.path.join(OUT, "v1_vs_v2_states_summary.json"), "w"), ensure_ascii=False, indent=2)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
