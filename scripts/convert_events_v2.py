"""規則v1の出来事と Presence を、オントロジv2（draft.2）の形のRDFに決定論的に変換する

入力（読み取りのみ）:
    ../outputs/rules_v1/events.csv（extract_events_v1.py の出力）
    ../outputs/rules_v1/presences.csv（build_presence_v1.py の出力）
    ../outputs/ontology_v2/warship_career_ontology_v2.ttl（宣言されていない用語の一覧を出すため）
出力:
    ../outputs/rdf_v2/events_v2.ttl
    ../outputs/rdf_v2/events_v2_summary.json

変換の方針（対応表 docs/jinmoncom2026_rules_v1_mapping_draft_20261005.md §5〜§10）
    - 艦（myData:<艦>）と場所・通貨は convert_header_v2.py と同じ IRI。header_v2.ttl と合わせて読む前提
    - 出来事の IRI は events.csv の id（案c、§5.5）。時間は myData:ts_<id>（E52）。日付の書き方は
      convert_header_v2.py と同じ（P82a/P81a/P81b/P82b）
    - 出来事と艦の結び方：E11（工事）:modifies_ship、E6 P13_destroyed、E8/E96 P24_transferred_title_of、
      E10 P30_transferred_custody_of、E13/E15 P140_assigned_attribute_to、E7 P12_occurred_in_the_presence_of
    - 所有の向き：status_effect が end なら海軍から相手へ（P23 海軍・P22 相手）、start なら相手から海軍へ
    - 地位の印（"(status)"・"(status: stored ashore)"）・役割の文（"(role)"）・注記（"(note: ...)"）は出来事にしない。
      その文から始まる Presence に :source_text として残す
    - Presence（E93）：艦から crm:P195i_had_presence。状態は :has_service_status / :has_work_status
      - 工事と解体中（relation = during）：P164 で出来事と同じ E52 を指す（P164 の scope note の1つ目の場合、§10）
      - 任務上の地位：自分の E52（myData:ts_<Presence>）。始まりの出来事へ P182i、終わりの出来事へ P182
    - 要確認（needs_review）の出来事には rdfs:comment で理由を残す
    - 解体・売却の命令（"by AO D"、order_date）は :BreakingUpOrder・:SaleOrder として別の出来事にし、crm:P17_was_motivated_by で結ぶ
    - B1r の Presence（derived = B1r）は :generated_by_rule "B1r" と注記で、規則で導いた値であることを示す
    - 配属先（2026-10-09）：events.csv の stations 列（JSON）から :StationDeployment。出来事から :has_station_deployment、
      艦へ P12、配属先（E53。就役した港とは別の myData:station_<表記>、P2 :SeaStation）へ P7、順序 :station_order、
      日付があれば P4。"on same station" で補ったもの（ST4）は :review_note
    - 改名の P38（外した名前）は付けない（その時点の名前を追う仕組みが未実装。§10 の未決）

依存: rdflib（サンドボックスの外で実行）
"""
import collections
import csv
import json
import os
import re
import sys

from rdflib import Graph, Literal, URIRef
from rdflib.namespace import RDF, RDFS, XSD

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from convert_header_v2 import CRM, D, SEALIT, W, add_begin, add_end, slug, undeclared_terms, UNCERTAIN_NOTE  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import dataset_paths as P   # 開発用／評価用の切り替え（JINMON_DATASET）
EVENTS = P.out("rules_v1/events.csv")
PRESENCES = P.out("rules_v1/presences.csv")
ONTOLOGY = os.path.join(HERE, "../outputs/ontology_v2/warship_career_ontology_v2.ttl")
OUT = P.out("rdf_v2")

