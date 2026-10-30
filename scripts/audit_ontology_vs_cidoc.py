"""オントロジ（v1 または v2）の CIDOC CRM 用語の宣言を、CIDOC CRM 公式の RDFS（7.1.3）と照合する

入力（読み取りのみ）:
    ../sources/reference/CIDOC_CRM_v7.1.3.rdf（公式）
    照合するオントロジ（既定: ../sources/v1/warship_career_ontology.ttl）
出力:
    ../outputs/ontology_audit/<名前>_audit.csv と標準出力

判定（定義域・値域・上位クラス・上位プロパティのそれぞれについて）
    same        公式と同じ
    narrower    公式より狭い（公式の下位クラスを指定）。RDFSでは「このプロパティを使うものは狭いクラスに属する」
                と推論されるので、CIDOCの意味をこのオントロジの中で狭めていることになる
    broader     公式より広い。公式の制約を緩めている
    unrelated   公式と包含関係にない
    incomplete  上位クラスが公式の祖先ではあるが、直接の親を飛ばしている（矛盾ではない）
    not_in_crm  公式に存在しない用語
独自の用語（: 名前空間）が CIDOC の用語の下位にある場合は、独自の定義域・値域が上位の公式の定義域・値域に
収まっているかを調べる。

使い方: python3 audit_ontology_vs_cidoc.py [オントロジ.ttl] [出力名]
依存: rdflib
"""
import csv
import logging
import os
import sys

from rdflib import Graph, Namespace, URIRef
from rdflib.namespace import OWL, RDF, RDFS

logging.getLogger("rdflib").setLevel(logging.ERROR)

HERE = os.path.dirname(os.path.abspath(__file__))
CRM_FILE = os.path.join(HERE, "../sources/reference/CIDOC_CRM_v7.1.3.rdf")
CRM = Namespace("http://www.cidoc-crm.org/cidoc-crm/")
W = "http://www.example.com/ontology/warship#"


def short(t):
    s = str(t)
    for ns, p in [(str(CRM), "crm:"), (W, ":"), ("http://www.sealitproject.eu/ontology/", "sealit:"),
                  (str(RDFS), "rdfs:"), (str(OWL), "owl:"), ("http://www.w3.org/2001/XMLSchema#", "xsd:")]:
        if s.startswith(ns):
            return p + s[len(ns):]
    return s


def closure(g, node, pred):
    acc, stack = {node}, [node]
    while stack:
        for sup in g.objects(stack.pop(), pred):
            if isinstance(sup, URIRef) and sup not in acc:
                acc.add(sup)
                stack.append(sup)
    return acc


def main(onto_path=None, name=None):
    onto_path = onto_path or os.path.join(HERE, "../sources/v1/warship_career_ontology.ttl")
    name = name or os.path.splitext(os.path.basename(onto_path))[0]
    crm = Graph().parse(CRM_FILE, format="xml")
    onto = Graph().parse(onto_path, format="turtle")

    crm_classes = set(crm.subjects(RDF.type, RDFS.Class))
    crm_props = set(crm.subjects(RDF.type, RDF.Property))

    def up_class(c):
        """公式の階層での祖先（公式にないクラスは、照合中のオントロジでの上位クラスをたどってから公式の階層へ）"""
        acc = set()
        for x in closure(onto, c, RDFS.subClassOf) if c not in crm_classes else {c}:
            acc |= closure(crm, x, RDFS.subClassOf) if x in crm_classes else {x}
        return acc

    def relation(local, official):
        if local == official:
            return "same"
        if official in up_class(local):
            return "narrower"
        if local in crm_classes and local in closure(crm, official, RDFS.subClassOf):
            return "broader"
        return "unrelated"

    rows = []
    # CIDOC のプロパティ
    for p in sorted(set(onto.subjects(RDF.type, OWL.ObjectProperty)) | set(onto.subjects(RDF.type, OWL.DatatypeProperty))):
        if not str(p).startswith(str(CRM)):
            continue
        if p not in crm_props:
            rows.append([short(p), "property", "existence", "", "", "not_in_crm"])
            continue
        for kind, pred in (("domain", RDFS.domain), ("range", RDFS.range)):
            off = crm.value(p, pred)
            for loc in onto.objects(p, pred):
                rel = relation(loc, off) if off is not None else "official_undefined"
                rows.append([short(p), "property", kind, short(loc), short(off), rel])
        for sup in onto.objects(p, RDFS.subPropertyOf):
            if sup == OWL.topObjectProperty or sup == OWL.topDataProperty:
                continue
            rel = "same" if sup in closure(crm, p, RDFS.subPropertyOf) else "not_official_superproperty"
            rows.append([short(p), "property", "subPropertyOf", short(sup), "", rel])
    # CIDOC のクラス
    for c in sorted(set(onto.subjects(RDF.type, OWL.Class))):
        if not str(c).startswith(str(CRM)):
            continue
        if c not in crm_classes:
            rows.append([short(c), "class", "existence", "", "", "not_in_crm"])
            continue
        direct = set(crm.objects(c, RDFS.subClassOf))
        for sup in onto.objects(c, RDFS.subClassOf):
            if not isinstance(sup, URIRef):
                continue
            anc = closure(crm, c, RDFS.subClassOf)
            rel = "same" if sup in direct else "incomplete" if sup in anc else "unrelated"
            rows.append([short(c), "class", "subClassOf", short(sup), " ".join(sorted(short(x) for x in direct)), rel])
    # 独自の用語・他の名前空間の用語で、CIDOC の下位にあるもの
    for p in sorted(set(onto.subjects(RDF.type, OWL.ObjectProperty))):
        if str(p).startswith(str(CRM)):
            continue
        for sup in onto.objects(p, RDFS.subPropertyOf):
            if not str(sup).startswith(str(CRM)) or sup not in crm_props:
                if str(sup).startswith(str(CRM)):
                    rows.append([short(p), "custom_property", "subPropertyOf", short(sup), "", "superproperty_not_in_crm"])
                continue
            for kind, pred in (("domain", RDFS.domain), ("range", RDFS.range)):
                off = crm.value(sup, pred)
                for loc in onto.objects(p, pred):
                    rel = relation(loc, off) if off is not None else "official_undefined"
                    ok = "fits" if rel in ("same", "narrower") else rel
                    rows.append([short(p), "custom_property", f"{kind} (vs super {short(sup)})", short(loc), short(off), ok])
    for c in sorted(set(onto.subjects(RDF.type, OWL.Class))):
        if str(c).startswith(str(CRM)):
            continue
        for sup in onto.objects(c, RDFS.subClassOf):
            if isinstance(sup, URIRef) and str(sup).startswith(str(CRM)):
                rows.append([short(c), "custom_class", "subClassOf", short(sup), "", "in_crm" if sup in crm_classes else "superclass_not_in_crm"])

    out_dir = os.path.join(HERE, "../outputs/ontology_audit")
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, f"{name}_audit.csv"), "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(["term", "kind", "aspect", "local", "official", "result"])
        w.writerows(rows)
    for r in rows:
        if r[5] not in ("same", "fits", "in_crm"):
            print("\t".join(r))
    print(f"\n# {len(rows)} 件を照合。問題なし（same/fits/in_crm）以外を上に表示")


if __name__ == "__main__":
    main(*sys.argv[1:])
