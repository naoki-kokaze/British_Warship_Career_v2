"""SHACL-SPARQL 制約（sh:sparql の sh:select）を rdflib で直接実行する暫定の検査器

pySHACL を導入するまでの代わり。検査対象はシェイプの sh:targetClass のインスタンスに限り、
$this をそのインスタンスに束縛して sh:select を実行する（SHACL の SPARQL 制約と同じ意味）。
sh:sparql 以外の SHACL Core の制約（sh:minCount など）は扱わない。

使い方: python3 run_shapes_sparql.py <データ.ttl> <オントロジ.ttl> <シェイプ.ttl> [出力.csv]
依存: rdflib
"""
import csv
import logging
import sys

from rdflib import Graph, Namespace
from rdflib.namespace import RDF

logging.getLogger("rdflib").setLevel(logging.ERROR)
SH = Namespace("http://www.w3.org/ns/shacl#")


def main(data_path, onto_path, shapes_path, out_path=None):
    data = Graph()
    data.parse(data_path, format="turtle")
    data.parse(onto_path, format="turtle")   # :CostComponent などの型をオントロジから得る
    shapes = Graph()
    shapes.parse(shapes_path, format="turtle")

    rows = []
    for shape in shapes.subjects(RDF.type, SH.NodeShape):
        target = shapes.value(shape, SH.targetClass)
        severity = str(shapes.value(shape, SH.severity) or SH.Violation).split("#")[-1]
        for c in shapes.objects(shape, SH.sparql):
            prefixes = ""
            for pnode in shapes.objects(c, SH.prefixes):
                for decl in shapes.objects(pnode, SH.declare):
                    prefixes += f"PREFIX {shapes.value(decl, SH.prefix)}: <{shapes.value(decl, SH.namespace)}>\n"
            query = prefixes + str(shapes.value(c, SH.select)).replace("$this", "?this")
            message = str(shapes.value(c, SH.message))
            focus = set(data.subjects(RDF.type, target))
            for res in data.query(query):
                binding = res.asdict()
                this = binding.get("this")
                if this not in focus:
                    continue
                msg = message
                for k, v in binding.items():
                    msg = msg.replace("{?" + k + "}", str(v))
                rows.append([severity, str(shape).split("#")[-1], str(this).split("/")[-1], msg])

    rows.sort()
    for r in rows:
        print("\t".join(r))
    summary = {}
    for r in rows:
        summary[(r[0], r[1])] = summary.get((r[0], r[1]), 0) + 1
    print("\n# 集計:", {f"{k[0]} {k[1]}": v for k, v in sorted(summary.items())} or "違反なし")
    if out_path:
        with open(out_path, "w", newline="", encoding="utf-8-sig") as fh:
            w = csv.writer(fh)
            w.writerow(["severity", "shape", "focus_node", "message"])
            w.writerows(rows)


if __name__ == "__main__":
    main(*sys.argv[1:])
