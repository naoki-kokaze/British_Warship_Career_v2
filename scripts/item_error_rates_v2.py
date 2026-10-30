"""判定の明細から、項目単位の誤りの率を出す（v2 と比較用の RDF に同じ物差しを当てる。2026-10-20）

定義（10/19 ユーザー確認、10/20 に型で分類する形に整理）
    - 項目：その艦に属する、型の付いた myData のノード（時間の幅 E52 を除く）。v2 では艦ごとの一覧の行と一致する
    - 誤りのある項目：明細で軸2か軸3が△または×の項目。1つの項目に複数の明細があっても1件（最も重い判定）
      共有のノード（業者名など）を対象にした明細は、それを参照している項目の誤りとする
    - 欠落：対象IDが「欠落：」「欠落（配属先）：」の明細。RDF にないので分母に入れず、別に数える
    - 区分は型で決める（状態の期間・配属先・艦長の任命・寸法・計測・費用・金額・名前・艦・出来事）
    - 出所：:generated_by_rule が LLM: で始まる項目は LLM 由来（v2 のみ意味がある）
    - 系統：eval_v2_selection.csv の group（A〜F）。系統ごとに同数を抽出したので、全体の率は母集団の推定値ではない
      （カメラレディ5.1）。系統別の率と、系統の重みを等しくした率（系統の率の平均）を併せて出す（10/21 追加）
    - 軸2の確認範囲：eval_v2_main_order.csv の「軸2の確認範囲」で、全項目の艦と気づいた場合のみの艦の軸2の誤りの率を比べる。
      見落としの割合の目安 ＝ 1 −（気づいた場合のみの率 ÷ 全項目の率）。艦が違うので目安にとどまる（カメラレディ5.3。10/21 追加）

使い方
    python3 item_error_rates_v2.py <RDFのフォルダ> <判定の CSV（judge_run*.csv、記録シートの形）> [ラベル]
    例: python3 item_error_rates_v2.py ../outputs/eval_v2/send_main_20261019 ../outputs/eval_v2/llm_judge_v2/judge_run2_main.csv v2
依存: rdflib
"""
import collections
import csv
import glob
import os
import re
import sys

from rdflib import Graph, Namespace, RDF, URIRef

M = "http://www.example.com/myData/"
W = Namespace("http://www.example.com/ontology/warship#")
RANK = {"": 0, "○": 0, "△": 1, "×": 2}
MAIN_ORDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "../outputs/eval_v2/eval_v2_main_order.csv")
SELECTION = os.path.join(os.path.dirname(os.path.abspath(__file__)), "../outputs/eval_v2/eval_v2_selection.csv")
ORDER = ["出来事", "状態の期間", "配属先", "艦長の任命", "寸法・計測", "費用・金額", "名前", "艦"]


def local(n):
    return str(n)[len(M):]


def category(types, name, ship):
    if name == ship or "Ship" in types:
        return "艦"
    if "E93_Presence" in types:
        return "状態の期間"
    if "StationDeployment" in types:
        return "配属先"
    if "CommandAppointment" in types:
        return "艦長の任命"
    if types & {"E54_Dimension", "E16_Measurement"}:
        return "寸法・計測"
    if "E97_Monetary_Amount" in types:
        return "費用・金額"
    if types & {"E42_Identifier", "E41_Appellation"} or name.startswith("name_"):
        return "名前"
    return "出来事"


def owned(name, ship):
    return name == ship or name.startswith(ship + "_") or f"_{ship}_" in name or name.endswith("_" + ship)


