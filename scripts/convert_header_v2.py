"""規則v0で取り出した定型部分の事実を、オントロジv2（draft.2）の形のRDFに決定論的に変換する

入力（読み取りのみ）:
    ../outputs/rules_v0/header_facts.csv（extract_header_v0.py の出力）
    ../outputs/rules_v01/dimension_facts.csv（extract_dimensions_v01.py の出力、規則v0.1）
    ../sources/v1/strata/*.xlsx（艦名）
出力:
    ../outputs/rdf_v2/header_v2.ttl
    ../outputs/rdf_v2/header_v2_summary.json

変換の方針（2026-09-30 ユーザー決定。docs/jinmoncom2026_rules_v0_header_report_20260930.md §5）
    - crm:E12_Production は crm:P108_has_produced で艦に結ぶ。期間は起工日（K:）から最初の竣工日（C:）まで
    - 進水（:Launching）と最初の竣工（:Completion）は建造の一部（crm:P9_consists_of）
    - 発注（:Ordering）・再発注（:Reordering）は建造の動機（crm:P17_was_motivated_by）
    - 2回目以降の C: は :Fitting（目的に応じて :FittingForSea / :FittingForOrdinary）として艦に結ぶ（:modifies_ship）
    - 建造費は原文の内訳ごとに crm:E97_Monetary_Amount を作り、:CostComponent で種類を付ける。合計は原文にある場合だけ
    - 記録の層は原文に忠実にする：ない値を別の値で代用しない。原文の誤り（OCR）も直さず、SHACL の検査で見つける
    - 各ノードに :generated_by_rule（規則ID）と :source_text（原文の文字列）を付ける
    - draft.2（2026-10-05、CIDOC監査 docs/jinmoncom2026_ontology_v1_cidoc_audit_20261001.md §5）：
      日付は境界 P82a（始まりの最も早い時点）・P81a（始まりの最も遅い時点）・P81b（終わりの最も早い時点）・
      P82b（終わりの最も遅い時点）で、値は xsd:date。月までの日付は月初〜月末、年までは1/1〜12/31。
      P79/P80 は日付には使わず、原文の「?」などの注記に使う
    - 寸法（規則v0.1、2026-10-05）：原文の区間ごとに crm:E16_Measurement（種類は :MeasurementOccasion）を作り、
      crm:P39_measured で艦、crm:P40_observed_dimension で crm:E54_Dimension（種類は :DimensionKind）を結ぶ。
      長さは :value_feet と :value_inches を別々に、bm は :tons_bm_whole と :tons_bm_ninety_fourths を別々に持たせる
      （換算は分析の層）。値の得かたは :value_status（parsed / formula_resolved / visually_* / needs_review）。
      解析不能（unparsed）の値は RDF にせず、CSV の確認リストに残す。
      As built・Tonnage as completed の計測は、海軍で建造された艦（括弧の外に起工か進水がある艦）では建造の一部
      （crm:P9_consists_of）とする。取得艦・改装後の計測は、取得・改装の出来事（規則v1）ができてから結ぶ。
      近道の crm:P43_has_dimension は、改装・延長後でない計測（As built・Dimensions & tons・as completed）にだけ付ける

依存: rdflib, openpyxl
"""
import calendar
import collections
import csv
import glob
import json
import os
import re

import openpyxl
from rdflib import BNode, Graph, Literal, Namespace, URIRef
from rdflib.namespace import RDF, RDFS, XSD

import sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import dataset_paths as P   # 開発用／評価用の切り替え（JINMON_DATASET）
FACTS = P.out("rules_v0/header_facts.csv")
DIMS = P.out("rules_v01/dimension_facts.csv")
OCCASION = {"as built": "AsBuilt", "dimensions and tons": "DimensionsAndTons", "as completed": "AsCompleted",
            "as lengthened": "AsLengthened", "as converted": "AsConverted"}
LENGTH_KINDS = {"GundeckLength", "KeelLengthForTonnage", "BreadthForTonnage", "DepthInHold", "DraughtForward",
                "DraughtAft", "MouldedBreadth", "BreadthMarkedOA", "BreadthUnlabelled", "LengthUnspecified"}
STRATA = P.STRATA
OUT = P.out("rdf_v2")

W = Namespace("http://www.example.com/ontology/warship#")
CRM = Namespace("http://www.cidoc-crm.org/cidoc-crm/")
SEALIT = Namespace("http://www.sealitproject.eu/ontology/")
D = Namespace("http://www.example.com/myData/")
ONTOLOGY = os.path.join(HERE, "../outputs/ontology_v2/warship_career_ontology_v2.ttl")
COST_KIND = {"HULL": W.HullCost, "MACHINERY": W.MachineryCost, "FITTING": W.FittingCost, "BUILD": W.BuildCost,
             "SUPPLIES": W.SuppliesCost, "TOTAL": W.StatedTotalCost, "UNLABELLED": W.UnspecifiedCost}
