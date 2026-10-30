"""2つの記録シートの一致率（院生と2人目、人とLLM判定者など。2026-10-21）

定義（10/21、院生の判定を受け取る前に決定。docs/jinmoncom2026_llm_only_baseline_and_qa_20261019.md「院生と2人目の一致率の定義」）
    - 単位は項目。項目の定義は item_error_rates_v2.py と同じ（型の付いた myData のノード、時間の幅を除く）
      共有のノードを対象にした明細は、それを参照している項目の誤りとする。1つの項目に複数の明細があれば最も重い判定
    - 主な数字は二値（誤りあり＝△または×）。三値（○△×）の κ は参考
    - 軸3は両者が判定した艦の全項目。軸2は一覧で「全項目」の艦に限る。両軸をまとめた値は参考
    - 艦を「独立」と「照合」に分けて出す（INDEPENDENT・RECONCILED）。全体も参考に出す
    - 併記：Po、Cohen の κ、誤りありの側の一致（2a/(2a+b+c)）、2×2 の件数
    - 欠落は κ に入れず、両者の欠落の明細を艦ごとに並べて出力する（照合は人が行う）
    - 判定の基準の差は直さず、記入のまま比べる。食い違う項目は一覧（CSV）にして裁定の候補にする

使い方
    python3 compare_annotators_v2.py <シートA> <シートB> [Aの名前] [Bの名前] [出力のフォルダ]
    例: python3 compare_annotators_v2.py <院生のCSV> ../outputs/eval_v2/second_annotation_20261020/v2判定_記録シート_2人目_12隻_確定_20261021.csv 院生 2人目
    RDF は ../outputs/eval_v2/rdf_v2。両方のシートに総合判定行がある艦だけを比べる
    出力：画面に表、出力のフォルダ（既定 ../outputs/eval_v2/agreement_v2）に食い違う項目の CSV と欠落の一覧
依存: rdflib
"""
import collections
import csv
import glob
import os
import sys

from rdflib import Graph, RDF, URIRef

from item_error_rates_v2 import M, RANK, category, local, owned

HERE = os.path.dirname(os.path.abspath(__file__))
ORDER_CSV = os.path.join(HERE, "../outputs/eval_v2/eval_v2_main_order.csv")
RDF_DIR = os.path.join(HERE, "../outputs/eval_v2/rdf_v2")
OUT_DIR = os.path.join(HERE, "../outputs/eval_v2/agreement_v2")

# 2人目の判定（docs/jinmoncom2026_llm_only_baseline_and_qa_20261019.md「2人目の判定」）
# 10/23 に追加の5隻（Valiant・Sphinx・Ardent・Stork・DANUBE）を足して独立12隻（各系統2隻）
INDEPENDENT = {"AWC_9010", "PM_9024", "SL3_9162", "SBS_9193", "PSPV_9046", "SCGVG_9215", "AIF_9009",
               "SL3_9001", "SBS_9111", "PSL_9008", "SCGVG_9095", "PM_9043"}
RECONCILED = {"SBS_9113", "SCSL_9032", "PSL_9023", "SM_9026", "SL2_9043"}
MARK = {0: "○", 1: "△", 2: "×"}
# 2人目が判定の前に接触した項目は、2人目との一致から除く（10/23）
EXCLUDED_CSV = os.path.join(HERE, "../outputs/eval_v2/second_annotation_20261020/事前接触_除外項目_20261023.csv")


def kappa(a, b):
    n = len(a)
    if n == 0:
        return float("nan"), float("nan")
    po = sum(x == y for x, y in zip(a, b)) / n
    pe = sum((a.count(c) / n) * (b.count(c) / n) for c in set(a) | set(b))
    return po, (po - pe) / (1 - pe) if pe < 1 else float("nan")


def load_items(g, ships, exclude=False):
    ids = sorted(ships, key=len, reverse=True)
    items = {}
    excluded = {r["対象ID"] for r in csv.DictReader(open(EXCLUDED_CSV, encoding="utf-8-sig"))} if exclude else set()
    for s in set(g.subjects(RDF.type, None)):
        if not (isinstance(s, URIRef) and str(s).startswith(M)):
            continue
        name = local(s)
        ship = next((i for i in ids if owned(name, i)), None)
        types = {str(o).split("#")[-1].split("/")[-1] for o in g.objects(s, RDF.type)}
        if ship is None or "E52_Time-Span" in types:
            continue
        if name in excluded:
            continue
        items[name] = (ship, category(types, name, ship))
    return items