NAVY = D.royal_navy
NOT_EVENTS = ("(status)", "(status: stored ashore)", "(role)", "(role end)", "(note: never commissioned)", "(note: housed over)")
LINK = {"E11": W.modifies_ship, "E6": CRM.P13_destroyed, "E8": CRM.P24_transferred_title_of,
        "E96": CRM.P24_transferred_title_of, "E10": CRM.P30_transferred_custody_of,
        "E13": CRM.P140_assigned_attribute_to, "E15": CRM.P140_assigned_attribute_to,
        "E7": CRM.P12_occurred_in_the_presence_of}
CIDOC_CLASS = {"E6": CRM.E6_Destruction, "E7": CRM.E7_Activity, "E8": CRM.E8_Acquisition, "E96": CRM.E96_Purchase,
               "E10": CRM.E10_Transfer_of_Custody, "E11": CRM.E11_Modification, "E13": CRM.E13_Attribute_Assignment,
               "E15": CRM.E15_Identifier_Assignment}


def classes(ev):
    """type 列の ':X'・'sealit:X' をクラスに、なければ cidoc 列の E クラスに"""
    out = []
    for tok in re.findall(r"(?<![\w:])(:[A-Z]\w+|sealit:[A-Z]\w+)", ev["type"]):
        if tok in (":Loan", ":Transfer", ":changes_ship_rating"):
            continue
        out.append(SEALIT[tok.split(":")[1]] if tok.startswith("sealit:") else W[tok[1:]])
    if not out:
        out = [CIDOC_CLASS[c] for c in ev["cidoc"].split("+") if c in CIDOC_CLASS]
    return list(dict.fromkeys(out))


def add_dates(g, ts, f):
    """f の begin/end（と精度）を E52 に。片方しかなければ片方だけ。'after' は境界にせず注記"""
    if f.get("date_role") == "after":
        g.add((ts, RDFS.comment, Literal(f"the source gives only 'after {f['begin']}'", lang="en")))
        return
    if f["begin"] and f["begin_precision"]:
        add_begin(g, ts, f["begin"], f["begin_precision"])
    if f["end"] and f["end_precision"]:
        add_end(g, ts, f["end"], f["end_precision"])


def actor(g, name):
    node = D[f"actor_{slug(name)}"]
    g.add((node, RDF.type, CRM.E39_Actor))
    g.add((node, RDFS.label, Literal(name, lang="en")))
    return node


def amount(g, node_id, value):
    amt = D[f"amount_{node_id}"]
    g.add((amt, RDF.type, CRM.E97_Monetary_Amount))
    g.add((amt, CRM.P90_has_value, Literal(f"{float(value):.4f}".rstrip("0").rstrip("."), datatype=XSD.decimal)))
    g.add((amt, CRM.P180_has_currency, D.currency_gbp))
    return amt


def heading_chain(name, heading):
    """N1・N2（決定B5）：見出しの "(ex-...)" から、古い順の名前の列 [(名前, 種類, 改名の日付), ...] を作る。最後は見出しの名前"""
    chain = []
    for grp in reversed(re.findall(r"[(\[]\s*ex-\s*([^)\]]*)", heading)):
        head = re.split(r",", grp)[0].strip()
        kind = "navy"
        m = re.match(r"(?:(mercantile|PO|pirate vessel|slaver|private yacht|yacht|French)\b)\s*", head)
        if m:
            kind, head = "pre", head[m.end():].strip()
        if not head or head[0] in "-0123456789":   # 名前がない（"ex-mercantile - -"、"ex-74 of 1811"）
            continue
        rd = re.search(r"renamed\s+((?:\d{1,2}\s*\.\s*){0,2}\d[\d ]{3,5})", grp)
        chain.append((head, kind, re.sub(r"\s+", "", rd.group(1)) if rd else ""))
    chain.append((name, "heading", ""))
    return chain


def iso(d):
    """'27.2.1843' / '7.1862' / '1813' → (ISO, 精度)"""
    parts = [x for x in d.split(".") if x]
    if len(parts) == 3:
        return f"{int(parts[2]):04d}-{int(parts[1]):02d}-{int(parts[0]):02d}", "day"
    if len(parts) == 2:
        return f"{int(parts[1]):04d}-{int(parts[0]):02d}", "month"
    return (f"{int(parts[0]):04d}", "year") if parts else ("", "")