USABLE = {"parsed", "partial", "ambiguous"}   # unparsed / empty は RDF にせず、確認リストに残す


def bounds(value, precision):
    """原文の精度の日付を、その日付が収まる最初の日と最後の日（xsd:date）にする"""
    if precision == "day":
        return Literal(value, datatype=XSD.date), Literal(value, datatype=XSD.date)
    if precision == "month":
        y, m = map(int, value.split("-"))
        return (Literal(f"{y:04d}-{m:02d}-01", datatype=XSD.date),
                Literal(f"{y:04d}-{m:02d}-{calendar.monthrange(y, m)[1]:02d}", datatype=XSD.date))
    if precision == "year":
        return Literal(f"{value}-01-01", datatype=XSD.date), Literal(f"{value}-12-31", datatype=XSD.date)
    raise ValueError(precision)


def add_begin(g, ts, value, precision):
    first, last = bounds(value, precision)
    g.add((ts, CRM.P82a_begin_of_the_begin, first))
    g.add((ts, CRM.P81a_end_of_the_begin, last))


def add_end(g, ts, value, precision):
    first, last = bounds(value, precision)
    g.add((ts, CRM.P81b_begin_of_the_end, first))
    g.add((ts, CRM.P82b_end_of_the_end, last))


UNCERTAIN_NOTE = Literal("the source marks this date as uncertain ('?')", lang="en")


def undeclared_terms(g, ontology=ONTOLOGY):
    """オントロジで宣言されていない用語の件数（CIDOC 公式の用語でも、v2 で宣言していなければ挙げる）。
    header・events の変換の要約に出す（10/21：events だけにあったものを関数にして header でも使う）"""
    onto = Graph().parse(ontology, format="turtle")
    declared = set(onto.subjects())
    used = collections.Counter()
    for _s, pr, o in g:
        if str(pr).startswith((str(CRM), str(W))):
            used[pr] += 1
        if pr == RDF.type and str(o).startswith((str(CRM), str(W), str(SEALIT))):
            used[o] += 1
        if str(o).startswith(str(W)) and pr != RDF.type:
            used[o] += 1
    return {g.namespace_manager.qname(t): n for t, n in sorted(used.items()) if t not in declared}


def slug(text):
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def add_timespan(g, node, f):
    """始まりと終わりを境界で表す。単一の日付は、始まりも終わりもその日（または月・年）の中にある"""
    ts = BNode()
    g.add((node, CRM["P4_has_time-span"], ts))
    g.add((ts, RDF.type, CRM["E52_Time-Span"]))
    add_begin(g, ts, f["begin"], f["begin_precision"])
    add_end(g, ts, f["end"], f["end_precision"])
    if f["uncertain"] == "True":   # 原文の「?」が始まり・終わりのどちらに係るかは区別できないので両方に付ける
        g.add((ts, CRM.P79_beginning_is_qualified_by, UNCERTAIN_NOTE))
        g.add((ts, CRM.P80_end_is_qualified_by, UNCERTAIN_NOTE))


def annotate(g, node, f):
    g.add((node, W.generated_by_rule, Literal(f["rules"])))
    g.add((node, W.source_text, Literal(f["raw"])))
    notes = []
    if f["qualifier"]:
        notes.append(f"qualifier: {f['qualifier']}")
    if f["status"] == "ambiguous":
        notes.append("ambiguous in the source; the first date is recorded (requires review)")
    if f["status"] == "partial":
        notes.append("partially parsed; see :source_text (requires review)")
    for n in notes:
        g.add((node, RDFS.comment, Literal(n, lang="en")))


def add_place(g, node, f):
    if f["place"]:
        pl = D[f"place_{slug(f['place'])}"]
        g.add((pl, RDF.type, CRM.E53_Place))
        g.add((pl, RDFS.label, Literal(f["place"], lang="en")))
        g.add((node, CRM.P7_took_place_at, pl))


def purpose_classes(f):
    q = f["qualifier"].lower()
    return [W.FittingForSea] if "for sea" in q else [W.FittingForOrdinary] if "for ordinary" in q else []


