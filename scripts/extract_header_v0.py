"""規則v0：Winfield原文の定型部分（Ord/K/L/C/Re-ord・First cost）を決定論的に取り出す

入力（読み取りのみ）: ../sources/v1/strata/*.xlsx（269隻）
出力: ../outputs/rules_v0/
    header_facts.csv     取り出した事実（1行1事実。適用した規則IDつき）
    header_unparsed.csv  値を解析しきれなかった箇所（人が確認する対象）
    header_coverage.csv  艦ごとの項目の有無
    summary.json

依存: openpyxl
計画メモ: ../docs/jinmoncom2026_rdf_regeneration_plan_20260930.md §7

規則の一覧（IDは出力の rules 列に記録する）
    N1  数字・ピリオド・カンマ・ハイフンの間に入ったOCR由来の空白を取り除く（例: "1 0.1805" → "10.1805"）
    N2  数字に挟まれた O/o を 0 に直す（例: "1O.1805" → "10.1805"）
    N3  年の先頭の "," や "i" を 1 に直す（例: "1.10.,806" → "1.10.1806"）。推定を含むので ocr_repaired=True
    H1  定型部分の見出し（Ord: / K: / L: / C: / Re-ord:）で値を区切る
    H2  見出しの揺れを受け入れる（"L (floated out):" "(Re-)L:" "C :" "L.5.1809"。3周目で "Ord. 9.6.1808" "K. 10.1808" も）
    H4  見出しで行が終わり、値が次の行に折り返している（"L:" ＋改行＋"24.10.1805"）→ 次の行をつなぐ（3周目）
    S1  値を最初の文の切れ目（". "＋大文字、"; "）で切り、後ろを spill 列に残す（出来事の規則が後で扱う）
    S2  1つの見出しに複数の値がある場合（", 12.6.1790 (for sea)"）は、日付の前で分けて別の事実にする
    A1  日付の候補が複数ある（"X or Y" "X & Y"）→ status=ambiguous として人の確認に回す
    D1  単一の日付（D.M.YYYY / M.YYYY / YYYY）
    D2  期間（"13.5-17.7.1810" "2.1854-4.6.1854" "1.1.1798 to 16.3.1798"。始点に欠けた年・月は終点から補う）
    D3  不確かさの印（"?" "c." "about"）→ uncertain=True
    Q1  値の残りから場所（"at ..."）を取り出す
    Q2  値の残りから括弧内の目的・注記（"(for sea)" "(for Ordinary ...)"）を取り出す
    Q3  括弧なしの目的（"for Ordinary" "for sea"）と役割（"as a packet brig"）、日付の前の注記（"(undocked)" "end"）を取り出す
    Q4  "at" のない場所（"16.3-11.5.1787 Woolwich"）
    Q5  値の残りの ", then ..." 以降は、その後の出来事（"then laid up"）なので場所・目的に含めない。叙述の節として
        survey_narrative_v1.py の split_head が扱う（2026-10-14、試しの判定 SF5_9041）
    F1  "Fitted at X D to D" 型の艤装の記述（C: の代わりに書かれているもの）
    F2  定型部分の行の "Completed D" "Completed fitting D"（C: の代わりに書かれているもの。3周目 2026-10-08）。
        叙述の中の "Completed fitting at X ... D"（修理後の艤装など）は対象外（出来事の規則 EV10 が扱う）
    C1  First cost の金額（£ポンド[.シリング.ペンス]）を取り出す
    C2  金額の内訳の種類（hull / machinery / fitting / build / total）を近くの語から判定する。
        種類の付かない最初の金額を合計（TOTAL）とみなすのは、金額が1つだけの場合と、"including" で内訳が続く場合に限る
    N4  金額中の "£10.485" のように、ピリオドの後に3桁が続くものは千の位の区切りとみなす（シリングは2桁まで）
    C4  臼砲艇などの "First cost (contractor paid + Admiralty supplies/fitting costs): £2,360 + 280/825" 型。
        見出しの順に BUILD（請負額）・SUPPLIES（工廠支給の物資）・FITTING を割り当てる
    C3  "First cost: unknown" "First cost: ?" → status=stated_unknown
    C5  "hull & fitting £N" のように2つの種類を合わせた金額は種類を付けない（UnspecifiedCost。2026-10-14）
"""
import collections
import csv
import glob
import json
import os
import re

import openpyxl

import sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import dataset_paths as P   # 開発用／評価用の切り替え（JINMON_DATASET）
SRC = P.STRATA
OUT = P.out("rules_v0")

FIELD = {"Ord": "ORDERED", "K": "KEEL_LAID", "L": "LAUNCHED", "C": "COMPLETED", "Re-ord": "REORDERED"}
KEY_RE = re.compile(r"(?<![A-Za-z-])(?:\(Re-\))?(Re-ord|Ord|K|L|C)\s?(?:\([^)]*\)\s?)?:"
                    r"|(?:(?<=^)|(?<=\.\s))(Ord|K|L|C)\.(?=\s?\d)")   # H2：ピリオドの見出し（"L.5.1809"、3周目で "Ord. 9.6.1808" "K. 10.1808" も）
DATE_RE = r"(?:\d{1,2}\.){0,2}\d{4}"


def normalize(s, rules):
    """N1・N2：数字まわりのOCRのゆれを直す"""
    t = re.sub(r"(?<=\d)[Oo](?=[\d.])|(?<=[\d.])[Oo](?=\d)", "0", s)
    if t != s:
        rules.add("N2")
    u = re.sub(r"(?<=[\d.,\-])[ \t]+(?=[\d.,\-])", "", t)
    u = re.sub(r"(?<=\d)[ \t]+(?=\.\d)", "", u)
    if u != t:
        rules.add("N1")
    v = re.sub(r"(?<=\.),(?=\d{3}\b)|(?<=\.\s)i\s?(?=\d{3}\b)|(?<=\.)i\s?(?=\d{3}\b)", "1", u)
    if v != u:
        rules.add("N3")
        v = re.sub(r"(?<=[\d.,\-])[ \t]+(?=[\d.,\-])", "", v)   # N3 の後に残った空白を N1 で再度除く
    return v


def to_iso(tok):
    """'19.12.1796' → ('1796-12-19','day')、'2.1797' → ('1797-02','month')、'1797' → ('1797','year')"""
    parts = tok.split(".")
    try:
        if len(parts) == 3:
            d, m, y = (int(x) for x in parts)
            if 1 <= m <= 12 and 1 <= d <= 31:
                return f"{y:04d}-{m:02d}-{d:02d}", "day"
        elif len(parts) == 2:
            m, y = (int(x) for x in parts)
            if 1 <= m <= 12:
                return f"{y:04d}-{m:02d}", "month"
        elif len(parts) == 1:
            return f"{int(parts[0]):04d}", "year"
    except ValueError:
        pass
    return None, None


def parse_date_value(v, rules):
    """値の文字列から日付（単一または期間）を読み、残り（場所・注記）を返す"""
    lead = ""
    m0 = re.match(r"\s*(\((?:undocked|floated out)\)|end|early|late|mid|about|c\.)\s*", v)
    if m0:
        lead = m0.group(1).strip("()")
        rules.add("Q3")
        v = v[m0.end():] if lead not in ("about", "c.") else v
    uncertain = bool(re.search(r"\?|\bc\.|\babout\b", v))
    if uncertain:
        rules.add("D3")
    w = v.replace("?", "")
    w = re.sub(r"\b(c\.|about)\s*", "", w)
    m = re.match(r"\s*(?P<b>(?:\d{1,2}\.){0,2}\d{1,4})\s*(?:-|–|to)\s*(?P<e>" + DATE_RE + r")\b", w)
    if m:
        e_iso, e_prec = to_iso(m.group("e"))
        b_parts = m.group("b").split(".")
        e_parts = m.group("e").split(".")
        # 始点の欠けた部分（年、または月と年）を終点から補う
        if len(b_parts[-1]) != 4:
            b_parts = b_parts + e_parts[len(b_parts) - len(e_parts):] if len(b_parts) < len(e_parts) else b_parts
        b_iso, b_prec = to_iso(".".join(b_parts))
        if b_iso and e_iso:
            rules.add("D2")
            return b_iso, e_iso, b_prec, e_prec, uncertain, (f"({lead}) " if lead else "") + w[m.end():]
    m = re.match(r"\s*(" + DATE_RE + r")\b", w)
    if m:
        iso, prec = to_iso(m.group(1))
        if iso:
            rules.add("D1")
            return iso, iso, prec, prec, uncertain, (f"({lead}) " if lead else "") + w[m.end():]
    return None, None, None, None, uncertain, w


