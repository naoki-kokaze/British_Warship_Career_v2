"""v1 RDF（LLM 生成）の出来事と、規則v1 の出来事（events.csv）を艦ごとに対応づける（出来事の層の照合）

方針（2026-10-07 ユーザー承認。対応表 §11）
    - 出来事の種類を「種類（kind）」と「家族（family）」に揃える。種類が同じなら同じ出来事の候補、家族が同じなら
      種類の取り違えの候補（例：v1 は再就役、v2 は就役）
    - 日付は両者の精度の粗いほうに揃えて比べる（v1 は精度の印がないので、'1864'・'1864-07'・'1864-07-07' の形から読む）
    - 対応づけの順：
        1 match            種類が同じ・日付が一致
        2 type_differs     家族が同じ・日付が一致・種類が違う
        3 date_differs     種類が同じ・日付が違う（年の差が2年以内で最も近いもの）
        4 v1_event_vs_v2_statement  v1 だけにある出来事が、v2 では出来事にしなかった文（艦長任命・地位の印・注記）と
                           同じ日付にあるもの（v1 が艦長の交代から就役を作った、など。決定B1）
        5 v1_only / v2_only 残り
    - どちらが正しいかはここでは決めない。不一致は原文で裁定する（§11、第3段階）
    - 比べないもの：v2 の艦長任命（v1 は出来事にしていない）・地位の印（v1 は Presence だけ）・注記、
      v1 の建造（E12。定型部分の照合は compare_v1_header_v0.py）。件数だけ summary に出す

入力（読み取りのみ）: ../sources/v1/ship_careers_combined.ttl、../outputs/rules_v1/events.csv
出力: ../outputs/rules_v1/v1_vs_v2_events.csv、v1_vs_v2_events_summary.json
依存: rdflib（サンドボックスの外で実行）
"""
import collections
import csv
import json
import logging
import os
import re

from rdflib import Graph, Namespace
from rdflib.namespace import RDF, RDFS

logging.getLogger("rdflib").setLevel(logging.ERROR)
HERE = os.path.dirname(os.path.abspath(__file__))
TTL = os.path.join(HERE, "../sources/v1/ship_careers_combined.ttl")
EVENTS = os.path.join(HERE, "../outputs/rules_v1/events.csv")
OUT = os.path.join(HERE, "../outputs/rules_v1")
CRM = Namespace("http://www.cidoc-crm.org/cidoc-crm/")
W = Namespace("http://www.example.com/ontology/warship#")

FAMILY = {"commissioning": "commission", "recommissioning": "commission", "decommissioning": "decommission",
          "fitting": "work", "repair": "work", "conversion": "work", "role": "work",
          "sale": "title", "acquisition": "title", "capture": "title", "gift": "title",
          "breaking_up": "end", "loss": "end", "renaming": "name", "rating": "rating",
          "transfer": "custody", "loan": "custody", "other": "other"}
REPAIR = {"SmallRepair", "MiddlingRepair", "LargeRepair", "GreatRepair", "VerySmallRepair", "VeryLargeRepair",
          "SmallToMiddlingRepair", "Repair", "ShipRepair", "DefectsRepair", "MakingGoodDefects", "DefectsMadeGood",
          "Rebuild", "ReEngining"}


def v1_kind(types, label):
    lab = label.lower()
    if "Commissioning" in types:
        return "commissioning"
    if "Recommissioning" in types:
        return "recommissioning"
    if "Decommissioning" in types:
        return "decommissioning"
    if types & REPAIR:
        return "repair"
    if types & {"Fitting", "FittingForSea", "FittingForOrdinary", "FittingForForeignService", "Refit", "Completion",
                "FittingAsReceivingShip"}:
        return "fitting"
    if types & {"ShipConversion", "Hulking"}:
        return "role" if re.search(r"\bbecame\b|\bhulked\b|\bas\b", lab) else "conversion"
    if types & {"E6_Destruction"}:
        if re.search(r"\bsold\b", lab):
            return "sale"
        return "loss" if re.search(r"wreck|founder|lost|burnt|burned|sunk|sank|explod|capsiz", lab) else "breaking_up"
    if types & {"E8_Acquisition", "Purchase"}:
        return "acquisition" if re.search(r"purchas|bought|acquired|taken|transferred to royal navy", lab) else \
            "gift" if re.search(r"present|gift|given", lab) else "sale"
    if "Capture" in types:
        return "capture"
    if "E13_Attribute_Assignment" in types:
        return "renaming" if re.search(r"renamed|reverted|named", lab) else "rating"
    if "E7_Activity" in types:
        if re.search(r"\blent\b|\bloan", lab):
            return "loan"
        if re.search(r"coastguard|transferred|assigned to", lab):
            return "transfer"
        return "role" if re.search(r"\bbecame\b|\bas\b", lab) else "other"
    return "other"


def v2_kind(ev):
    t = ev["type"]
    if t.startswith(":Commissioning"):
        return "commissioning"
    if t.startswith(":Recommissioning"):
        return "recommissioning"
    if t.startswith(":Decommissioning"):
        return "decommissioning"
    if "Repair" in t:
        return "repair"
    if "Conversion" in t:
        return "conversion"
    if "Fitting" in t or "Refit" in t:
        return "role" if ev["role_text"] and "InNonCombatDuty" in ev["status_effect"] else "fitting"
    if t == "(role)":
        return "role"
    if "breaking up" in t:
        return "breaking_up"
    if "loss" in t:
        return "loss"
    if "(sale)" in t or "title to another" in t:
        return "sale"
    if "gift" in t:
        return "gift"
    if "acquisition" in t or "(taken)" in t:
        return "capture" if "(taken)" in t else "acquisition"
    if t.startswith("E15"):
        return "renaming"
    if t.startswith("E13"):
        return "rating"
    if ":Loan" in t or "end of loan" in t:
        return "loan"
    if t.startswith("E10"):
        return "transfer"
    return None   # 比べない（艦長任命・地位の印・注記）