def add_dimensions(g, facts, tally):
    """規則v0.1の寸法を E16_Measurement / E54_Dimension にする"""
    for unit, label in [("unit_ft_in", "feet and inches (Imperial)"), ("unit_ton_bm", "tons Builder's Measurement"),
                        ("unit_ton_displacement", "tons displacement")]:
        g.add((D[unit], RDF.type, CRM.E58_Measurement_Unit))
        g.add((D[unit], RDFS.label, Literal(label, lang="en")))
    rows = [r for r in csv.DictReader(open(DIMS, encoding="utf-8-sig")) if r["status"] != "unparsed"]
    built = {sid for sid, fx in facts.items()
             if any("inside parentheses" not in f["qualifier"] and f["status"] in USABLE and f["begin"]
                    for fld in ("KEEL_LAID", "LAUNCHED") for f in fx.get(fld, []))}
    count = collections.Counter()
    for r in rows:
        sid, seg = r["ship"], r["segment"]
        ship = D[sid]
        meas = D[f"measurement_{sid}_{seg}"]
        if (meas, RDF.type, CRM.E16_Measurement) not in g:
            g.add((meas, RDF.type, CRM.E16_Measurement))
            g.add((meas, CRM.P2_has_type, W[OCCASION[r["context"]]]))
            g.add((meas, CRM.P39_measured, ship))
            g.add((meas, RDFS.label, Literal(f"Measurement of {sid} ({r['context']})", lang="en")))
            if r["context"] in ("as built", "as completed") and sid in built:
                g.add((D[f"production_{sid}"], CRM.P9_consists_of, meas))
                tally["measurement_part_of_production"] += 1
            tally["E16_Measurement"] += 1
        if r["kind"] in ("Dimensions", "Note"):   # 値にならない記述は計測の注記に残す
            g.add((meas, RDFS.comment, Literal(f"{r['raw']} ({r['note']})", lang="en")))
            continue
        count[(sid, seg, r["kind"])] += 1
        k = count[(sid, seg, r["kind"])]
        dim = D[f"dimension_{sid}_{seg}_{r['kind']}" + (f"_{k}" if k > 1 else "")]
        g.add((dim, RDF.type, CRM.E54_Dimension))
        g.add((dim, CRM.P2_has_type, W[r["kind"]]))
        g.add((meas, CRM.P40_observed_dimension, dim))
        if r["context"] not in ("as lengthened", "as converted"):
            g.add((ship, CRM.P43_has_dimension, dim))
        if r["kind"] in LENGTH_KINDS:
            g.add((dim, CRM.P91_has_unit, D.unit_ft_in))
            if r["feet"] != "":
                g.add((dim, W.value_feet, Literal(int(float(r["feet"])), datatype=XSD.integer)))
            if r["inches"] != "":
                g.add((dim, W.value_inches, Literal(f"{float(r['inches']):g}", datatype=XSD.decimal)))
        elif r["kind"] == "BuildersMeasurement":
            g.add((dim, CRM.P91_has_unit, D.unit_ton_bm))
            if r["tons_bm_whole"] != "":
                g.add((dim, W.tons_bm_whole, Literal(int(r["tons_bm_whole"]), datatype=XSD.integer)))
            if r["tons_bm_94ths"] != "":
                g.add((dim, W.tons_bm_ninety_fourths, Literal(int(r["tons_bm_94ths"]), datatype=XSD.integer)))
        elif r["kind"] == "Displacement":
            g.add((dim, CRM.P91_has_unit, D.unit_ton_displacement))
            g.add((dim, CRM.P90_has_value, Literal(int(r["value"]), datatype=XSD.integer)))
        g.add((dim, W.value_status, Literal(r["status"])))
        g.add((dim, W.generated_by_rule, Literal(r["rules"])))
        g.add((dim, W.source_text, Literal(r["raw"])))
        if r["uncertain"] == "True":
            g.add((dim, RDFS.comment, Literal("the source marks this value as approximate ('about')", lang="en")))
        if r["qualifier"]:
            g.add((dim, RDFS.comment, Literal(f"qualifier: {r['qualifier']}", lang="en")))
        if r["note"]:
            g.add((dim, RDFS.comment, Literal(r["note"], lang="en")))
        tally["E54_Dimension"] += 1
        tally[f"dimension_status_{r['status']}"] += 1