def parse_rest(rest, rules):
    """Q1・Q2：残りの文字列から場所と括弧内の注記を取り出す"""
    rest = rest.strip(" .;,)")
    qual = "; ".join(x.strip() for x in re.findall(r"\(([^)]*)\)?", rest)) if "(" in rest else ""
    if qual:
        rules.add("Q2")
    no_paren = re.sub(r"\([^)]*\)?", "", rest).strip(" .;,")
    m5 = re.search(r",\s*then\b", no_paren)
    if m5:
        rules.add("Q5")
        no_paren = no_paren[:m5.start()].strip(" .;,")
    extra = []
    m3 = re.search(r"\b(for (?:sea|Ordinary)|as (?:an? )?[A-Za-z ]+?)(?=\s+\d|\s+at\b|$)", no_paren)
    if m3:
        extra.append(m3.group(1))
        rules.add("Q3")
        no_paren = (no_paren[:m3.start()] + no_paren[m3.end():]).strip(" .;,")
    if extra:
        qual = "; ".join([qual] + extra if qual else extra)
    place = ""
    m = re.search(r"\bat\s+(.+)$", no_paren)
    if m:
        place = m.group(1).strip(" .;,")
        rules.add("Q1")
        no_paren = no_paren[:m.start()].strip(" .;,")
    elif re.fullmatch(r"[A-Z][A-Za-z]+(?: (?:Dyd|Dockyard))?", no_paren):
        place, no_paren = no_paren, ""
        rules.add("Q4")
    return place, qual, no_paren


def split_sentence(raw, semicolon=True):
    """S1：括弧の外にある最初の文の切れ目（". "＋大文字／"("、または "; "＋数字以外）で切る"""
    depth = 0
    for i, ch in enumerate(raw):
        depth += (ch == "(") - (ch == ")")
        if depth > 0:
            continue
        rest = raw[i + 1:]
        if ch == "." and re.match(r"\s+[A-Z(]", rest) and not re.search(r"\b(Dyd|Capt|Adm|St)$", raw[:i]):
            return raw[:i + 1].strip(), rest.strip()
        if semicolon and ch == ";" and not re.match(r"\s*\d", rest):
            return raw[:i].strip(), rest.strip()
    return raw.strip(), ""


def split_values(head):
    """S2：括弧の外で、", " や "; " の直後に日付が続く位置で分ける"""
    parts, depth, start = [], 0, 0
    for i, ch in enumerate(head):
        depth += (ch == "(") - (ch == ")")
        if depth == 0 and ch in ",;" and re.match(r"\s*\d", head[i + 1:]):
            parts.append(head[start:i])
            start = i + 1
    parts.append(head[start:])
    return [p.strip() for p in parts if p.strip()]


def header_block(text):
    """定型部分の行（見出しを含む行）と、括弧が閉じていなければ次の行までを返す"""
    lines = text.split("\n")
    out = []
    for i, ln in enumerate(lines):
        if KEY_RE.search(ln) and not re.match(r"\s*(Commissioned|Recommissioned|Paid off)", ln):
            seg = ln
            j = i
            while (seg.count("(") > seg.count(")") or re.search(r"(?:Ord|K|L|C)\s?:\s*$", seg)) and j + 1 < len(lines):
                j += 1   # 括弧が閉じていない、または見出しで行が終わり値が次の行に折り返している（H4。3周目：SL1_0016）
                seg += " " + lines[j]
            out.append(seg)
    return out


def cost_text(text):
    """First cost の文（次の行頭が大文字の新しい文になるまで）"""
    m = re.search(r"First cost[^:]*:(.*?)(?=\n\s*(?:Commissioned|Recommissioned|Fitted|Paid|Lent|Sold|Became|Not |Towed|[A-Z][a-z]+ \d)|\Z)",
                  text, re.S)
    if not m:
        return None
    head, _spill = split_sentence(m.group(0).replace("\n", " "), semicolon=False)   # S1：建造費の文だけを対象にする（";" では切らない）
    return head