def read_sheet(path, g, items, ships):
    """項目ごとの (軸2, 軸3) の最も重い判定、明細の中身、欠落の明細、総合判定行（比べる艦の行だけ）"""
    rows = [r for r in csv.DictReader(open(path, encoding="utf-8-sig")) if r["vessel_id"] in ships]
    summary = {r["vessel_id"]: r for r in rows if r["行タイプ"] == "総合判定"}
    marks = collections.defaultdict(lambda: [0, 0])
    notes = collections.defaultdict(list)
    omissions = collections.defaultdict(list)
    unmatched = []

    def item_of(target):
        if target in items:
            return target
        for s in g.subjects(None, URIRef(M + target)):
            if local(s) in items:
                return local(s)
        return None

    for r in rows:
        if r["行タイプ"] == "総合判定":
            continue
        t = r["対象ID"].strip()
        if t.startswith("欠落"):
            omissions[r["vessel_id"]].append(f"{t}｜{r['軸3_意味']}{r['軸3_エラータイプ']}｜{r['軸3_コメント'].strip()}")
            continue
        it = item_of(t)
        if it is None:
            unmatched.append(t)
            continue
        m = marks[it]
        m[0] = max(m[0], RANK.get(r["軸2_スキーマ"].strip(), 0))
        m[1] = max(m[1], RANK.get(r["軸3_意味"].strip(), 0))
        et = "／".join(x for x in (r["軸2_エラータイプ"].strip(), r["軸3_エラータイプ"].strip()) if x)
        cm = " ".join(x for x in (r["軸2_コメント"].strip(), r["軸3_コメント"].strip()) if x)
        notes[it].append(f"[{MARK[RANK.get(r['軸2_スキーマ'].strip(), 0)]}{MARK[RANK.get(r['軸3_意味'].strip(), 0)]} {et}] {cm}")
    return summary, marks, notes, omissions, unmatched


def report(title, pairs):
    """pairs: [(Aの判定 0/1/2, Bの判定 0/1/2)]"""
    a = [x >= 1 for x, _ in pairs]
    b = [y >= 1 for _, y in pairs]
    both = sum(x and y for x, y in zip(a, b))
    only_a = sum(x and not y for x, y in zip(a, b))
    only_b = sum(y and not x for x, y in zip(a, b))
    neither = len(pairs) - both - only_a - only_b
    po, k = kappa(a, b)
    psa = 2 * both / (2 * both + only_a + only_b) if (both + only_a + only_b) else float("nan")
    _po3, k3 = kappa([x for x, _ in pairs], [y for _, y in pairs])
    print(f"| {title} | {len(pairs)} | {both} | {only_a} | {only_b} | {neither} | {po:.3f} | {k:.3f} | {psa:.3f} | {k3:.3f} |")


