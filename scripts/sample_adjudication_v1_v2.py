"""v1 と v2 の不一致から、裁定（第3段階）のための標本を無作為に抽出する（対応表 §11）

抽出（乱数の種 20261007、計55件）
    出来事の層（v1_vs_v2_events.csv）：v1_only 10、v2_only 10、type_differs 5、date_differs 5、
                                       v1_event_vs_v2_statement 5
    状態の層（v1_vs_v2_states_runs.csv、任務上の地位の軸）：
        事実の食い違いの候補（differ のうち定義の違い B1・B4・F を除く、6か月以上）15、
        v2 に状態がない区間（その艦の v2 の最初の状態より前、12か月以上）5
各件に、その年代（前後1年）の原文の節を付ける。原文の節は rules_v1_survey/clauses.csv から

出力: ../outputs/rules_v1/adjudication_sample.csv（判定の列 verdict・note は空。裁定の結果を記入する）
"""
import collections
import csv
import os
import random
import re

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "../outputs/rules_v1")
CLAUSES = os.path.join(HERE, "../outputs/rules_v1_survey/clauses.csv")
SEED = 20261007
DEFINITIONAL = {("InNonCombatDuty", "InCommission"), ("InOrdinary", "PaidOff"), ("InNonCombatDuty", "InOtherCustody"),
                ("InOrdinary", "InOtherCustody"), ("InCommission", "InOtherCustody"), ("PaidOff", "InOtherCustody")}


def years_in(text):
    return {int(y) for y in re.findall(r"(?<!\d)(1[6-9]\d\d)(?!\d)", text)}


def context(clauses, ship, y_from, y_to):
    rows = clauses.get(ship, [])
    hit = [f"[{n}] {c}" for n, c in rows if any(y_from - 1 <= y <= y_to + 1 for y in years_in(c))]
    return " || ".join(hit) if hit else " || ".join(f"[{n}] {c}" for n, c in rows[:6])


def main():
    rnd = random.Random(SEED)
    clauses = collections.defaultdict(list)
    for r in csv.DictReader(open(CLAUSES, encoding="utf-8-sig")):
        clauses[r["ship"]].append((r["clause_no"], r["clause"]))
    ev = list(csv.DictReader(open(os.path.join(OUT, "v1_vs_v2_events.csv"), encoding="utf-8-sig")))
    runs = [r for r in csv.DictReader(open(os.path.join(OUT, "v1_vs_v2_states_runs.csv"), encoding="utf-8-sig"))
            if r["axis"] == "service"]

    sample = []
    for cls, n in [("v1_only", 10), ("v2_only", 10), ("type_differs", 5), ("date_differs", 5),
                   ("v1_event_vs_v2_statement", 5)]:
        pool = [r for r in ev if r["result"] == cls]
        for r in rnd.sample(pool, n):
            ys = years_in(r["v1_date"] + " " + r["v2_date"]) or {1800}
            sample.append({"layer": "event", "category": cls, "ship": r["ship"],
                           "v1": f"{r['v1_kind']} {r['v1_date']} | {r['v1_label']}" if r["v1_id"] else "",
                           "v2": f"{r['v2_kind']} {r['v2_date']} | {r['v2_raw']}" if r["v2_id"] else "",
                           "v1_id": r["v1_id"], "v2_id": r["v2_id"],
                           "source": context(clauses, r["ship"], min(ys), max(ys))})

    first_v2 = {}
    for r in runs:
        if r["v2_status"] and r["ship"] not in first_v2:
            first_v2[r["ship"]] = r["from"]
    factual = [r for r in runs if r["result"] == "differ" and int(r["months"]) >= 6
               and (r["v1_status"], r["v2_status"]) not in DEFINITIONAL]
    before = [r for r in runs if r["result"] == "v2_none" and int(r["months"]) >= 12
              and r["ship"] in first_v2 and r["to"] < first_v2[r["ship"]]]
    for cat, pool, n in [("state_differ", factual, 15), ("state_v2_none_before_first", before, 5)]:
        for r in rnd.sample(pool, n):
            sample.append({"layer": "state", "category": cat, "ship": r["ship"],
                           "v1": f"{r['v1_status']} {r['from']}〜{r['to']} ({r['months']}か月)",
                           "v2": f"{r['v2_status'] or '(なし)'} {r['from']}〜{r['to']}",
                           "v1_id": "", "v2_id": "",
                           "source": context(clauses, r["ship"], int(r["from"][:4]), int(r["to"][:4]))})

    fields = ["no", "layer", "category", "ship", "v1", "v2", "v1_id", "v2_id", "source", "verdict", "note"]
    with open(os.path.join(OUT, "adjudication_sample.csv"), "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for i, s in enumerate(sample, 1):
            w.writerow({"no": i, **s, "verdict": "", "note": ""})
    print(len(sample), collections.Counter(s["category"] for s in sample))


if __name__ == "__main__":
    main()