def add_names(g, events, as_event, tally):
    """名前の追跡（2026-10-07）：最初の名前（見出し、決定B5の ex- を含む）から改名を順にたどり、E15 に P38（外した名前）と
    P37（付けた名前）を付ける。艦から各名前へ P1。新しい名前が読めない・OCR で崩れた名前は :review_note"""
    import glob
    import openpyxl
    names, heads = {}, {}
    for fn in sorted(glob.glob(os.path.join(P.STRATA, "*.xlsx"))):
        rows = list(openpyxl.load_workbook(fn, read_only=True).worksheets[0].iter_rows(values_only=True))
        for r in rows[1:]:
            d = dict(zip(rows[0], r))
            sid = f"{d['Prefix']}_{int(d['serial_no']):04d}"
            names[sid], heads[sid] = str(d["Name"]), str(d["text"] or "").split("\n")[0]
    by_ship = collections.defaultdict(list)
    for ev in events:
        by_ship[ev["ship"]].append(ev)

    def name_node(sid, nm):
        n = D[f"name_{sid}_{slug(nm)}"]
        g.add((n, RDF.type, CRM.E42_Identifier))
        g.add((n, RDFS.label, Literal(nm)))
        g.add((D[sid], CRM.P1_is_identified_by, n))
        return n

    def narrative(node, e, current):
        """叙述の改名1件：P38 に今の名前、P37 に新しい名前を付け、改名後の名前を返す"""
        g.add((node, CRM.P38_deassigned, name_node(e["ship"], current)))
        tally["renamings_with_P38"] += 1
        nm = e["new_name"]
        if not nm:
            g.add((node, W.review_note, Literal("the new name could not be read; the name is not followed after this renaming")))
            return current
        g.add((node, CRM.P37_assigned, name_node(e["ship"], nm)))
        if len(nm) < 3 or nm[0].islower() or re.search(r"\bIll\b", nm):
            g.add((node, W.review_note, Literal(f"the new name '{nm}' may be garbled by OCR (see :source_text)")))
        return nm

    for sid in sorted(names):
        evs = sorted(by_ship.get(sid, []), key=lambda e: int(e["event_no"]))
        renames = [e for e in evs if e["type"] == "E15 (renaming)" and e["id"] in as_event]
        chain = heading_chain(names[sid], heads[sid])
        current = chain[0][0]
        name_node(sid, current)
        acq = next((e for e in evs if "start" in e["status_effect"].split(";") and e["id"] in as_event), None)
        for (old, okind, rdate), (new, nkind, _) in zip(chain, chain[1:]):   # "(ex-Dove, renamed D)" の D は古い名前の側
            if old.lower() == new.lower():   # 取得前と同じ名前（"ex-mercantile Glatton"）：改名は作らない
                current = new
                continue
            reuse = next((e for e in renames if e["new_name"].lower() == new.lower()), None) if nkind == "heading" else None
            if reuse:   # 見出しの名前への改名が叙述にある
                # 2026-10-14（試しの判定 SM_9036）：叙述でそれより前にある改名（"renamed Refuge, then renamed Resolute"）を
                # 先に順にたどる。そうしないと途中の名前が飛び、旧名（P38）がずれる
                for e in [e for e in renames if int(e["event_no"]) < int(reuse["event_no"])]:
                    current = narrative(as_event[e["id"]], e, current)
                    renames.remove(e)
                old = current
                node = as_event[reuse["id"]]
                renames.remove(reuse)
            else:
                acq_date = (acq["begin"] or acq["end"]) if (okind == "pre" and acq is not None) else ""
                date8 = (iso(rdate)[0] if rdate else acq_date).replace("-", "").ljust(8, "0") or "00000000"   # 案c
                node = D[f"{sid}_{date8}_renaming_{slug(new)}"]
                g.add((node, RDF.type, CRM.E15_Identifier_Assignment))
                g.add((node, CRM.P140_assigned_attribute_to, D[sid]))
                g.add((node, W.source_text, Literal(heads[sid])))
                if okind == "pre":   # N2：取得時の改名。時間は取得の出来事と同じ
                    g.add((node, W.generated_by_rule, Literal("N2")))
                    g.add((node, RDFS.comment, Literal("renamed on acquisition", lang="en")))
                    if acq is not None:
                        g.add((node, CRM["P4_has_time-span"], D[f"ts_{acq['id']}"]))
                else:   # N1：海軍の中での改名（見出しが新しい名前）
                    g.add((node, W.generated_by_rule, Literal("N1")))
                    if rdate:
                        ts = D[f"ts_{node.split('/')[-1]}"]
                        g.add((node, CRM["P4_has_time-span"], ts))
                        g.add((ts, RDF.type, CRM["E52_Time-Span"]))
                        v, pr = iso(rdate)
                        add_dates(g, ts, {"begin": v, "begin_precision": pr, "end": v, "end_precision": pr})
                    else:
                        g.add((node, RDFS.comment, Literal("the date of this renaming is not given", lang="en")))
                tally[f"renamings_from_heading_{'N2' if okind == 'pre' else 'N1'}"] += 1
            g.add((node, CRM.P38_deassigned, name_node(sid, old)))
            g.add((node, CRM.P37_assigned, name_node(sid, new)))
            current = new
        for e in evs:
            node = as_event.get(e["id"])
            if node is None or e["cidoc"] != "E15":
                continue
            if e["type"] == "E15 (naming)":   # 命名：その時点の名前を付けたことの記録
                g.add((node, CRM.P37_assigned, name_node(sid, e["new_name"] or current)))
                continue
            if e not in renames:
                continue
            current = narrative(node, e, current)


