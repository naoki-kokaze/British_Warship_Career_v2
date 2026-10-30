"""規則v0で取り出した定型部分の事実と、v1 RDF（LLM生成）の建造イベントを突き合わせる

分類：match（一致）、match_sum_of_components（v1が内訳の合計を記録）、match_partial_sum（内訳の一部の和と一致）、v1_P80_is_completion（v1が建造の終点に竣工日を記録）、
same_year_differs（同じ年で日付が違う）、mismatch、v1_missing、rule_missing、both_missing

v1の生成プロンプトでは、建造（crm:E12_Production）の始点 P79（または P82）に発注日か起工日、
終点 P80 に進水日を入れ、建造費を :incurred_cost（crm:P90_has_value）として付けることになっていた。

入力（読み取りのみ）:
    ../sources/v1/ship_careers_combined.ttl
    ../outputs/rules_v0/header_facts.csv（extract_header_v0.py の出力）
出力:
    ../outputs/rules_v0/v1_vs_header.csv   艦ごと・項目ごとの照合結果
    ../outputs/rules_v0/v1_vs_header_summary.json

依存: rdflib
"""
import collections
import csv
import itertools
import json
import logging
import os
import re

from rdflib import Graph, Namespace
from rdflib.namespace import RDF

logging.getLogger("rdflib").setLevel(logging.ERROR)

HERE = os.path.dirname(os.path.abspath(__file__))
TTL = os.path.join(HERE, "../sources/v1/ship_careers_combined.ttl")
FACTS = os.path.join(HERE, "../outputs/rules_v0/header_facts.csv")
OUT = os.path.join(HERE, "../outputs/rules_v0")
CRM = Namespace("http://www.cidoc-crm.org/cidoc-crm/")
W = Namespace("http://www.example.com/ontology/warship#")


def compare(rule_val, rule_prec, v1_val):
    """規則側の精度（日・月・年）に合わせて、v1の値の先頭を比べる"""
    if not rule_val:
        return "rule_missing" if v1_val else "both_missing"
    if not v1_val:
        return "v1_missing"
    n = {"day": 10, "month": 7, "year": 4}.get(rule_prec, 10)
    if v1_val[:n] == rule_val[:n]:
        return "match" if len(v1_val) >= n else "match_coarser"
    if v1_val[:4] == rule_val[:4]:
        return "same_year_differs"
    return "mismatch"


