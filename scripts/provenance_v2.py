"""v2 の RDF の出所の割合：規則（原文から直接）／規則（推測を含む）／LLM（2026-10-20）

カメラレディ4章・6章用。v1 は全体が LLM の生成なので、v2 のどれだけが LLM の推論を経ずに作られたかを示す。

入力（読み取りのみ）: <データセット>/rdf_v2/header_v2.ttl・events_v2.ttl、評価用は ../outputs/eval_v2/eval_v2_main_order.csv
出力: <データセット>/provenance_v2/provenance_by_record.csv  … 艦の範囲・単位（記録／トリプル）・出所ごとの件数
      <データセット>/provenance_v2/summary.json

出所の分け方（:generated_by_rule の値で決める）
- llm            : "LLM:<モデル>:<プロンプトの版>" で始まる（規則で処理しきれなかった節の候補。評価用は案bで人の確認なし）
- rule_inferred  : 推測を含む規則。B1r（任地つきの艦長任命から就役中を導く）、ST4（same station を直前の配属先で補う）、
                   ST7（all in the X を前の就役に写す）、寸法（crm:E54_Dimension）の F2（bm の式で一意に決めた値。
                   見出しの F2「Completed D」は推測ではないので含めない）
- rule_direct    : それ以外の規則
記録＝:generated_by_rule を持つノード。トリプルは、主語の記録に帰属させる（時間幅などの空白ノード・ts_/amount_ のノードは
親の記録へ）。どの記録にも帰属しないもの（艦・場所・名前など共有のノード）は shared として別に数える。
状態の期間を「次の出来事まで続く」とする規則 P2 は、Presence の組み立て全体に掛かる暗黙の推測なので、ここでは分けない
（論文で別に述べる）。

使い方: JINMON_DATASET=eval_v2 python3 provenance_v2.py   （開発用は JINMON_DATASET を付けない）
"""
import collections
import csv
import json
import os
import re
import sys

from rdflib import BNode, Graph, Namespace, URIRef
from rdflib.namespace import RDF

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import dataset_paths as P   # 開発用／評価用の切り替え（JINMON_DATASET）

W = Namespace("http://www.example.com/ontology/warship#")
CRM = Namespace("http://www.cidoc-crm.org/cidoc-crm/")
RDF_DIR = P.out("rdf_v2")
OUT = P.out("provenance_v2")
MAIN_ORDER = os.path.join(HERE, "../outputs/eval_v2/eval_v2_main_order.csv")
INFERRED = {"B1r", "ST4", "ST7"}
SHIP = re.compile(r"([A-Z][A-Z0-9]*_\d{4})")
SOURCES = ("rule_direct", "rule_inferred", "llm")


def classify(rule, node, g):
    if rule.startswith("LLM:"):
        return "llm"
    tokens = set(rule.split())
    if tokens & INFERRED or ("F2" in tokens and (node, RDF.type, CRM.E54_Dimension) in g):
        return "rule_inferred"
    return "rule_direct"


def name(node):
    return str(node).rsplit("/", 1)[-1]