def main():
    events = list(csv.DictReader(open(EVENTS, encoding="utf-8-sig")))
    presences = list(csv.DictReader(open(PRESENCES, encoding="utf-8-sig")))
    g = Graph()
    for p, ns in [("", W), ("crm", CRM), ("sealit", SEALIT), ("myData", D), ("xsd", XSD), ("rdfs", RDFS)]:
        g.bind(p, ns)
    g.add((NAVY, RDF.type, CRM.E74_Group))
    g.add((NAVY, RDFS.label, Literal("Royal Navy (Admiralty)", lang="en")))
    tally = collections.Counter()
    as_event = {}

    for ev in events:
        if ev["status"] == "skip" or ev["type"] in NOT_EVENTS or not ev["cidoc"]:
            tally["statements_not_events"] += 1
            continue
        node, ship = D[ev["id"]], D[ev["ship"]]
        as_event[ev["id"]] = node
        for c in classes(ev):
            g.add((node, RDF.type, c))
        for c in ev["cidoc"].split("+"):
            if c in LINK:
                g.add((node, LINK[c], ship))
        ts = D[f"ts_{ev['id']}"]
        g.add((node, CRM["P4_has_time-span"], ts))
        g.add((ts, RDF.type, CRM["E52_Time-Span"]))
        add_dates(g, ts, ev)
        if ev["uncertain"] == "True":
            g.add((ts, CRM.P79_beginning_is_qualified_by, UNCERTAIN_NOTE))
            g.add((ts, CRM.P80_end_is_qualified_by, UNCERTAIN_NOTE))
        if ev["place"]:
            pl = D[f"place_{slug(ev['place'])}"]
            g.add((pl, RDF.type, CRM.E53_Place))
            g.add((pl, RDFS.label, Literal(ev["place"], lang="en")))
            g.add((node, CRM.P7_took_place_at, pl))
        eff = ev["status_effect"].split(";")
        cp = actor(g, ev["counterparty"]) if ev["counterparty"] and "→" not in ev["counterparty"] else None
        if ev["cidoc"] in ("E8", "E96"):
            if "end" in eff:
                g.add((node, CRM.P23_transferred_title_from, NAVY))
                if cp:
                    g.add((node, CRM.P22_transferred_title_to, cp))
            elif "start" in eff:
                g.add((node, CRM.P22_transferred_title_to, NAVY))
                if cp:
                    g.add((node, CRM.P23_transferred_title_from, cp))
            if ev["cidoc"] == "E96" and ev["amount_gbp"]:
                g.add((node, CRM.P179_had_sales_price, amount(g, ev["id"], ev["amount_gbp"])))
        elif ev["amount_gbp"]:
            g.add((node, W.incurred_cost, amount(g, ev["id"], ev["amount_gbp"])))
        if ev["cidoc"] == "E10":
            g.add((node, CRM.P2_has_type, W.Loan if ":Loan" in ev["type"] or "loan" in ev["type"] else W.Transfer))
            if "service:InOtherCustody" in eff:
                g.add((node, CRM.P28_custody_surrendered_by, NAVY))
                if cp:
                    g.add((node, CRM.P29_custody_received_by, cp))
            elif "service:end_InOtherCustody" in eff:
                g.add((node, CRM.P29_custody_received_by, NAVY))
            elif "start" in eff:
                g.add((node, CRM.P29_custody_received_by, NAVY))
        if ev["order_date"] and ev["cidoc"] in ("E6", "E96"):   # U1：解体・売却の命令（AO）を別の出来事にし、P17 で結ぶ
            kind = "breaking_up_order" if ev["cidoc"] == "E6" else "sale_order"
            order = D[f"{ev['ship']}_{ev['order_date'].replace('-', '').ljust(8, '0')}_{kind}"]
            g.add((order, RDF.type, W.BreakingUpOrder if ev["cidoc"] == "E6" else W.SaleOrder))
            g.add((node, CRM.P17_was_motivated_by, order))
            ots = D[f"ts_{order.split('/')[-1]}"]
            g.add((order, CRM["P4_has_time-span"], ots))
            g.add((ots, RDF.type, CRM["E52_Time-Span"]))
            add_dates(g, ots, {"begin": ev["order_date"], "begin_precision": ev["order_precision"],
                               "end": ev["order_date"], "end_precision": ev["order_precision"]})
            g.add((order, W.generated_by_rule, Literal("U1")))
            g.add((order, W.source_text, Literal(ev["raw"])))
            tally[f"{kind}s"] += 1
        if ev["officer_text"]:
            g.add((node, W.officer_text, Literal(ev["officer_text"])))
        for k, st in enumerate(json.loads(ev["stations"]) if ev.get("stations") else [], 1):
            # 配属先（2026-10-09、stations_v1.py）：就役・艦長任命から :StationDeployment へ。場所は就役した港（P7）と別のノード
            dep = D[f"{ev['id']}_station{k}"]
            g.add((dep, RDF.type, W.StationDeployment))
            g.add((node, W.has_station_deployment, dep))
            g.add((dep, CRM.P12_occurred_in_the_presence_of, ship))
            pl = D[f"station_{slug(st['label'])}"]
            g.add((pl, RDF.type, CRM.E53_Place))
            g.add((pl, RDFS.label, Literal(st["label"], lang="en")))
            g.add((pl, CRM.P2_has_type, W.SeaStation))   # 沿岸警備・郵便船は役割で、配属先にしない（10/9）
            g.add((dep, CRM.P7_took_place_at, pl))
            g.add((dep, W.station_order, Literal(st["seq"], datatype=XSD.integer)))
            if st["begin"] or st["end"]:
                dts = D[f"ts_{ev['id']}_station{k}"]
                g.add((dep, CRM["P4_has_time-span"], dts))
                g.add((dts, RDF.type, CRM["E52_Time-Span"]))
                add_dates(g, dts, {"begin": st["begin"], "begin_precision": st["bp"], "end": st["end"], "end_precision": st["ep"]})
            g.add((dep, W.generated_by_rule, Literal(st["rule"])))
            g.add((dep, W.source_text, Literal(ev["raw"])))
            if st["inferred"]:
                g.add((dep, W.review_note, Literal(f"'same station' in the source: the station is taken from the previous "
                                                   f"deployment of the ship ({st['label']}); rule ST4")))
                tally["station_deployments_inferred"] += 1
            tally["station_deployments"] += 1
        g.add((node, W.generated_by_rule, Literal(ev["rules"])))
        g.add((node, W.source_text, Literal(ev["raw"])))
        if ev["status"] == "needs_review":
            g.add((node, W.review_note, Literal(ev["note"] or "see :source_text")))
        elif ev["note"]:
            g.add((node, RDFS.comment, Literal(ev["note"], lang="en")))
        tally["events"] += 1
        tally[f"events_{ev['cidoc']}"] += 1

    raw = {ev["id"]: ev["raw"] for ev in events}
    for p in presences:
        node, ship = D[p["id"]], D[p["ship"]]
        g.add((node, RDF.type, CRM.E93_Presence))
        g.add((ship, CRM.P195i_had_presence, node))
        g.add((node, W.has_service_status if p["axis"] == "service" else W.has_work_status, W[p["status"]]))
        start = as_event.get(p["start_event"])
        if p["relation"] == "during" and start:
            g.add((node, CRM.P164_is_temporally_specified_by, D[f"ts_{p['start_event']}"]))
            tally["presence_shares_event_timespan"] += 1
        else:
            ts = D[f"ts_{p['id']}"]
            g.add((node, CRM.P164_is_temporally_specified_by, ts))
            g.add((ts, RDF.type, CRM["E52_Time-Span"]))
            add_dates(g, ts, p)
            if start:
                g.add((node, CRM.P182i_starts_after_or_with_the_end_of, start))
            elif p["start_event"].startswith("completion_"):   # P15：見出しの竣工（header_v2.ttl の同じ URI）から始まる
                g.add((node, CRM.P182i_starts_after_or_with_the_end_of, D[p["start_event"]]))
                tally["presence_from_completion"] += 1
            else:
                g.add((node, W.source_text, Literal(raw.get(p["start_event"], ""))))   # 地位の印・役割の文から始まる
                tally["presence_from_statement"] += 1
            end = as_event.get(p["end_event"])
            if end:
                g.add((node, CRM.P182_ends_before_or_with_the_start_of, end))
            elif p["end_event"]:
                tally["presence_end_at_statement"] += 1
        if p["role_text"]:
            g.add((node, RDFS.comment, Literal(f"role in the source: {p['role_text']}", lang="en")))
        if p["note"]:
            g.add((node, RDFS.comment, Literal(p["note"], lang="en")))
        if p.get("review_note"):
            g.add((node, W.review_note, Literal(p["review_note"])))
            tally["presence_review_notes"] += 1
        g.add((node, W.generated_by_rule, Literal(p.get("derived") or "build_presence_v1")))   # B1r は規則で導いた値
        tally["presences"] += 1
        tally[f"presence_{p['axis']}"] += 1

    add_names(g, events, as_event, tally)
    tally["events_review_notes"] = sum(1 for ev in events if ev["status"] == "needs_review" and ev["id"] in as_event)
    os.makedirs(OUT, exist_ok=True)
    g.serialize(os.path.join(OUT, "events_v2.ttl"), format="turtle")

    summary = {"triples": len(g), **dict(tally), "undeclared_terms": undeclared_terms(g, ONTOLOGY)}
    json.dump(summary, open(os.path.join(OUT, "events_v2_summary.json"), "w"), ensure_ascii=False, indent=2)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