def main(rdf_dir, judge_csv, label=""):
    g = Graph()
    for p in glob.glob(os.path.join(rdf_dir, "*.ttl")):
        g.parse(p)
    rows = list(csv.DictReader(open(judge_csv, encoding="utf-8-sig")))
    ships = sorted({r["vessel_id"] for r in rows if r["行タイプ"] == "総合判定"})
    ids = sorted(ships, key=len, reverse=True)

    items = {}   # ノード名 -> (艦, 区分, 出所)
    for s in set(g.subjects(RDF.type, None)):
        if not (isinstance(s, URIRef) and str(s).startswith(M)):
            continue
        name = local(s)
        ship = next((i for i in ids if owned(name, i)), None)
        types = {str(o).split("#")[-1].split("/")[-1] for o in g.objects(s, RDF.type)}
        if ship is None or "E52_Time-Span" in types:
            continue
        prov = "LLM" if any(str(v).startswith("LLM") for v in g.objects(s, W.generated_by_rule)) else "規則"
        items[name] = (ship, category(types, name, ship), prov)

    def item_of(target):
        if target in items:
            return target
        for s in g.subjects(None, URIRef(M + target)):   # 共有のノード → 参照している項目
            if local(s) in items:
                return local(s)
        return None

    worst, worst2, omit, unmatched = {}, {}, collections.Counter(), []
    for r in rows:
        if r["行タイプ"] == "総合判定":
            continue
        t = r["対象ID"].strip()
        if t.startswith("欠落（配属先）"):
            omit["配属先"] += 1
            continue
        if t.startswith("欠落"):
            omit["その他"] += 1
            continue
        it = item_of(t)
        if it is None:
            unmatched.append(t)
            continue
        worst[it] = max(worst.get(it, 0), RANK[r["軸2_スキーマ"]], RANK[r["軸3_意味"]])
        worst2[it] = max(worst2.get(it, 0), RANK[r["軸2_スキーマ"]])

    den, bad, badx = collections.Counter(), collections.Counter(), collections.Counter()
    for name, (_s, cat, prov) in items.items():
        for key in (cat, "合計", "出所:" + prov):
            den[key] += 1
            if worst.get(name, 0) >= 1:
                bad[key] += 1
            if worst.get(name, 0) == 2:
                badx[key] += 1

    summary = [r for r in rows if r["行タイプ"] == "総合判定"]
    details = [r for r in rows if r["行タイプ"] != "総合判定"]
    print(f"## {label}（{len(ships)}隻、項目 {den['合計']}、明細 {len(details)}）\n")
    for ax in ("軸1_構文", "軸2_スキーマ", "軸3_意味"):
        c = collections.Counter(r[ax] for r in summary)
        print(f"- 艦単位 {ax}：○{c['○']} △{c['△']} ×{c['×']}")
    print("\n| 区分 | 項目 | △または× | 率 | ×のみ | 率 |\n|---|---|---|---|---|---|")
    for key in ORDER + ["合計", "出所:規則", "出所:LLM"]:
        if den[key]:
            print(f"| {key} | {den[key]} | {bad[key]} | {bad[key] / den[key]:.1%} | {badx[key]} | {badx[key] / den[key]:.1%} |")
    group_of = {r["id"]: (r["group"], r["group_name"]) for r in csv.DictReader(open(SELECTION, encoding="utf-8-sig"))}
    gden, gbad, gbadx, gomit, gships = (collections.Counter() for _ in range(5))
    for name, (s, _cat, _prov) in items.items():
        grp = group_of.get(s, ("?", "?"))
        gden[grp] += 1
        gbad[grp] += worst.get(name, 0) >= 1
        gbadx[grp] += worst.get(name, 0) == 2
    for s in ships:
        gships[group_of.get(s, ("?", "?"))] += 1
    for r in rows:
        if r["行タイプ"] != "総合判定" and r["対象ID"].strip().startswith("欠落"):
            gomit[group_of.get(r["vessel_id"], ("?", "?"))] += 1
    print("\n| 系統 | 艦 | 項目 | △または× | 率 | ×のみ | 率 | 欠落 |\n|---|---|---|---|---|---|---|---|")
    for grp in sorted(gden):
        print(f"| {grp[0]} {grp[1]} | {gships[grp]} | {gden[grp]} | {gbad[grp]} | {gbad[grp] / gden[grp]:.1%} "
              f"| {gbadx[grp]} | {gbadx[grp] / gden[grp]:.1%} | {gomit[grp]} |")
    if gden:
        rates = [gbad[g] / gden[g] for g in gden]
        print(f"\n- 系統の重みを等しくした率（系統の率の平均）：{sum(rates) / len(rates):.1%}"
              f"（範囲 {min(rates):.1%}〜{max(rates):.1%}）。項目をそのまま合わせた率は {bad['合計'] / den['合計']:.1%}")
    scope_of = {r["id"]: r["軸2の確認範囲"] for r in csv.DictReader(open(MAIN_ORDER, encoding="utf-8-sig"))}
    sden, sbad = collections.Counter(), collections.Counter()
    for name, (s, _cat, _prov) in items.items():
        sc = scope_of.get(s, "?")
        sden[sc] += 1
        sbad[sc] += worst2.get(name, 0) >= 1
    parts = [f"{sc} {sbad[sc]}/{sden[sc]}（{sbad[sc] / sden[sc]:.1%}）" for sc in ("全項目", "気づいた場合のみ") if sden[sc]]
    line = "- 軸2の誤り（一覧の確認範囲別）：" + "、".join(parts)
    if sden["全項目"] and sden["気づいた場合のみ"] and sbad["全項目"]:
        ratio = (sbad["気づいた場合のみ"] / sden["気づいた場合のみ"]) / (sbad["全項目"] / sden["全項目"])
        line += f"。見落としの割合の目安 1 − {ratio:.2f} ＝ {1 - ratio:.0%}（艦が違うので目安）"
    print(line)
    total_omit = sum(omit.values())
    print(f"\n- 欠落：{total_omit}（配属先 {omit['配属先']}、その他 {omit['その他']}）。"
          f"欠落 ÷（項目＋欠落）＝ {total_omit / (den['合計'] + total_omit):.1%}")
    types3 = collections.Counter(r["軸3_エラータイプ"] for r in details if r["軸3_意味"] in ("△", "×"))
    types2 = collections.Counter(r["軸2_エラータイプ"] for r in details if r["軸2_スキーマ"] in ("△", "×"))
    print(f"- 軸3のエラータイプ：{dict(types3.most_common())}")
    print(f"- 軸2のエラータイプ：{dict(types2.most_common())}")
    design = sum("【設計】" in (r["軸2_コメント"] + r["軸3_コメント"]) for r in details)
    design_summary = sum("【設計】" in r.get("総合コメント", "") for r in summary)
    print(f"- 【設計】の印：明細 {design}、総合判定行のコメント {design_summary}（明細にならない設計の指摘）")
    if unmatched:
        print(f"- 項目に対応しない対象ID：{len(unmatched)} {unmatched[:10]}")
    print()


if __name__ == "__main__":
    main(*sys.argv[1:4])