def main():
    g = Graph()
    for f in ("header_v2.ttl", "events_v2.ttl"):
        g.parse(os.path.join(RDF_DIR, f))
    source = {s: classify(str(o), s, g) for s, o in g.subject_objects(W.generated_by_rule)}
    parent = {o: s for s, o in g.subject_objects() if isinstance(o, BNode)}

    def owner(s):
        seen = set()
        while isinstance(s, BNode) and s in parent and s not in seen:
            seen.add(s)
            s = parent[s]
        if s in source:
            return s
        if isinstance(s, URIRef):
            m = re.match(r"^(?:ts|amount)_(.+)$", name(s))
            if m:
                cand = URIRef(str(s).rsplit("/", 1)[0] + "/" + m.group(1))
                if cand in source:
                    return cand
        return None

    def ship_of(node):
        m = SHIP.search(name(node))
        return m.group(1) if m else None

    scopes = {"all": None}
    if P.DATASET == "eval_v2":
        rows = list(csv.DictReader(open(MAIN_ORDER, encoding="utf-8-sig")))
        scopes["main30"] = {r["id"] for r in rows if r["tier"] in ("必須", "追加")}

    records = collections.Counter()
    triples = collections.Counter()
    for s in source:
        records[(ship_of(s), source[s])] += 1
    for s, p, o in g:
        own = owner(s)
        if own is not None:
            triples[(ship_of(own), source[own])] += 1
        else:
            node = s
            while isinstance(node, BNode) and node in parent:
                node = parent[node]
            triples[(ship_of(node), "shared")] += 1

    os.makedirs(OUT, exist_ok=True)
    summary, out_rows = {}, []
    for scope, ships in scopes.items():
        for unit, counter, kinds in (("records", records, SOURCES), ("triples", triples, SOURCES + ("shared",))):
            c = collections.Counter()
            for (ship, src), n in counter.items():
                if ships is None or ship in ships:
                    c[src] += n
            total = sum(c[k] for k in kinds)
            marked = sum(c[k] for k in SOURCES)
            summary.setdefault(scope, {})[unit] = {k: c[k] for k in kinds} | {"total": total}
            for k in kinds:
                out_rows.append([scope, unit, k, c[k], f"{100 * c[k] / total:.2f}",
                                 f"{100 * c[k] / marked:.2f}" if k in SOURCES else ""])
    with open(os.path.join(OUT, "provenance_by_record.csv"), "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["scope", "unit", "source", "count", "pct_of_total", "pct_of_marked"])
        w.writerows(out_rows)
    trace = llm_trace(g, scopes)
    for scope in scopes:
        summary[scope]["llm_trace"] = trace[scope]
    json.dump(summary, open(os.path.join(OUT, "summary.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    for r in out_rows:
        print(*r, sep="\t")
    for scope, t in trace.items():
        print(f"\n[{scope}] LLM の行の行き先：{json.dumps({k: v for k, v in t.items() if k != 'detail'}, ensure_ascii=False)}")
        for d in t["detail"]:
            print("  ", d)


def llm_trace(g, scopes):
    """統合した LLM の行が RDF のどこに残ったか（表2の注用。2026-10-21）

    出来事のノードにならない種類（(role)・(status)）は、状態の期間だけになるか（出所の印は build_presence_v1）、
    地位を変えない役割（role_seagoing）なら規則 P9 により何も残らない。LLM の出来事から始まる・で終わる状態の期間も、
    出所の印は規則（build_presence_v1）になる。表2の区分は変えず、ここで件数を数えて注に書く
    """
    events = [r for r in csv.DictReader(open(P.out("rules_v1/events.csv"), encoding="utf-8-sig"))
              if r["rules"].startswith("LLM:")]
    presences = list(csv.DictReader(open(P.out("rules_v1/presences.csv"), encoding="utf-8-sig")))
    base = "http://www.example.com/myData/"
    in_rdf = {name(s) for s in g.subjects(RDF.type, None) if str(s).startswith(base)}
    llm_ids = {r["id"] for r in events}
    out = {}
    for scope, ships in scopes.items():
        sel = [r for r in events if ships is None or r["ship"] in ships]
        started = [p for p in presences if p["start_event"] in llm_ids and p["id"] in in_rdf
                   and (ships is None or p["ship"] in ships)]
        ended = [p for p in presences if p["end_event"] in llm_ids and p["start_event"] not in llm_ids
                 and p["id"] in in_rdf and (ships is None or p["ship"] in ships)]
        t = {"llm_rows_merged": len(sel), "event_nodes": 0, "presence_only": 0, "not_represented": 0,
             "presences_started_by_llm_event": 0, "presences_ended_by_llm_event": len(ended), "detail": []}
        for r in sel:
            if r["id"] in in_rdf:
                t["event_nodes"] += 1
            elif any(p["start_event"] == r["id"] for p in started):
                t["presence_only"] += 1
                t["detail"].append(f"状態の期間だけ：{r['id']}（{r['type']} {r['status_effect']}）")
            else:
                t["not_represented"] += 1
                t["detail"].append(f"RDF にない：{r['id']}（{r['type']} {r['status_effect']}）")
        node_ids = {r["id"] for r in sel if r["id"] in in_rdf}
        t["presences_started_by_llm_event"] = sum(p["start_event"] in node_ids for p in started)
        t["detail"] += [f"LLM の出来事から始まる期間：{p['id']}" for p in started if p["start_event"] in node_ids]
        t["detail"] += [f"LLM の出来事で終わる期間：{p['id']}" for p in ended]
        out[scope] = t
    return out


if __name__ == "__main__":
    main()
