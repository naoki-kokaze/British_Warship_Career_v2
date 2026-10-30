"""カメラレディ図1：言い回しの種類（規則）の数と、分類できた叙述の節の割合の累積（2026-10-20）

入力（読み取りのみ）: ../outputs/rules_v1_survey/clauses.csv（開発用269隻）
                      ../outputs/eval_v2/rules_v1_survey/clauses.csv（評価用71隻）
                      どちらも survey_narrative_v1.py の出力（節ごとに当てはまった種類。なしを含む）
出力: ../outputs/figures/fig1_rule_coverage.svg
      ../outputs/figures/fig1_rule_coverage.csv  … 図の数値（順番・種類・増えた節の数・累積の割合）

方針:
- 順番は開発用で決める：まだ分類されていない節を最も多く拾う種類から1つずつ足す（貪欲法）
- 評価用には開発用の順番をそのまま当てる（評価用の結果で順番を決め直さない）
- 依存なしで SVG を書く。紙面（A4・2段組の1段）に縮小して載せる前提で、ライトモードのみ。
  系列は色に加えて線種と印（実線・丸／破線・四角）で区別し、グレースケールの印刷でも読めるようにする
"""
import csv
import os

HERE = os.path.dirname(os.path.abspath(__file__))
DEV = os.path.join(HERE, "../outputs/rules_v1_survey/clauses.csv")
EVAL = os.path.join(HERE, "../outputs/eval_v2/rules_v1_survey/clauses.csv")
OUT = os.path.join(HERE, "../outputs/figures")


def load(path):
    return [set(r["categories"].split()) for r in csv.DictReader(open(path, encoding="utf-8-sig"))]


def greedy_order(sets):
    covered, order = [False] * len(sets), []
    remaining = {c for s in sets for c in s}
    while remaining:
        gain = lambda c: sum(1 for i, s in enumerate(sets) if not covered[i] and c in s)
        best = max(sorted(remaining), key=gain)   # 同点は種類のIDの順
        order.append(best)
        remaining.discard(best)
        for i, s in enumerate(sets):
            if best in s:
                covered[i] = True
    return order


def cumulative(sets, order):
    covered, rows = [False] * len(sets), []
    for c in order:
        added = 0
        for i, s in enumerate(sets):
            if not covered[i] and c in s:
                covered[i] = True
                added += 1
        rows.append((c, added, 100 * sum(covered) / len(sets)))
    return rows


# 図の寸法（viewBox の単位。1段の幅に縮小すると 1単位 ≒ 0.15mm）
W, H = 540, 330
L, R, T, B = 58, 150, 18, 52
FONT = "'Hiragino Sans','Noto Sans JP','Yu Gothic',sans-serif"
INK, INK2, GRID = "#0b0b0b", "#52514e", "#dddcd8"
DEV_C, EVAL_C = "#2a78d6", "#eb6834"   # 参照パレットの1・2番（validate_palette.js で検査済み）