def main():
    g = Graph()
    g.parse(TTL, format="turtle")
    v1 = {}
    for ev in g.subjects(RDF.type, CRM.E12_Production):
        m = re.search(r"event_([A-Z][A-Z0-9]*_\d{4})_", str(ev))
        if not m:
            continue
        sid = m.group(1)
        ts = next(g.objects(ev, CRM["P4_has_time-span"]), None)
        get = lambda p: str(next(g.objects(ts, p), "")) if ts is not None else ""
        costs = [float(v) for c in g.objects(ev, W.incurred_cost) for v in g.objects(c, CRM.P90_has_value)
                 if re.fullmatch(r"[\d.]+", str(v))]
        # 1隻に複数の E12 がある場合は、最初のもの（番号が最小のもの）を採る
        if sid not in v1 or str(ev) < v1[sid]["event"]:
            v1[sid] = {"event": str(ev), "P79": get(CRM.P79_beginning_is_qualified_by), "P80": get(CRM.P80_end_is_qualified_by),
                       "P82": get(CRM.P82_at_some_time_within), "costs": costs}

    facts = collections.defaultdict(dict)
    costs = collections.defaultdict(list)
    completion = collections.defaultdict(set)   # 竣工の始点・終点（v1 の P80 が竣工日を指していないかの確認用）
    for r in csv.DictReader(open(FACTS, encoding="utf-8-sig")):
        if r["field"] == "COMPLETED" and r["begin"]:
            completion[r["ship"]].update({r["begin"], r["end"]})
        if r["field"] == "FIRST_COST":
            if r["amount_gbp"]:
                costs[r["ship"]].append((float(r["amount_gbp"]), r["cost_kind"]))
        elif r["status"] in ("parsed", "partial") and r["field"] not in facts[r["ship"]]:
            facts[r["ship"]][r["field"]] = (r["begin"], r["begin_precision"])

    ships = sorted(set(facts) | set(costs) | set(v1))
    rows, tally = [], collections.defaultdict(collections.Counter)
    for sid in ships:
        f, e = facts.get(sid, {}), v1.get(sid)
        if e is None:
            rows.append([sid, "E12", "", "", "", "v1_no_production_event"])
            tally["E12_present"]["no"] += 1
            continue
        tally["E12_present"]["yes"] += 1
        # 進水日 ↔ P80
        lv, lp = f.get("LAUNCHED", ("", ""))
        res = compare(lv, lp, e["P80"])
        if res in ("mismatch", "same_year_differs") and e["P80"] and any(
                c[:len(e["P80"])] == e["P80"] or e["P80"][:len(c)] == c for c in completion.get(sid, ())):
            res = "v1_P80_is_completion"   # v1 が建造の終点に竣工日を入れている
        rows.append([sid, "LAUNCHED↔P80", lv, e["P80"], lp, res])
        tally["LAUNCHED↔P80"][res] += 1
        # 建造の始点 ↔ P79（なければ P82）：発注日と起工日のどちらかに一致すればよい
        start = e["P79"] or e["P82"]
        cands = [(k, *f[k]) for k in ("ORDERED", "KEEL_LAID") if k in f]
        best = "rule_missing" if not cands else "mismatch"
        which = ""
        for k, val, prec in cands:
            r = compare(val, prec, start)
            if r in ("match", "match_coarser"):
                best, which = r, k
                break
            if r == "same_year_differs" and best == "mismatch":
                best, which = r, k
        if cands and not start:
            best = "v1_missing"
        rows.append([sid, "ORD/KEEL↔P79", " / ".join(f"{k}={v}" for k, v, _ in cands), start, which, best])
        tally["ORD/KEEL↔P79"][best] += 1
        # 建造費：規則側のどれか1つの金額が v1 の金額のどれかと一致するか（1ポンド未満の差は一致とみなす）
        rc, vc = costs.get(sid, []), e["costs"]
        if not rc and not vc:
            cres = "both_missing"
        elif not vc:
            cres = "v1_missing"
        elif not rc:
            cres = "rule_missing"
        else:
            parts = [a for a, k in rc if k != "TOTAL"]
            if any(abs(a - b) < 1 for a, _ in rc for b in vc):
                cres = "match"
            elif parts and any(abs(sum(parts) - b) < len(parts) for b in vc):   # 内訳ごとのシリング・ペンスの切り捨てを許す
                cres = "match_sum_of_components"   # v1 が原文の内訳を足し合わせた値を記録している
            elif any(abs(sum(c) - b) < 1 for n in range(2, len(rc) + 1)
                     for c in itertools.combinations([a for a, _ in rc], n) for b in vc):
                cres = "match_partial_sum"         # 内訳の一部の和と一致（入れ子の内訳など。人の確認が要る）
            else:
                cres = "mismatch"
        rows.append([sid, "FIRST_COST↔incurred_cost", "; ".join(f"{k}:{a:g}" for a, k in rc), "; ".join(f"{b:g}" for b in vc), "", cres])
        tally["FIRST_COST↔incurred_cost"][cres] += 1

    with open(os.path.join(OUT, "v1_vs_header.csv"), "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(["ship", "item", "rule_value", "v1_value", "note", "result"])
        w.writerows(rows)
    summary = {k: dict(v) for k, v in tally.items()}
    with open(os.path.join(OUT, "v1_vs_header_summary.json"), "w", encoding="utf-8") as fh:
        json.dump(summary, fh, ensure_ascii=False, indent=2)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
