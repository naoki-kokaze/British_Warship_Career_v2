"""v1 の系統的な誤りが v2 で解消したかの確認（カメラレディ3.3・査読A3。2026-10-21）

3.3 で開示した v1 の誤りを、v2 の RDF に同じ形の問いで当てて件数を数える（0件なら解消）。
    1. 状態の期間（crm:E93_Presence）に crm:P7_took_place_at（v1：410件・64隻）
    2. 艦種・推進方式（:has_ship_type・:has_propulsion_type）を艦そのもの（sealit:Ship）に直接付ける（v1：266〜267隻）
    3. :has_ship_type の値がオントロジーで定義されていない（v1：923件のうち623件）
    4. 日付の記録に crm:P79・crm:P80（時間幅の始まり・終わりについての注記）を用いる（v1：1,784件）。v2 は日付を P81・P82 に置き、
       P79・P80 は原文の「?」などの注記の文字列に使う（convert_header_v2.py の方針）ので、値が日付のものだけを誤りとして数え、
       注記としての使用は（参考）に出す
あわせて、v2 での :has_ship_type・:has_propulsion_type の使用件数を出す（0件の理由が「使っていないから」かどうかを見分ける）

使い方: python3 check_v1_systematic_errors_v2.py   （開発用 outputs/rdf_v2 と評価用 outputs/eval_v2/rdf_v2 の両方）
依存: rdflib
"""
import glob
import os
import re

from rdflib import Graph, Namespace, RDF

HERE = os.path.dirname(os.path.abspath(__file__))
ONTOLOGY = os.path.join(HERE, "../outputs/ontology_v2/warship_career_ontology_v2.ttl")
DATASETS = {"開発用": os.path.join(HERE, "../outputs/rdf_v2"), "評価用": os.path.join(HERE, "../outputs/eval_v2/rdf_v2")}
CRM = Namespace("http://www.cidoc-crm.org/cidoc-crm/")
W = Namespace("http://www.example.com/ontology/warship#")
SEALIT = Namespace("http://www.sealitproject.eu/ontology/")


def is_date(o):
    dt = str(getattr(o, "datatype", "") or "")
    return dt.endswith(("#date", "#dateTime", "#gYear", "#gYearMonth")) or bool(re.fullmatch(r"\d{4}(-\d{2}){0,2}", str(o)))


def main():
    onto = Graph().parse(ONTOLOGY)
    ship_type_values = set(onto.subjects(RDF.type, W.ShipType))
    print("| 確認 | v1 | " + " | ".join(DATASETS) + " |\n|---|---|" + "---|" * len(DATASETS))
    results = {}
    for name, d in DATASETS.items():
        g = Graph()
        for p in glob.glob(os.path.join(d, "*.ttl")):
            g.parse(p)
        presences = set(g.subjects(RDF.type, CRM.E93_Presence))
        ships = set(g.subjects(RDF.type, SEALIT.Ship))
        st = list(g.subject_objects(W.has_ship_type))
        pt = list(g.subject_objects(W.has_propulsion_type))
        results[name] = [
            sum(1 for s in presences for _ in g.objects(s, CRM.P7_took_place_at)),
            len({s for s, _ in st + pt if s in ships}),
            sum(1 for _s, o in st if o not in ship_type_values),
            sum(1 for p in (CRM.P79_beginning_is_qualified_by, CRM.P80_end_is_qualified_by)
                for _s, o in g.subject_objects(p) if is_date(o)),
            f"{len(st)}／{len(pt)}",
            sum(1 for p in (CRM.P79_beginning_is_qualified_by, CRM.P80_end_is_qualified_by)
                for _s, o in g.subject_objects(p) if not is_date(o)),
        ]
    labels = [("1. 状態の期間に P7", "410件・64隻"), ("2. 艦種・推進方式を艦に直接（艦の数）", "266〜267隻"),
              ("3. :has_ship_type の未定義の値", "623/923件"), ("4. 日付に P79・P80", "1,784件"),
              ("（参考）:has_ship_type／:has_propulsion_type の使用件数", "—"),
              ("（参考）P79・P80 の注記としての使用（値が日付でない）", "—")]
    for i, (lab, v1) in enumerate(labels):
        print(f"| {lab} | {v1} | " + " | ".join(str(results[n][i]) for n in DATASETS) + " |")


if __name__ == "__main__":
    main()
