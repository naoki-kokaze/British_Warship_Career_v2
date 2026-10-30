"""v1 RDF（269隻）の機械的な棚卸し：語彙・定義域/値域・Presenceの構造・リテラル

入力（読み取りのみ）:
    ../sources/v1/ship_careers_combined.ttl
    ../sources/v1/warship_career_ontology.ttl
出力:
    ../outputs/inventory_v1/*.csv と summary.json

依存: rdflib（pip install rdflib）
計画メモ: ../docs/jinmoncom2026_rdf_regeneration_plan_20260930.md §2・§4-1
"""
import collections
import csv
import json
import logging
import os
import re

from rdflib import BNode, Graph, Literal, Namespace, URIRef
from rdflib.namespace import OWL, RDF, RDFS, XSD

logging.getLogger("rdflib").setLevel(logging.ERROR)  # 不正リテラルの警告は自前で集計する

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "../sources/v1/ship_careers_combined.ttl")
ONTO = os.path.join(HERE, "../sources/v1/warship_career_ontology.ttl")
OUT = os.path.join(HERE, "../outputs/inventory_v1")

W = Namespace("http://www.example.com/ontology/warship#")
CRM = Namespace("http://www.cidoc-crm.org/cidoc-crm/")
SEALIT = Namespace("http://www.sealitproject.eu/ontology/")
MYDATA = "http://www.example.com/myData/"

PREFIXES = {
    str(W): ":", str(CRM): "crm:", str(SEALIT): "sealit:", MYDATA: "myData:",
    str(RDFS): "rdfs:", str(RDF): "rdf:", str(OWL): "owl:", str(XSD): "xsd:",
    "http://purl.org/dc/terms/": "dcterms:",
}
# 語彙として出現頻度を数えるプロパティ（値が型の個体になるもの）
VOCAB_PROPS = [W.has_ship_type, W.has_ship_role, W.has_operational_status, W.has_propulsion_type,
               W.has_ship_rating, W.converts_into, W.changes_ship_rating, CRM.P21_had_general_purpose,
               CRM.P180_has_currency]
# 定義域/値域を検査しない（注釈的な）プロパティ
SKIP_DR = {RDF.type, RDFS.label, RDFS.comment, URIRef("http://purl.org/dc/terms/source")}
SHIP_RE = re.compile(r"([A-Z][A-Z0-9]*_\d{4})")
DATE_RE = {
    XSD.date: re.compile(r"^-?\d{4}-\d{2}-\d{2}$"),
    XSD.gYearMonth: re.compile(r"^-?\d{4}-\d{2}$"),
    XSD.gYear: re.compile(r"^-?\d{4}$"),
}


def q(term):
    """IRIを接頭辞つきで短く表す"""
    if isinstance(term, BNode):
        return "_:bnode"
    if isinstance(term, Literal):
        return f'"{term}"^^{q(term.datatype) if term.datatype else ""}'
    s = str(term)
    for ns, p in PREFIXES.items():
        if s.startswith(ns):
            return p + s[len(ns):]
    return s