def main():
    os.makedirs(OUT, exist_ok=True)
    names = {}
    for fn in sorted(glob.glob(os.path.join(STRATA, "*.xlsx"))):
        rows = list(openpyxl.load_workbook(fn, read_only=True).worksheets[0].iter_rows(values_only=True))
        for r in rows[1:]:
            d = dict(zip(rows[0], r))
            names[f"{d['Prefix']}_{int(d['serial_no']):04d}"] = str(d["Name"])

    facts = collections.defaultdict(lambda: collections.defaultdict(list))
    for f in csv.DictReader(open(FACTS, encoding="utf-8-sig")):
        facts[f["ship"]][f["field"]].append(f)

    g = Graph()
    for p, ns in [("", W), ("crm", CRM), ("sealit", SEALIT), ("myData", D), ("xsd", XSD), ("rdfs", RDFS)]:
        g.bind(p, ns)
    g.add((D.currency_gbp, RDF.type, CRM.E98_Currency))
    g.add((D.currency_gbp, RDFS.label, Literal("GBP", lang="en")))
    tally = collections.Counter()

    for sid in sorted(names):
        ship = D[sid]
        g.add((ship, RDF.type, SEALIT.Ship))
        g.add((ship, RDFS.label, Literal(names[sid], lang="en")))
        fx = facts.get(sid, {})
        prod = D[f"production_{sid}"]
        g.add((prod, RDF.type, CRM.E12_Production))
        g.add((prod, CRM.P108_has_produced, ship))
        g.add((prod, RDFS.label, Literal(f"Production of {names[sid]}", lang="en")))
        g.add((prod, W.generated_by_rule, Literal("P0")))   # P0: 艦ごとに建造ノードを1つ作る（変換の規則）
        tally["E12_Production"] += 1

        # 建造の期間：起工日（始点）〜最初の竣工日（終点）。ない値は空のまま
        keel = [f for f in fx.get("KEEL_LAID", []) if f["status"] in USABLE and f["begin"]]
        comp = [f for f in fx.get("COMPLETED", []) if f["status"] in USABLE and f["begin"]]
        if keel or comp:
            ts = BNode()
            g.add((prod, CRM["P4_has_time-span"], ts))
            g.add((ts, RDF.type, CRM["E52_Time-Span"]))
            if keel:
                add_begin(g, ts, keel[0]["begin"], keel[0]["begin_precision"])
                if keel[0]["uncertain"] == "True":
                    g.add((ts, CRM.P79_beginning_is_qualified_by, UNCERTAIN_NOTE))
                g.add((prod, W.source_text, Literal("K: " + keel[0]["raw"])))
                tally["production_begin_from_keel"] += 1
            if comp:
                add_end(g, ts, comp[0]["end"], comp[0]["end_precision"])
                if comp[0]["uncertain"] == "True":
                    g.add((ts, CRM.P80_end_is_qualified_by, UNCERTAIN_NOTE))
                tally["production_end_from_first_completion"] += 1

        for field, cls, link in [("ORDERED", W.Ordering, CRM.P17_was_motivated_by),
                                 ("REORDERED", W.Reordering, CRM.P17_was_motivated_by),
                                 ("LAUNCHED", W.Launching, CRM.P9_consists_of)]:
            for i, f in enumerate(x for x in fx.get(field, []) if x["status"] in USABLE and x["begin"]):
                node = D[f"{cls.split('#')[1].lower()}_{sid}" + (f"_{i + 1}" if i else "")]
                g.add((node, RDF.type, cls))
                g.add((prod, link, node))
                add_timespan(g, node, f)
                add_place(g, node, f)
                annotate(g, node, f)
                tally[cls.split("#")[1]] += 1

        for i, f in enumerate(comp):
            if i == 0:   # 最初の竣工：建造の一部
                node = D[f"completion_{sid}"]
                g.add((node, RDF.type, W.Completion))
                g.add((prod, CRM.P9_consists_of, node))
                tally["Completion"] += 1
            else:        # 2回目以降：艤装の出来事
                node = D[f"fitting_{sid}_c{i + 1}"]
                g.add((node, RDF.type, W.Fitting))
                tally["Fitting(later C:)"] += 1
            for c in purpose_classes(f):
                g.add((node, RDF.type, c))
            g.add((node, W.modifies_ship, ship))
            add_timespan(g, node, f)
            add_place(g, node, f)
            annotate(g, node, f)

        for n, f in enumerate(x for x in fx.get("FIRST_COST", []) if x["status"] in ("parsed", "partial")):
            amt = D[f"cost_{sid}_{n + 1}"]
            g.add((amt, RDF.type, CRM.E97_Monetary_Amount))
            g.add((amt, CRM.P2_has_type, COST_KIND.get(f["cost_kind"], W.UnspecifiedCost)))
            g.add((amt, CRM.P90_has_value, Literal(f"{float(f['amount_gbp']):.4f}".rstrip("0").rstrip("."), datatype=XSD.decimal)))
            g.add((amt, CRM.P180_has_currency, D.currency_gbp))
            g.add((amt, W.generated_by_rule, Literal(f["rules"])))
            g.add((amt, W.source_text, Literal(f["raw"])))
            g.add((prod, W.incurred_cost, amt))
            tally["cost_amounts"] += 1
        for f in fx.get("FIRST_COST", []):
            if f["status"] == "stated_unknown":
                g.add((prod, RDFS.comment, Literal("First cost is stated as unknown in the source.", lang="en")))

    add_dimensions(g, facts, tally)
    g.serialize(os.path.join(OUT, "header_v2.ttl"), format="turtle")
    summary = {"ships": len(names), "triples": len(g), **dict(tally), "undeclared_terms": undeclared_terms(g)}
    with open(os.path.join(OUT, "header_v2_summary.json"), "w", encoding="utf-8") as fh:
        json.dump(summary, fh, ensure_ascii=False, indent=2)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
