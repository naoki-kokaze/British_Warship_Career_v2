"""配属先の表記（原文どおり）と、歴史的なステーションへのまとめの案の対応表を作る（2026-10-09）

入力: ../outputs/rules_v1/events.csv（開発用）、../outputs/eval_v2/rules_v1/events.csv（評価用）の stations 列
出力: ../outputs/station_labels_v2.csv
    label            RDF に入る表記（原文どおり。myData:station_<表記> の rdfs:label）
    kind             sea / coastguard / packet
    proposed_station まとめの案（stations_v1.py の GAZETTEER。ユーザーの確認待ち。RDF には入れない）
    n_dev / n_eval   出現数（"on same station" で補ったもの・"all" で写したものを含む）
    confirmed_station / note  ユーザーの記入欄（確認後、sources/manual/ へ移して分析で使う）
"""
import collections
import csv
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = {"dev": "../outputs/rules_v1/events.csv", "eval": "../outputs/eval_v2/rules_v1/events.csv"}
OUT = os.path.join(HERE, "../outputs/station_labels_v2.csv")

rows, n = {}, collections.Counter()
for tag, path in SRC.items():
    for e in csv.DictReader(open(os.path.join(HERE, path), encoding="utf-8-sig")):
        for st in json.loads(e["stations"]) if e.get("stations") else []:
            key = st["label"].lower()
            rows.setdefault(key, {"label": st["label"], "kind": st["kind"], "proposed_station": st["proposed"]})
            n[(key, tag)] += 1
with open(OUT, "w", newline="", encoding="utf-8-sig") as f:
    w = csv.DictWriter(f, fieldnames=["label", "kind", "proposed_station", "n_dev", "n_eval", "confirmed_station", "note"])
    w.writeheader()
    for key, r in sorted(rows.items(), key=lambda x: (x[1]["kind"], x[1]["proposed_station"], -n[(x[0], "dev")] - n[(x[0], "eval")])):
        w.writerow(r | {"n_dev": n[(key, "dev")], "n_eval": n[(key, "eval")], "confirmed_station": "", "note": ""})
print(len(rows), "labels ->", OUT)