def norm_date(s):
    s = str(s)
    m = re.match(r"(\d{4})(?:-(\d{2}))?(?:-(\d{2}))?", s)
    return "-".join(x for x in m.groups() if x) if m else ""


def same_date(a, b):
    if not a or not b:
        return False
    n = min(len(a.split("-")), len(b.split("-")))
    return a.split("-")[:n] == b.split("-")[:n]


def year_diff(a, b):
    return abs(int(a[:4]) - int(b[:4])) if a and b else None


def load_v1():
    g = Graph().parse(TTL, format="turtle")
    out = collections.defaultdict(list)
    for s in set(g.subjects(CRM["P4_has_time-span"], None)):
        m = re.search(r"event_([A-Z0-9]+_\d{4})_", str(s))
        if not m:
            continue
        types = {str(o).split("#")[-1].split("/")[-1] for o in g.objects(s, RDF.type)}
        if "E12_Production" in types:
            continue
        label = str(g.value(s, RDFS.label) or "")
        ts = g.value(s, CRM["P4_has_time-span"])
        b = g.value(ts, CRM.P82_at_some_time_within) or g.value(ts, CRM.P79_beginning_is_qualified_by)
        e = g.value(ts, CRM.P80_end_is_qualified_by)
        date = norm_date(b) or norm_date(e)
        out[m.group(1)].append({"id": str(s).split("/")[-1], "kind": v1_kind(types, label), "date": date,
                                "types": "+".join(sorted(types)), "label": label})
    return out


def main():
    v1 = load_v1()
    v2 = collections.defaultdict(list)
    statements = collections.defaultdict(list)
    excluded = collections.Counter()
    for ev in csv.DictReader(open(EVENTS, encoding="utf-8-sig")):
        k = v2_kind(ev)
        if k is None:
            excluded[ev["type"]] += 1
            statements[ev["ship"]].append({"id": ev["id"], "kind": "statement", "date": ev["begin"] or ev["end"],
                                           "types": ev["type"], "label": ev["raw"], "status": ev["status"]})
            continue
        v2[ev["ship"]].append({"id": ev["id"], "kind": k, "date": ev["begin"] or ev["end"], "types": ev["type"],
                               "label": ev["raw"], "status": ev["status"]})

    rows = []
    for ship in sorted(set(v1) | set(v2)):
        a, b = list(v1.get(ship, [])), list(v2.get(ship, []))

        def take(cond, cls):
            for x in list(a):
                cands = [y for y in b if cond(x, y)]
                if not cands:
                    continue
                y = min(cands, key=lambda y: (year_diff(x["date"], y["date"]) or 0))
                a.remove(x)
                b.remove(y)
                rows.append(row(ship, cls, x, y))

        take(lambda x, y: x["kind"] == y["kind"] and same_date(x["date"], y["date"]), "match")
        take(lambda x, y: FAMILY[x["kind"]] == FAMILY[y["kind"]] and same_date(x["date"], y["date"]), "type_differs")
        take(lambda x, y: x["kind"] == y["kind"] and x["date"] and y["date"] and year_diff(x["date"], y["date"]) <= 2,
             "date_differs")
        st = list(statements.get(ship, []))
        for x in list(a):
            cands = [y for y in st if same_date(x["date"], y["date"])]
            if cands:
                y = cands[0]
                a.remove(x)
                st.remove(y)
                rows.append(row(ship, "v1_event_vs_v2_statement", x, y))
        rows += [row(ship, "v1_only", x, None) for x in a] + [row(ship, "v2_only", None, y) for y in b]

    fields = ["ship", "result", "family", "v1_kind", "v2_kind", "v1_date", "v2_date", "year_diff",
              "v1_id", "v1_types", "v1_label", "v2_id", "v2_types", "v2_status", "v2_raw"]
    with open(os.path.join(OUT, "v1_vs_v2_events.csv"), "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    by = collections.Counter(r["result"] for r in rows)
    by_family = collections.defaultdict(collections.Counter)
    for r in rows:
        by_family[r["family"]][r["result"]] += 1
    summary = {"ships_v1": len(v1), "ships_v2": len(v2), "v1_events": sum(map(len, v1.values())),
               "v2_events_compared": sum(map(len, v2.values())), "v2_not_compared": dict(excluded.most_common()),
               "results": dict(by.most_common()),
               "by_family": {k: dict(v.most_common()) for k, v in sorted(by_family.items())}}
    json.dump(summary, open(os.path.join(OUT, "v1_vs_v2_events_summary.json"), "w"), ensure_ascii=False, indent=2)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def row(ship, cls, x, y):
    k = x["kind"] if x else y["kind"]
    return {"ship": ship, "result": cls, "family": FAMILY[k],
            "v1_kind": x["kind"] if x else "", "v2_kind": (y["types"] if y["kind"] == "statement" else y["kind"]) if y else "",
            "v1_date": x["date"] if x else "", "v2_date": y["date"] if y else "",
            "year_diff": year_diff(x["date"], y["date"]) if x and y else "",
            "v1_id": x["id"] if x else "", "v1_types": x["types"] if x else "", "v1_label": x["label"] if x else "",
            "v2_id": y["id"] if y else "", "v2_types": y["types"] if y else "", "v2_status": y["status"] if y else "",
            "v2_raw": y["label"] if y else ""}


if __name__ == "__main__":
    main()