def parse_cost(raw, rules):
    """C1・C2：金額と内訳の種類"""
    s = normalize(raw, rules)
    n4 = re.sub(r"(£\s*\d{1,3})\.(\d{3})(?![\d.])", r"\1,\2", s)
    if n4 != s:
        rules.add("N4")
    s = re.sub(r"(?<=\d),(?=\d{3}\b)", "", n4)          # 千の位のカンマを除く
    label, body = s.split(":", 1)
    m4 = re.search(r"£\s*(\d+)\s*\+\s*(\d+)\s*/\s*(\d+)", body)
    if re.search(r"contractor paid \+ Admiralty supplies/fitting", label) and m4:
        rules.update({"C1", "C4"})
        return [(float(m4.group(1)), "BUILD", m4.group(0)), (float(m4.group(2)), "SUPPLIES", m4.group(0)),
                (float(m4.group(3)), "FITTING", m4.group(0))]
    # C5（2026-10-14、試しの判定 PSPV_9003）："hull & fitting £10,427" は2つの種類を合わせた1つの金額。"&" で切らない
    body = re.sub(r"\b(hull|machinery|fitting)\s*(?:&|and)\s*(?=(?:hull|machinery|fitting)\b)", r"\1_AND_", body, flags=re.I)
    chunks = re.split(r"[;()+&]|,\s|\bplus\b|\band\b", body)
    facts = []
    for ch in chunks:
        m = re.search(r"£\s*(\d+)(?:\.(\d{1,2})\.(\d{1,2})d?)?", ch)
        if not m:
            continue
        rules.add("C1")
        pounds = int(m.group(1)) + (int(m.group(2) or 0) / 20) + (int(m.group(3) or 0) / 240)
        if "_AND_" in ch:   # C5：合算の種類は語彙にないので、種類を付けない（UnspecifiedCost。原文の語は source_text に残る）
            rules.add("C5")
            facts.append((round(pounds, 4), "", ch.replace("_AND_", " & ").strip()))
            continue
        low = ch.lower()
        kind = ("HULL" if "hull" in low else "MACHINERY" if re.search(r"machiner|engine", low) else
                "FITTING" if "fitting" in low or "fitted" in low else
                "BUILD" if re.search(r"build|built|builder", low) else
                "TOTAL" if "total" in low else "")
        if kind:
            rules.add("C2")
        facts.append((round(pounds, 4), kind, ch.strip()))
    # 種類の付かない最初の金額は、合計とみなす（"First cost: £62,474." や "£96,441 (including ...)"）
    if facts and not facts[0][1] and (len(facts) == 1 or re.search(r"£\s*\d+\s*,?\s*\(?\s*includ", body)):
        facts[0] = (facts[0][0], "TOTAL", facts[0][2])
        rules.add("C2")
    return facts