def write_csv(name, header, rows):
    with open(os.path.join(OUT, name), "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


def main():
    os.makedirs(OUT, exist_ok=True)
    onto, data = Graph(), Graph()
    onto.parse(ONTO, format="turtle")
    data.parse(DATA, format="turtle")

    # ---------- オントロジの宣言 ----------
    decl_classes = set(onto.subjects(RDF.type, OWL.Class)) - {n for n in onto.subjects(RDF.type, OWL.Class) if isinstance(n, BNode)}
    decl_props = set(onto.subjects(RDF.type, OWL.ObjectProperty)) | set(onto.subjects(RDF.type, OWL.DatatypeProperty)) \
        | set(onto.subjects(RDF.type, OWL.AnnotationProperty))
    datatype_props = set(onto.subjects(RDF.type, OWL.DatatypeProperty))
    onto_individuals = {s: set(t for t in onto.objects(s, RDF.type) if t != OWL.NamedIndividual)
                        for s in onto.subjects(RDF.type, OWL.NamedIndividual)}
    superclasses = {}

    def supers(c):
        if c not in superclasses:
            acc, stack = {c}, [c]
            while stack:
                for sup in onto.objects(stack.pop(), RDFS.subClassOf):
                    if isinstance(sup, URIRef) and sup not in acc:
                        acc.add(sup)
                        stack.append(sup)
            superclasses[c] = acc
        return superclasses[c]

    domain = {p: o for p, o in onto.subject_objects(RDFS.domain)}
    range_ = {p: o for p, o in onto.subject_objects(RDFS.range)}

    def types_of(n):
        return set(data.objects(n, RDF.type)) | onto_individuals.get(n, set())

    parent_cache = {}

    def ship_of(n, depth=0):
        """ノードが属する艦IDを返す（空白ノードは親をたどる）"""
        if isinstance(n, URIRef):
            m = SHIP_RE.search(str(n))
            return m.group(1) if m else ""
        if isinstance(n, BNode) and depth < 4:
            if n not in parent_cache:
                parent_cache[n] = next(data.subjects(None, n), None)
            par = parent_cache[n]
            return ship_of(par, depth + 1) if par is not None else ""
        return ""

    ships = sorted({ship_of(s) for s in data.subjects(RDF.type, SEALIT.Ship)} - {""})
    stratum = lambda sid: sid.split("_")[0] if sid else ""

    # ---------- 1. クラスとプロパティの使用状況 ----------
    class_cnt, class_ships = collections.Counter(), collections.defaultdict(set)
    for s, t in data.subject_objects(RDF.type):
        class_cnt[t] += 1
        class_ships[t].add(ship_of(s))
    write_csv("class_usage.csv", ["class", "count", "n_ships", "declared_in_ontology"],
              [[q(c), n, len(class_ships[c] - {""}), c in decl_classes] for c, n in class_cnt.most_common()])

    prop_cnt, prop_ships = collections.Counter(), collections.defaultdict(set)
    for s, p, o in data:
        prop_cnt[p] += 1
        prop_ships[p].add(ship_of(s))
    write_csv("property_usage.csv", ["property", "count", "n_ships", "declared_in_ontology"],
              [[q(p), n, len(prop_ships[p] - {""}), p in decl_props or p in SKIP_DR]
               for p, n in prop_cnt.most_common()])

    # ---------- 2. 語彙（型の個体）の出現頻度 ----------
    vocab_rows = []
    for p in VOCAB_PROPS:
        cnt, shp = collections.Counter(), collections.defaultdict(set)
        for s, o in data.subject_objects(p):
            cnt[o] += 1
            shp[o].add(ship_of(s))
        for o, n in cnt.most_common():
            if o in onto_individuals:
                origin = "ontology"
            elif set(data.objects(o, RDF.type)):
                origin = "data-local"  # データ内で型宣言されたad hocな個体
            else:
                origin = "undefined"
            label = next(data.objects(o, RDFS.label), next(onto.objects(o, RDFS.label), ""))
            strata = sorted({stratum(x) for x in shp[o]} - {""})
            vocab_rows.append([q(p), q(o), str(label), n, len(shp[o] - {""}), origin, " ".join(strata)])
    write_csv("vocab_usage.csv", ["property", "value", "label", "count", "n_ships", "origin", "strata"], vocab_rows)

    # ---------- 3. 定義域・値域 ----------
    dr_detail = []
    for s, p, o in data:
        if p in SKIP_DR or p not in decl_props:
            continue
        for side, node, expected in (("domain", s, domain.get(p)), ("range", o, range_.get(p))):
            if expected is None or expected == RDFS.Literal:
                continue
            if isinstance(node, Literal):
                if p not in datatype_props:
                    dr_detail.append([ship_of(s), q(s), q(p), q(o), side, q(expected), "literal", "literal_for_object_property"])
                continue
            ts = types_of(node)
            if not ts:
                issue = "untyped_node"
            elif any(expected in supers(t) for t in ts):
                continue
            elif all(t not in decl_classes and t not in {expected} for t in ts) and \
                    not any(t in decl_classes for t in ts):
                issue = "undeclared_type"  # 型がオントロジ未宣言なので適否を判定できない
            else:
                issue = "violation"
            dr_detail.append([ship_of(s), q(s), q(p), q(o), side, q(expected),
                              " ".join(sorted(q(t) for t in ts)), issue])
    write_csv("domain_range_detail.csv",
              ["ship", "subject", "property", "object", "side", "expected", "actual_types", "issue"], dr_detail)
    agg = collections.defaultdict(lambda: [0, set()])
    for ship, _s, p, _o, side, exp, act, issue in dr_detail:
        k = (p, side, exp, act, issue)
        agg[k][0] += 1
        agg[k][1].add(ship)
    write_csv("domain_range_summary.csv",
              ["property", "side", "expected", "actual_types", "issue", "count", "n_ships"],
              sorted(([*k, v[0], len(v[1] - {""})] for k, v in agg.items()), key=lambda r: -r[5]))

    # ---------- 4. P195i の向き ----------
    p195 = collections.Counter()
    for s, o in data.subject_objects(CRM.P195i_had_presence):
        ts, to = types_of(s), types_of(o)
        if SEALIT.Ship in ts and CRM.E93_Presence in to:
            p195["Ship→Presence（オントロジどおり）"] += 1
        elif CRM.E93_Presence in ts and SEALIT.Ship in to:
            p195["Presence→Ship（逆向き）"] += 1
        else:
            p195["その他"] += 1

    # ---------- 5. リテラル（日付の型と値の整合） ----------
    lit_rows = []
    for s, p, o in data:
        if isinstance(o, Literal) and o.datatype in DATE_RE and not DATE_RE[o.datatype].match(str(o)):
            lit_rows.append([ship_of(s), q(p), str(o), q(o.datatype), "value_does_not_match_datatype"])
        elif isinstance(o, Literal) and getattr(o, "ill_typed", False):
            lit_rows.append([ship_of(s), q(p), str(o), q(o.datatype), "ill_typed"])
    write_csv("literal_issues.csv", ["ship", "property", "value", "datatype", "issue"], lit_rows)

    # ---------- 6. Presence の構造と期間 ----------
    def bounds(lit):
        """日付リテラル → (最早, 最遅) の 'YYYY-MM-DD' 文字列"""
        s = str(lit)
        m = re.match(r"^(\d{4})(?:-(\d{2}))?(?:-(\d{2}))?", s)
        if not m:
            return None
        y, mo, d = m.group(1), m.group(2), m.group(3)
        if d:
            return (f"{y}-{mo}-{d}",) * 2
        if mo:
            return (f"{y}-{mo}-01", f"{y}-{mo}-31")
        return (f"{y}-01-01", f"{y}-12-31")

    def ts_point(ts, which):
        """Time-Span の始点/終点（P79/P80、なければP82）"""
        pref = [CRM.P79_beginning_is_qualified_by, CRM.P82_at_some_time_within, CRM.P80_end_is_qualified_by] \
            if which == "begin" else [CRM.P80_end_is_qualified_by, CRM.P82_at_some_time_within, CRM.P79_beginning_is_qualified_by]
        for p in pref:
            v = next(data.objects(ts, p), None)
            if v is not None:
                return bounds(v)
        return None

    def event_point(ev, which):
        ts = next(data.objects(ev, CRM["P4_has_time-span"]), None)
        return ts_point(ts, which) if ts is not None else None

    pres_rows, pres_by_ship = [], collections.defaultdict(list)
    presences = set(data.subjects(RDF.type, CRM.E93_Presence))
    for pr in presences:
        sid = ship_of(pr)
        statuses = list(data.objects(pr, W.has_operational_status))
        if len(statuses) != 1:
            pres_rows.append([sid, q(pr), f"status_count={len(statuses)}", " ".join(q(x) for x in statuses)])
        if next(data.objects(pr, W.has_ship_role), None) is not None and next(data.objects(pr, W.has_ship_type), None) is not None:
            pres_rows.append([sid, q(pr), "role_and_type_together", ""])
        ts = next(data.objects(pr, CRM.P164_is_temporally_specified_by), None)
        if ts is None:
            pres_rows.append([sid, q(pr), "no_time_span", ""])
            continue
        b = bounds(next(data.objects(ts, CRM.P79_beginning_is_qualified_by), None) or "") \
            if next(data.objects(ts, CRM.P79_beginning_is_qualified_by), None) is not None else None
        if b is None:
            ev = next(data.objects(ts, CRM.P182i_starts_after_or_with_the_end_of), None)
            b = event_point(ev, "end") if ev is not None else None
        e = bounds(next(data.objects(ts, CRM.P80_end_is_qualified_by))) \
            if next(data.objects(ts, CRM.P80_end_is_qualified_by), None) is not None else None
        if e is None:
            ev = next(data.objects(ts, CRM.P182_ends_before_or_with_the_start_of), None)
            e = event_point(ev, "begin") if ev is not None else None
        if b and e and b[0] > e[1]:
            pres_rows.append([sid, q(pr), "reversed_interval", f"begin={b[0]} end={e[1]}"])
        status = q(statuses[0]) if statuses else ""
        pres_by_ship[sid].append((b, e, pr, status))
    # 同じ艦の Presence どうしの重なり（確実に重なるものだけ。区間が反転したものは除く）
    # 日付の精度が月・年の場合は、その月・年の初日〜末日（月末は一律31日）の幅で比較する
    for sid, lst in pres_by_ship.items():
        dated = sorted([x for x in lst if x[0] and x[1] and x[0][0] <= x[1][1]], key=lambda x: x[0][0])
        for (b1, e1, p1, s1), (b2, e2, p2, s2) in zip(dated, dated[1:]):
            if b2[1] < e1[0]:
                pres_rows.append([sid, q(p2), "overlaps_previous", f"{q(p1)}({s1}) ~{e1[0]} / {s2} from {b2[1]}"])
    write_csv("presence_issues.csv", ["ship", "presence", "issue", "detail"], sorted(pres_rows))

    # ---------- 7. 層別の集計 ----------
    by_stratum = collections.defaultdict(lambda: collections.Counter())
    ships_with = collections.defaultdict(lambda: collections.defaultdict(set))
    for sid in ships:
        by_stratum[stratum(sid)]["ships"] += 1
    for pr in presences:
        by_stratum[stratum(ship_of(pr))]["presences"] += 1
    for row in dr_detail:
        if row[7] in ("violation", "undeclared_type"):
            ships_with[stratum(row[0])][f"{row[2]} {row[4]} {row[7]}"].add(row[0])
    for row in pres_rows:
        ships_with[stratum(row[0])][row[2].split("=")[0]].add(row[0])
    issue_keys = sorted({k for d in ships_with.values() for k in d})
    write_csv("stratum_summary.csv", ["stratum", "ships", "presences"] + [f"n_ships: {k}" for k in issue_keys],
              [[st, c["ships"], c["presences"]] + [len(ships_with[st][k]) for k in issue_keys]
               for st, c in sorted(by_stratum.items())])

    # ---------- 要約 ----------
    origin_cnt = collections.Counter()
    for p, _v, _l, n, _ns, origin, _st in vocab_rows:
        origin_cnt[(p, origin)] += n
    summary = {
        "triples": len(data),
        "ships": len(ships),
        "presences": len(presences),
        "strata": len(by_stratum),
        "undeclared_classes_used": {q(c): n for c, n in class_cnt.items() if c not in decl_classes},
        "undeclared_properties_used": {q(p): n for p, n in prop_cnt.items() if p not in decl_props and p not in SKIP_DR},
        "vocab_origin_counts": {f"{p} [{o}]": n for (p, o), n in sorted(origin_cnt.items())},
        "P195i_direction": dict(p195),
        "domain_range_issue_counts": dict(collections.Counter(r[7] for r in dr_detail)),
        "literal_issues": len(lit_rows),
        "presence_issue_counts": dict(collections.Counter(r[2].split("=")[0] if r[2].startswith("status_count") else r[2] for r in pres_rows)),
        "presence_issue_ships": {k: len({r[0] for r in pres_rows if r[2].startswith(k)})
                                 for k in ("status_count", "role_and_type_together", "no_time_span", "reversed_interval", "overlaps_previous")},
    }
    with open(os.path.join(OUT, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