def main(path_a, path_b, name_a="A", name_b="B", out_dir=OUT_DIR):
    order = {r["id"]: r for r in csv.DictReader(open(ORDER_CSV, encoding="utf-8-sig"))}
    g = Graph()
    for p in glob.glob(os.path.join(RDF_DIR, "*.ttl")):
        g.parse(p)
    heads = [{r["vessel_id"] for r in csv.DictReader(open(p, encoding="utf-8-sig")) if r["行タイプ"] == "総合判定"}
             for p in (path_a, path_b)]
    ships = sorted(heads[0] & heads[1])
    items = load_items(g, ships, exclude="2人目" in (name_a, name_b))
    sa, ma, na, oa, ua = read_sheet(path_a, g, items, set(ships))
    sb, mb, nb, ob, ub = read_sheet(path_b, g, items, set(ships))
    full = {s for s in ships if order.get(s, {}).get("軸2の確認範囲") == "全項目"}

    groups = [("独立", INDEPENDENT), ("照合", RECONCILED), ("全体", set(ships))]
    print(f"## 一致率：{name_a} × {name_b}（両者が判定した艦 {len(ships)}、項目 {len(items)}）\n")
    print(f"- 独立 {len(INDEPENDENT & set(ships))}隻、照合 {len(RECONCILED & set(ships))}隻、"
          f"その他 {len(set(ships) - INDEPENDENT - RECONCILED)}隻。軸2は「全項目」の艦 {sorted(full)}")
    print(f"- 2×2 は二値（誤りあり＝△または×）。a＝両者、b＝{name_a}のみ、c＝{name_b}のみ。PSA＝2a/(2a+b+c)。κ3＝三値の κ（参考）\n")
    print("| 対象 | 項目 | a 両者 | b " + name_a + "のみ | c " + name_b + "のみ | d 両者なし | Po | κ | PSA | κ3 |")
    print("|---|---|---|---|---|---|---|---|---|---|")
    for label, group in groups:
        sel = [n for n, (s, _c) in items.items() if s in group]
        report(f"軸3・{label}", [(ma[n][1], mb[n][1]) for n in sel])
    for label, group in groups:
        sel = [n for n, (s, _c) in items.items() if s in group and s in full]
        report(f"軸2・{label}（全項目の艦）", [(ma[n][0], mb[n][0]) for n in sel])
    for label, group in groups:
        sel = [n for n, (s, _c) in items.items() if s in group]
        report(f"両軸・{label}（参考）", [(max(ma[n]), max(mb[n])) for n in sel])

    print("\n### 艦単位の総合判定（参考）\n")
    for ax in ("軸2_スキーマ", "軸3_意味"):
        same = sum(sa[s][ax].strip() == sb[s][ax].strip() for s in ships)
        print(f"- {ax}：{same}/{len(ships)} 隻で一致")

    both_bad = [n for n in items if max(ma[n]) >= 1 and max(mb[n]) >= 1]
    if both_bad:
        def types_of(notes):
            return {t for x in notes for t in x.split("] ")[0].split(" ", 1)[-1].split("／") if t}
        same_type = sum(bool(types_of(na[n]) & types_of(nb[n])) for n in both_bad)
        print(f"\n- 両者が誤りとした項目 {len(both_bad)} のうち、エラータイプが1つでも一致 {same_type}")

    os.makedirs(out_dir, exist_ok=True)
    tag = f"{name_a}_x_{name_b}"
    diff_path = os.path.join(out_dir, f"disagreements_{tag}.csv")
    with open(diff_path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["vessel_id", "区分", "項目", "群", f"{name_a}_軸2", f"{name_a}_軸3", f"{name_b}_軸2", f"{name_b}_軸3",
                    f"{name_a}_明細", f"{name_b}_明細", "裁定", "裁定のメモ"])
        for n, (s, c) in sorted(items.items(), key=lambda x: (x[1][0], x[0])):
            pa = [x >= 1 for x in ma[n]]
            pb = [x >= 1 for x in mb[n]]
            axis2_counts = s in full
            if pa[1] != pb[1] or (axis2_counts and pa[0] != pb[0]) or (not axis2_counts and any(pa) != any(pb)):
                grp = "独立" if s in INDEPENDENT else "照合" if s in RECONCILED else "その他"
                w.writerow([s, c, n, grp, MARK[ma[n][0]], MARK[ma[n][1]], MARK[mb[n][0]], MARK[mb[n][1]],
                            " ／ ".join(na[n]), " ／ ".join(nb[n]), "", ""])
    omit_path = os.path.join(out_dir, f"omissions_{tag}.md")
    with open(omit_path, "w", encoding="utf-8") as f:
        f.write(f"# 欠落の明細の照合：{name_a} × {name_b}\n\n人が照合して「両方／{name_a}のみ／{name_b}のみ」を数える。\n")
        for s in ships:
            if oa[s] or ob[s]:
                f.write(f"\n## {s} {order.get(s, {}).get('name', '')}\n\n**{name_a}**\n")
                f.write("".join(f"- {x}\n" for x in oa[s]) or "- （なし）\n")
                f.write(f"\n**{name_b}**\n")
                f.write("".join(f"- {x}\n" for x in ob[s]) or "- （なし）\n")
    print(f"\n- 欠落の明細：{name_a} {sum(len(v) for v in oa.values())}、{name_b} {sum(len(v) for v in ob.values())}（照合用：{os.path.relpath(omit_path, HERE)}）")
    print(f"- 食い違う項目の一覧：{os.path.relpath(diff_path, HERE)}")
    for name, u in ((name_a, ua), (name_b, ub)):
        u = [x for x in u if x]
        if u:
            print(f"- {name}：項目に対応しない対象ID {len(u)} {u[:8]}")


if __name__ == "__main__":
    main(*sys.argv[1:6])
