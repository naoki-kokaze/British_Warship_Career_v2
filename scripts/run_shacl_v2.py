"""v2 の RDF を pySHACL で検査し、結果を CSV にする

使い方: python3 run_shacl_v2.py <シェイプ.ttl> <出力.csv> <データ.ttl> [<データ.ttl> ...]
    オントロジ（../outputs/ontology_v2/warship_career_ontology_v2.ttl）は常にデータに加える（クラスの型を得るため）
例:     python3 run_shacl_v2.py ../outputs/ontology_v2/shapes_events_v2.ttl ../outputs/rdf_v2/shapes_report_events_v2.csv \
            ../outputs/rdf_v2/header_v2.ttl ../outputs/rdf_v2/events_v2.ttl
依存: rdflib, pyshacl（サンドボックスの外で実行）
"""
import collections
import csv
import os
import sys

from pyshacl import validate
from rdflib import Graph, Namespace
from rdflib.namespace import RDF

HERE = os.path.dirname(os.path.abspath(__file__))
ONTOLOGY = os.path.join(HERE, "../outputs/ontology_v2/warship_career_ontology_v2.ttl")
SH = Namespace("http://www.w3.org/ns/shacl#")


def main(shapes_path, out_path, *data_paths):
    data = Graph()
    for p in (*data_paths, ONTOLOGY):
        data.parse(p, format="turtle")
    shapes = Graph().parse(shapes_path, format="turtle")
    conforms, report, text = validate(data, shacl_graph=shapes, inference="none", abort_on_first=False)
    if not isinstance(report, Graph):   # シェイプの誤りなど（pySHACL の ValidationFailure）
        sys.exit(f"pySHACL could not validate: {report}")
    rows = []
    for r in report.subjects(RDF.type, SH.ValidationResult):
        rows.append({
            "severity": report.value(r, SH.resultSeverity).split("#")[-1],
            "shape": str(report.value(r, SH.sourceShape)).split("#")[-1],
            "focus": data.namespace_manager.normalizeUri(report.value(r, SH.focusNode)),
            "message": str(report.value(r, SH.resultMessage)),
        })
    rows.sort(key=lambda x: (x["shape"], x["focus"], x["message"]))
    with open(out_path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["severity", "shape", "focus", "message"])
        w.writeheader()
        w.writerows(rows)
    print("conforms:", conforms)
    for (shape, sev), n in sorted(collections.Counter((x["shape"], x["severity"]) for x in rows).items()):
        print(f"  {shape} ({sev}): {n}")


if __name__ == "__main__":
    main(*sys.argv[1:])