def svg(dev_rows, eval_rows, n_dev, n_eval, ships_dev, ships_eval, knee):
    n = len(dev_rows)
    x = lambda k: L + (k - 1) * (W - L - R) / (n - 1)
    y = lambda p: T + (100 - p) * (H - T - B) / 100
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" font-family="{FONT}" '
           f'role="img" aria-labelledby="t d">',
           '<title id="t">規則の数と分類できた節の割合の累積</title>',
           f'<desc id="d">開発用{ships_dev}隻（{n_dev}節）と評価用{ships_eval}隻（{n_eval}節）。'
           f'{n}種類で開発用{dev_rows[-1][2]:.1f}%，評価用{eval_rows[-1][2]:.1f}%．</desc>',
           f'<rect width="{W}" height="{H}" fill="#ffffff"/>']
    for p in (0, 25, 50, 75, 100):   # 目盛りと補助線（控えめに）
        out.append(f'<line x1="{L}" x2="{W - R}" y1="{y(p):.1f}" y2="{y(p):.1f}" stroke="{GRID}" stroke-width="1"/>')
        out.append(f'<text x="{L - 8}" y="{y(p) + 5:.1f}" font-size="15" fill="{INK2}" text-anchor="end">{p}</text>')
    for k in (1, 5, 10, 15, 20, 25, n):
        out.append(f'<text x="{x(k):.1f}" y="{H - B + 20}" font-size="15" fill="{INK2}" text-anchor="middle">{k}</text>')
    out.append(f'<line x1="{L}" x2="{W - R}" y1="{y(0):.1f}" y2="{y(0):.1f}" stroke="{INK2}" stroke-width="1"/>')
    out.append(f'<text x="{(L + W - R) / 2:.1f}" y="{H - 8}" font-size="16" fill="{INK}" text-anchor="middle">'
               f'規則（言い回しの種類）の数</text>')
    out.append(f'<text transform="translate(16 {(T + H - B) / 2:.1f}) rotate(-90)" font-size="16" fill="{INK}" '
               f'text-anchor="middle">分類できた節の割合（%）</text>')
    # 止めどころの目安：この番号以降は1つ足しても1ポイント未満
    kx = (x(knee - 1) + x(knee)) / 2
    out.append(f'<line x1="{kx:.1f}" x2="{kx:.1f}" y1="{y(100):.1f}" y2="{y(0):.1f}" stroke="{INK2}" '
               f'stroke-width="1" stroke-dasharray="2 3"/>')
    out.append(f'<text x="{kx + 6:.1f}" y="{y(40):.1f}" font-size="15" fill="{INK2}">{knee}番目以降は</text>')
    out.append(f'<text x="{kx + 6:.1f}" y="{y(40) + 19:.1f}" font-size="15" fill="{INK2}">1つで1ポイント未満</text>')
    for rows, color, dash, mark in ((eval_rows, EVAL_C, "6 4", "square"), (dev_rows, DEV_C, "", "circle")):
        pts = " ".join(f"{x(k):.1f},{y(p):.1f}" for k, (_, _, p) in enumerate(rows, 1))
        da = f' stroke-dasharray="{dash}"' if dash else ""
        out.append(f'<polyline points="{pts}" fill="none" stroke="{color}" stroke-width="2"{da} '
                   f'stroke-linejoin="round" stroke-linecap="round"/>')
        for k, (_, _, p) in enumerate(rows, 1):
            if mark == "circle":
                out.append(f'<circle cx="{x(k):.1f}" cy="{y(p):.1f}" r="3.2" fill="{color}" stroke="#ffffff" stroke-width="1"/>')
            else:
                out.append(f'<rect x="{x(k) - 3:.1f}" y="{y(p) - 3:.1f}" width="6" height="6" fill="{color}" '
                           f'stroke="#ffffff" stroke-width="1"/>')
    # 線の端の直接ラベル（2本の終点は近いので上下に振り分ける）
    ex = x(n) + 10
    dp, ep = dev_rows[-1][2], eval_rows[-1][2]
    out.append(f'<text x="{ex:.1f}" y="{y(dp) - 16:.1f}" font-size="15" fill="{INK}">'
               f'<tspan font-weight="600">開発用</tspan> {dp:.1f}%</text>')
    out.append(f'<text x="{ex:.1f}" y="{y(dp) + 1:.1f}" font-size="13" fill="{INK2}">{ships_dev}隻・{n_dev:,}節</text>')
    out.append(f'<text x="{ex:.1f}" y="{y(ep) + 26:.1f}" font-size="15" fill="{INK}">'
               f'<tspan font-weight="600">評価用</tspan> {ep:.1f}%</text>')
    out.append(f'<text x="{ex:.1f}" y="{y(ep) + 43:.1f}" font-size="13" fill="{INK2}">{ships_eval}隻・{n_eval:,}節</text>')
    out.append(f'<line x1="{x(n) + 3:.1f}" x2="{ex - 2:.1f}" y1="{y(dp):.1f}" y2="{y(dp) - 20:.1f}" stroke="{DEV_C}" stroke-width="1"/>')
    out.append(f'<line x1="{x(n) + 3:.1f}" x2="{ex - 2:.1f}" y1="{y(ep):.1f}" y2="{y(ep) + 21:.1f}" stroke="{EVAL_C}" stroke-width="1"/>')
    out.append("</svg>")
    return "\n".join(out)


def main():
    dev, ev = load(DEV), load(EVAL)
    order = greedy_order(dev)
    dev_rows, eval_rows = cumulative(dev, order), cumulative(ev, order)
    knee = next(k for k, (_, added, _) in enumerate(dev_rows, 1) if 100 * added / len(dev) < 1)
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, "fig1_rule_coverage.csv"), "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["rank", "category", "dev_added", "dev_cum_pct", "eval_added", "eval_cum_pct"])
        for k, (d, e) in enumerate(zip(dev_rows, eval_rows), 1):
            w.writerow([k, d[0], d[1], f"{d[2]:.1f}", e[1], f"{e[2]:.1f}"])
    with open(os.path.join(OUT, "fig1_rule_coverage.svg"), "w", encoding="utf-8") as f:
        f.write(svg(dev_rows, eval_rows, len(dev), len(ev), 269, 71, knee))
    print(f"dev {len(dev)}節 {dev_rows[-1][2]:.1f}% / eval {len(ev)}節 {eval_rows[-1][2]:.1f}% / "
          f"{knee}番目以降は1ポイント未満（開発用）")


if __name__ == "__main__":
    main()