def main():
    os.makedirs(OUT, exist_ok=True)
    ships = []
    for f in sorted(glob.glob(os.path.join(SRC, "*.xlsx"))):
        rows = list(openpyxl.load_workbook(f, read_only=True).worksheets[0].iter_rows(values_only=True))
        h = rows[0]
        for r in rows[1:]:
            d = dict(zip(h, r))
            ships.append((f"{d['Prefix']}_{int(d['serial_no']):04d}", str(d["text"] or "")))

    facts, unparsed, coverage = [], [], []
    for sid, text in ships:
        have = collections.Counter()
        for line in header_block(text):
            rules = {"H1"}
            norm = normalize(line, rules)
            keys = list(KEY_RE.finditer(norm))
            for k, nxt in zip(keys, keys[1:] + [None]):
                raw = norm[k.end(): nxt.start() if nxt else len(norm)].strip()
                key_rules = set(rules)
                if k.group(2) or k.group(0).strip() not in (f"{k.group(1)}:",):
                    key_rules.add("H2")
                field = FIELD[k.group(1) or k.group(2)]
                head, spill = split_sentence(raw)
                if spill:
                    key_rules.add("S1")
                subs = split_values(head)
                if len(subs) > 1:
                    key_rules.add("S2")
                in_paren = norm[:k.start()].count("(") > norm[:k.start()].count(")")
                for sub in subs:
                    r = set(key_rules)
                    b, e, bp, ep, unc, rest = parse_date_value(sub, r)
                    place, qual, left = parse_rest(rest, r)
                    left = re.sub(r"\s*\bat$", "", left).strip(" .;,")
                    if in_paren:
                        qual = (qual + "; " if qual else "") + "inside parentheses (e.g. original build before capture)"
                    alt = re.match(r"(or|&)\s+(" + DATE_RE + r")$", left)
                    if b and alt:
                        r.add("A1")
                        qual = (qual + "; " if qual else "") + f"alternative date: {alt.group(2)}"
                        status, left = "ambiguous", ""
                    else:
                        status = ("parsed" if b and not left else "partial" if b else
                                  "empty" if sub.strip(" .-") == "" else "unparsed")
                    facts.append([sid, field, sub, b or "", e or "", bp or "", ep or "", unc, place, qual, "", "",
                                  " ".join(sorted(r)), status, spill if sub is subs[-1] else ""])
                    have[field] += 1
                    if status in ("partial", "unparsed", "ambiguous"):
                        unparsed.append([sid, field, sub, left, status])
        # F1：C: の代わりに "Fitted at X D to D" と書かれた艤装（SBS_0002 など）
        if not have["COMPLETED"]:
            m = re.search(r"Fitted at ([A-Z][A-Za-z &]+?) (" + DATE_RE + r") to (" + DATE_RE + r")", normalize(text, set()))
            if m:
                b, bp = to_iso(m.group(2))
                e, ep = to_iso(m.group(3))
                facts.append([sid, "COMPLETED", m.group(0), b, e, bp, ep, False, m.group(1).strip(), "Fitted ... to ...",
                              "", "", "F1 N1 D2 Q1", "parsed", ""])
                have["COMPLETED"] += 1
        # F2：定型部分の行の "Completed D" / "Completed fitting D"（SBS_0081・SL1_0009 など）
        if not have["COMPLETED"]:
            for line in header_block(text):
                m = re.search(r"(?:^|(?<=\.\s))Completed(?: fitting)? (" + DATE_RE + r")\b", normalize(line, set()))
                if m:
                    b, bp = to_iso(m.group(1))
                    facts.append([sid, "COMPLETED", m.group(0), b, b, bp, bp, False, "", "Completed ... (in place of C:)",
                                  "", "", "F2 N1 D1", "parsed", ""])
                    have["COMPLETED"] += 1
                    break
        ct = cost_text(text)
        if ct:
            r = set()
            costs = parse_cost(ct, r)
            for amt, kind, chunk in costs:
                facts.append([sid, "FIRST_COST", chunk, "", "", "", "", False, "", "", amt, kind or "UNLABELLED",
                              " ".join(sorted(r)), "parsed" if kind else "partial", ""])
                have["FIRST_COST"] += 1
            if not costs and re.search(r":\s*(unknown|\?)\s*\.?\s*$", ct.strip()):
                facts.append([sid, "FIRST_COST", ct.strip(), "", "", "", "", True, "", "stated as unknown", "", "",
                              "C3", "stated_unknown", ""])
            elif not costs:
                unparsed.append([sid, "FIRST_COST", ct, ct, "unparsed"])
        coverage.append([sid] + [have[f] for f in ["ORDERED", "KEEL_LAID", "LAUNCHED", "COMPLETED", "REORDERED", "FIRST_COST"]])

    header = ["ship", "field", "raw", "begin", "end", "begin_precision", "end_precision", "uncertain", "place",
              "qualifier", "amount_gbp", "cost_kind", "rules", "status", "spill"]
    for name, hdr, rows in [("header_facts.csv", header, facts),
                            ("header_unparsed.csv", ["ship", "field", "raw", "leftover", "status"], unparsed),
                            ("header_coverage.csv", ["ship", "ORDERED", "KEEL_LAID", "LAUNCHED", "COMPLETED", "REORDERED", "FIRST_COST"], coverage)]:
        with open(os.path.join(OUT, name), "w", newline="", encoding="utf-8-sig") as fh:
            w = csv.writer(fh)
            w.writerow(hdr)
            w.writerows(rows)

    date_facts = [x for x in facts if x[1] != "FIRST_COST"]
    summary = {
        "ships": len(ships),
        "ships_with_field": {f: sum(1 for c in coverage if c[i + 1]) for i, f in
                             enumerate(["ORDERED", "KEEL_LAID", "LAUNCHED", "COMPLETED", "REORDERED", "FIRST_COST"])},
        "date_facts": len(date_facts),
        "date_status": dict(collections.Counter(x[13] for x in date_facts)),
        "uncertain_dates": sum(1 for x in date_facts if x[7]),
        "cost_facts": len(facts) - len(date_facts),
        "cost_kinds": dict(collections.Counter(x[11] for x in facts if x[1] == "FIRST_COST")),
        "rule_usage": dict(collections.Counter(r for x in facts for r in x[12].split())),
    }
    with open(os.path.join(OUT, "summary.json"), "w", encoding="utf-8") as fh:
        json.dump(summary, fh, ensure_ascii=False, indent=2)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
