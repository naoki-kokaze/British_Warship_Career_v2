"""SHACL の報告と人の判定の重なり（カメラレディ5.2・6.4。2026-10-21）

SHACL の報告は院生に見せていない（rdf_regeneration_plan §7、10/9 決定）。院生の判定のあとで、SHACL が見つけた問題と
人が見つけた問題の重なりとずれを、SHACL の検査の4分類（対応表 §11.4）ごとに出す。

4分類（§11.4。PS3 は表で①と③の両方に名前があるが、中身〔解体中は終端〕に合わせて③。PS9〔退役のない再就役、§11.5 で追加〕は③）
    ① 時間の順序：PR2〜PR5、PS4、PS5、PS7、PS8
    ② 値の検算：DM2、DM3
    ③ 状態のつながりの決まり：PS1、PS3、PS6、PS9
    ④ 構造・確認待ちの印：PR1、PR6、DM1、PS2、DM4、DM5

数え方
    - SHACL の指摘の焦点（focus）を、item_error_rates_v2.py と同じ項目に対応づける（共有のノードは参照している項目へ）
    - 項目の一致：SHACL が指摘した項目に、人が誤り（△×）を付けたか
    - 艦の一致：SHACL が指摘した艦に、人の誤りか欠落が1つでもあるか（PS8 のように焦点が艦そのもので、人は個々の出来事に
      誤りを付ける場合があるため）
    - 人の誤りのうち、SHACL の指摘がある項目の割合（SHACL がどれだけ人の誤りを覆うか）
    - 人の判定は記入のまま比べる

使い方
    python3 compare_shacl_human_v2.py <記録シートの CSV> [名前]
    出力：画面に表、../outputs/eval_v2/agreement_v2/shacl_x_<名前>.csv に SHACL の指摘ごとの照合
依存: rdflib
"""
import collections
import csv
import glob
import os
import re
import sys

from rdflib import Graph, RDF, URIRef

from item_error_rates_v2 import M, RANK, category, local, owned

HERE = os.path.dirname(os.path.abspath(__file__))
RDF_DIR = os.path.join(HERE, "../outputs/eval_v2/rdf_v2")
OUT_DIR = os.path.join(HERE, "../outputs/eval_v2/agreement_v2")
CLASSES = {
    "① 時間の順序": {"PR2", "PR3", "PR4", "PR5", "PS4", "PS5", "PS7", "PS8"},
    "② 値の検算": {"DM2", "DM3"},
    "③ 状態のつながりの決まり": {"PS1", "PS3", "PS6", "PS9"},
    "④ 構造・確認待ちの印": {"PR1", "PR6", "DM1", "PS2", "DM4", "DM5"},
}
CLASS_OF = {code: c for c, codes in CLASSES.items() for code in codes}


def main(sheet, label="人"):
    g = Graph()
    for p in glob.glob(os.path.join(RDF_DIR, "*.ttl")):
        g.parse(p)
    rows = list(csv.DictReader(open(sheet, encoding="utf-8-sig")))
    ships = sorted({r["vessel_id"] for r in rows if r["行タイプ"] == "総合判定"})
    ids = sorted(ships, key=len, reverse=True)

    items = {}
    for s in set(g.subjects(RDF.type, None)):
        if not (isinstance(s, URIRef) and str(s).startswith(M)):
            continue
        name = local(s)
        ship = next((i for i in ids if owned(name, i)), None)
        types = {str(o).split("#")[-1].split("/")[-1] for o in g.objects(s, RDF.type)}
        if ship is None or "E52_Time-Span" in types:
            continue
        items[name] = (ship, category(types, name, ship))

    def item_of(target):
        target = target.replace("myData:", "").replace(M, "")
        if target in items:
            return target
        for s in g.subjects(None, URIRef(M + target)):
            if local(s) in items:
                return local(s)
        return None

    human, human_ship = {}, collections.Counter()
    for r in rows:
        if r["行タイプ"] == "総合判定":
            continue
        t = r["対象ID"].strip()
        bad = max(RANK.get(r["軸2_スキーマ"].strip(), 0), RANK.get(r["軸3_意味"].strip(), 0))
        if t.startswith("欠落"):
            human_ship[r["vessel_id"]] += 1
            continue
        it = item_of(t)
        if it is not None and bad >= 1:
            human[it] = max(human.get(it, 0), bad)
            human_ship[items[it][0]] += 1

    flags = []
    for path in sorted(glob.glob(os.path.join(RDF_DIR, "shapes_report_*.csv"))):
        for r in csv.DictReader(open(path, encoding="utf-8-sig")):
            focus = r.get("focus") or r.get("focus_node") or ""
            m = re.match(r"([A-Z]{2}\d+):", r["message"])
            code = m.group(1) if m else "-"
            it = item_of(focus)
            ship = items[it][0] if it else next((i for i in ids if owned(focus.replace("myData:", ""), i)), None)
            if ship is None:
                continue   # 比べる艦の外
            flags.append({"class": CLASS_OF.get(code, "（未分類）"), "code": code, "severity": r["severity"],
                          "ship": ship, "item": it or "", "focus": focus, "message": r["message"],
                          "item_hit": bool(it and it in human), "ship_hit": human_ship[ship] > 0})

    print(f"## SHACL × {label}（{len(ships)}隻、人の誤りのある項目 {len(human)}、SHACL の指摘 {len(flags)}）\n")
    print("| 分類 | 指摘 | 項目 | うち人も誤り | 艦 | うち人の誤り・欠落あり |\n|---|---|---|---|---|---|")
    for c in list(CLASSES) + ["（未分類）"]:
        fs = [f for f in flags if f["class"] == c]
        if not fs:
            continue
        its = {f["item"] for f in fs if f["item"]}
        shs = {f["ship"] for f in fs}
        print(f"| {c} | {len(fs)} | {len(its)} | {sum(i in human for i in its)} | {len(shs)} "
              f"| {sum(human_ship[s] > 0 for s in shs)} |")
    flagged_items = {f["item"] for f in flags if f["item"]}
    flagged_ships = {f["ship"] for f in flags}
    covered = sum(i in flagged_items for i in human)
    covered_ship = sum(items[i][0] in flagged_ships for i in human)
    print(f"\n- 人の誤りのある項目 {len(human)} のうち、SHACL の指摘がある項目 {covered}、SHACL の指摘がある艦の項目 {covered_ship}")
    codes = collections.Counter(f["code"] for f in flags)
    print(f"- 検査ごとの指摘：{dict(sorted(codes.items()))}")

    os.makedirs(OUT_DIR, exist_ok=True)
    out = os.path.join(OUT_DIR, f"shacl_x_{label}.csv")
    with open(out, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["class", "code", "severity", "ship", "item", "focus", "item_hit", "ship_hit", "message"])
        w.writeheader()
        w.writerows(sorted(flags, key=lambda x: (x["class"], x["ship"], x["code"])))
    print(f"- SHACL の指摘ごとの照合：{os.path.relpath(out, HERE)}")


if __name__ == "__main__":
    main(*sys.argv[1:3])
