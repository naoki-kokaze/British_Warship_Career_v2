"""規則v0.1：Winfield原文の定型部分から、寸法・トン数（bm）・喫水・排水量を決定論的に取り出す

入力（読み取りのみ）: ../sources/v1/strata/*.xlsx（269隻）
出力: ../outputs/rules_v01/
    dimension_facts.csv      取り出した値（1行1値。適用した規則IDつき）
    dimension_review.csv     人が確認する対象（要確認・解析不能。式に合う候補を参考として付す）
    formula_check.csv        bm の検算（k × b × ½b ／ 94。凡例 'Tons'）
    summary.json

依存: openpyxl
計画メモ: ../docs/jinmoncom2026_rdf_regeneration_plan_20260930.md §7.6
寸法の意味: Winfield 2014, Glossary and Abbreviations, 'Dimensions'・'Tons'（ontology v2 draft.2 の :DimensionKind）

記録の方針（2026-10-05 ユーザー決定）
    - 長さは ft と in を別々に記録する（in は ½・¼・¾・⅛ などを小数で）。換算は分析の層で行う
    - bm は整数部と94分の端数（分子）を別々に記録する
    - 一意に直せるOCRの誤りだけを規則で直し、規則IDを残す。一意に決まらないもの（S が 5 か 8 か、"?"、"%"、
      bm の区切りの化け）は値を確定させず status=needs_review とする。式に合う候補は参考として示すだけで、値には入れない

規則の一覧（IDは出力の rules 列に記録する）
    G1  見出しで寸法の部分を切り出す（"As built:" "Dimensions & tons:" "As lengthened ...:" "As converted:"
        "Tonnage as completed:"）。次の見出し（Men: Guns: Machinery: Ord: K: L: C: など）の前で切る
    G2  見出しのOCRの揺れを受け入れる（"As built" のコロン抜け、"Dimensions & guns:"）
    M1  数字・ft・in の間に入ったOCR由来の空白を除く（"1 0in" → "10in"、"1 1 ft" → "11ft"、"f t" → "ft"）
    M2  ft/in の数字の位置にある O・Q・D を 0 に直す（"1 Oft" → "10ft"、"Qin" → "0in"）
    M3  ft/in の数字の位置にある B を 8 に直す（"Bin" → "8in"）
    M4  分数の化けを見つける："x/a" "x/s"（例 "33/ain"、"31/sin"）。当初は a → 4、s → 8 と一意に直していたが、
        目視確認（2026-10-05、PM_0028 の "33/ain" は 3⅜）と式の検算で、a も s も分母が 4 の場合と 8 の場合があると
        分かった。そこで分母 4 と 8 の2つを候補にして needs_review とし、式で一意に決まれば F2 で決める
    M5  行頭の i や " を除く（"i ,7323" → "1,7323"）
    U1  一意に決まらない数字（S は 5 か 8、"?" は不明、"%" は分数不明）→ needs_review。式で検算できる値（竜骨長・幅）
        には、式に合う候補を参考として付す
    L1  "a, b x c x d" の4値：砲甲板長、トン数算定用の竜骨長 × 幅 × 船倉の深さ（凡例 'Dimensions'）
    L2  "about" → uncertain=True（2026-10-14：about より後ろの値にだけ）
    B1  幅の括弧書き："oa (X for tonnage)" "(X for tons)" → 括弧内がトン数算定用の幅、括弧外は oa（凡例に定義なし）
    B2  幅の括弧書き："(X mid.)" → 括弧内が型幅（凡例 'Mld.'）。括弧外は凡例どおりトン数算定用の幅
    B3  幅の括弧書き："(X oa)" → 括弧内が oa。括弧外はトン数算定用の幅
    L3  "x" で区切った値が4つ以上（PM_0028 Vigilant：'200ft 3⅜in x 28ft 2in (28ft 0in for tonnage) x 28ft 3in x 14ft 6in'）：
        最初を竜骨長、2つ目を幅（括弧書きは B1〜B4）、最後を船倉の深さとし、間の値は種類不明（:DimensionUnlabelled）。
        凡例に説明がないので、間の値と最後の値は needs_review にする（2026-10-05。PM_0028 は竜骨長と「トン数算定用」の
        幅で bm の式に一致することを確認済み）
    B4  幅の括弧書きで種類の語がないもの（"(23ft 0in)"）→ 括弧内は種類不明として needs_review
    T1  bm の整数（"1,081bm" "837bm"）
    T2  bm の94分の端数（"1,08974/94bm"）。区切りの化け（; t ! J l \ " など）を受け入れる。千の位のカンマがあれば
        整数部は確定する。区切りが "1" に化けた場合や、整数部と分子の境が決まらない場合は候補を列挙して needs_review
    T3  "\4bm" 型（分子が読めない）→ 整数部だけ記録し、端数は needs_review
    T4  Winfield は 1,000 以上の整数に必ず千の位のカンマを付ける（"1,081bm" "1,05554/94bm"）。そこで、カンマのない
        整数部は 1,000 未満とみなす。"23544194bm" は "235 44/94"（区切りの "/" が "1" に化けたもの）と読む
    T5  "921 (920\4 by calc.) bm" 型：原文の値（921）を記録し、計算値の記述は注記に残す
    R1  喫水 "Draught a/b" → 艦首／艦尾（凡例 'Draught'。竣工時の軽荷）。"(fwd), (aft)" 型も受け入れる
    R2  喫水の注記（"(light)" "(with 30 tons ballast aboard)"）を qualifier に残す
    P1  排水量（"1,960 disp." "230 displ." "3,632 tons displacement" "/4,583 disp"）。凡例 'Tons' の
        「後年の蒸気艦には参考として付す」排水量
    F1  bm の検算（記録の層の値は変えない）：トン数算定用の竜骨長 k と幅 b から k × b × ½b ／ 94 を計算し、
        原文の bm との差を formula_check.csv に出す。要確認の値には、式に合う候補を参考として示す
    F2  式による決定（2026-10-05 ユーザー決定、案2）：要確認の値のうち、式との差が最も小さい候補が 0.01% 以下で、
        次点の差がその5倍以上の場合に限り、その候補を記録の層の値とする。status=formula_resolved。原文の文字列・
        採った候補・次点を note に残し、目視確認の対象にする
    V1  目視確認の反映：../sources/manual/dimension_visual_checks.csv（人が記入。スクリプトは無ければ作るだけで、
        上書きしない）の visual_check 列を読む。confirmed → visually_confirmed（式で決めた値を目視で確認）、
        corrected → corrected_value の値に置き換えて visually_corrected、unreadable → 要確認のまま注記
    X1  寸法の欠けの記述（"dimensions unknown" "Dimensions unavailable" "to design exactly" "- -"）を注記として残す
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
MANUAL = P.manual("dimension_visual_checks.csv")
MANUAL_HEADER = ["ship", "ship_name", "class_name", "genre", "segment", "context", "kind", "raw", "status_at_export", "suggested_value", "formula_note",
                 "visual_check", "corrected_value", "checked_by", "checked_on", "note"]
OUT = P.out("rules_v01")

HEAD_RE = re.compile(r"(As built(?: \(|:|\s(?=[\d\"]))|As lengthened[^:]{0,12}:|As converted:|"
                     r"Dimensions & (?:tons|guns):|Tonnage as completed:)")
STOP_RE = re.compile(r"(?:\b(?:Men|Guns|Machinery|Ord|Re-ord|K|L|C|First cost|Armament|Complement)\s?:)|\bDesign\b|"
                     r"\b(?:Commissioned|Recommissioned|Fitted|Paid off|Sold|Purchased|Built)\b")
FRAC = {"½": 0.5, "¼": 0.25, "¾": 0.75, "⅛": 0.125, "⅜": 0.375, "⅝": 0.625, "⅞": 0.875}
CONTEXT = {"As built": "as built", "As lengthened": "as lengthened", "As converted": "as converted",
           "Dimensions & tons": "dimensions and tons", "Dimensions & guns": "dimensions and tons",
           "Tonnage as completed": "as completed"}


def segment(text):
    """G1・G2：寸法の部分を切り出す（見出し、本文、規則）"""
    flat = re.sub(r"-\n\s*", "-", text)          # "dis-\nplacement"
    flat = re.sub(r"\s*\n\s*", " ", flat)
    out = []
    for m in HEAD_RE.finditer(flat):
        rules = {"G1"}
        head = m.group(1)
        if head.startswith("As built") and not head.startswith("As built:"):
            rules.add("G2")
        if head.startswith("Dimensions & guns"):
            rules.add("G2")
        body_start = m.end() if head.endswith(":") else m.start() + len("As built")
        rest = flat[body_start:body_start + 400]
        nxt = HEAD_RE.search(rest)
        stop = STOP_RE.search(rest)
        cut = min([x.start() for x in (nxt, stop) if x] + [len(rest)])
        key = next(k for k in CONTEXT if head.startswith(k))
        out.append((CONTEXT[key], head.strip(), rest[:cut].strip(), rules))
    return out


def normalize(s, rules):
    """M1〜M5：ft/in と数字まわりの、一意に直せるOCRの揺れを直す"""
    t = s.replace("f t", "ft")
    t2 = re.sub(r"(?<=\d)\s?i\s+n\b", "in", t)   # M6（試し、2026-10-08）：OCR で切れた "4i n"（SF5_9041）
    if t2 != t:
        rules.add("M6")
    t = t2
    t2 = re.sub(r"^[\"i]\s*(?=[\d,])", "", t)
    if t2 != t:
        rules.add("M5")
    t = t2
    t2 = re.sub(r"(?<=[\s,])i\s?(?=[ ,]?\d)", "1", t)
    if t2 != t:
        rules.add("M5")
    t = t2
    # M1：数字どうし、数字と ft/in・分数の間の空白（O Q D B S ? も数字の位置にありうるので含める）
    t2 = re.sub(r"(?<=[\dOQDBS?])\s+(?=[\dOQDBS?½¼¾⅛⅜⅝⅞%]|ft\b|in\b)", "", t)
    t2 = re.sub(r"(?<=\d)\s+(?=,\d)|(?<=\d,)\s+(?=\d)", "", t2)
    if t2 != t:
        rules.add("M1")
    t = t2
    # M2・M3：ft/in の直前の数字の並びにある O Q D B
    def fix(m):
        tok = m.group(1)
        new = re.sub(r"[OoQD]", "0", tok)
        if new != tok:
            rules.add("M2")
        new2 = new.replace("B", "8")
        if new2 != new:
            rules.add("M3")
        return new2 + m.group(2)
    t = re.sub(r"(?<![A-Za-z])([\dOoQDB?S]+(?:[½¼¾⅛⅜⅝⅞%]|\d?/\s?[as])?)\s?(ft|in)\b", fix, t)
    t = re.sub(r"(?<=\d)\s+(?=[½¼¾⅛⅜⅝⅞]|ft\b|in\b)", "", t)
    # M4：分数の化け
    def frac(m):
        rules.add("M4")
        return f"{m.group(1)}[{m.group(2)}/{m.group(3)}]in"
    t = re.sub(r"(\d*)(\d)/\s?([as])in\b", frac, t)
    return t


MEAS_RE = re.compile(r"(?P<ft>[\d?S]+)ft(?:\s?(?P<in>[\d?S]{1,2})?(?P<fr>[½¼¾⅛⅜⅝⅞%]|\[\d/[as]\])?in)?")


def parse_meas(tok, rules):
    """'163ft 5½in' → (163, 5.5, status, candidates)。S・? は needs_review"""
    tok = normalize(tok, rules)
    m = MEAS_RE.search(tok)
    if not m:
        return None
    ft_s, in_s, fr = m.group("ft"), m.group("in") or ("0" if m.group("fr") else None), m.group("fr")
    unclear = []
    if re.search(r"[S?]", ft_s):
        unclear.append("ft")
    if in_s is not None and re.search(r"[S?]", in_s):
        unclear.append("in")
    if fr == "%":
        unclear.append("fraction")
    frac_opts = None
    if fr and fr.startswith("["):   # M4：x/a・x/s は分母 4 か 8
        unclear.append("fraction (denominator 4 or 8)")
        frac_opts = sorted({int(fr[1]) / 4, int(fr[1]) / 8} - {x for x in [int(fr[1]) / 4] if int(fr[1]) >= 4})
    if unclear:
        rules.add("U1")
    frv = 0.0
    if fr and fr in FRAC:
        frv = FRAC[fr]
    ft = None if "ft" in unclear else int(ft_s)
    inch = None
    if in_s is not None and not unclear:
        inch = int(in_s) + frv
    elif in_s is None:
        inch = None
    status = "needs_review" if unclear else "parsed"
    if (m.group("in") is not None or fr) and inch is None and not unclear:
        status = "unparsed"
    if not (m.group("in") is not None or fr) and re.search(r"\d\s*\S*\s*in\b", tok[m.end():]):
        status = "unparsed"   # ft の後にインチらしい文字列があるのに読めていない（読み落としを解析済みにしない）
        unclear.append("inches not read")
    if inch is not None and inch >= 12:
        status = "needs_review"
        unclear.append("inches>=12")
    return {"ft": ft, "in": inch, "ft_raw": ft_s, "in_raw": (in_s or "") + (fr or ""),
            "frac": None if (fr == "%" or frac_opts) else frv, "frac_opts": frac_opts,
            "unclear": unclear, "status": status, "span": m.span(), "has_in": m.group("in") is not None or bool(fr)}


def inch_candidates(meas):
    """S は 5/8、? は 0〜9（または 0〜11）。式の検算に使う候補（ft, in）"""
    fts = [int(meas["ft_raw"])] if re.fullmatch(r"\d+", meas["ft_raw"]) else \
        [int(x) for x in expand(meas["ft_raw"])]
    if meas.get("frac_opts"):
        fracs = meas["frac_opts"]
    elif meas["frac"] is None:
        fracs = [k / 8 for k in range(8)]
    else:
        fracs = [meas["frac"]]
    in_raw = re.sub(r"[½¼¾⅛⅜⅝⅞%]|\[\d/[as]\]", "", meas["in_raw"]) or "0"
    ins = [int(x) for x in expand(in_raw) if int(x) < 12]
    return [(f, i + fr) for f in fts for i in ins for fr in fracs]


def expand(s):
    opts = [""]
    for ch in s:
        alts = ["5", "8"] if ch == "S" else [str(d) for d in range(10)] if ch == "?" else [ch]
        opts = [o + a for o in opts for a in alts]
    return opts


def to_ft(ft, inch):
    return ft + (inch or 0) / 12


def parse_bm(tok, rules):
    """T1〜T3：bm の値。戻り値は（候補のリスト[(整数, 分子)]、端数が読めないか、注記）"""
    t = tok.replace(" ", "")
    t = re.sub(r"^i(?=,|\d)", "1", t)
    t = re.sub(r"^[\"i]", "", t)
    m3 = re.fullmatch(r"([\d,]+?)\\4", t)
    if m3:
        rules.add("T3")
        return [(int(m3.group(1).replace(",", "")), None)], True
    if re.fullmatch(r"\d{1,3}(?:,\d{3})+|\d{1,3}", t) or (re.fullmatch(r"\d{4}", t) and not t.endswith("94")):
        rules.add("T1")
        return [(int(t.replace(",", "")), 0)], False
    m = re.fullmatch(r"(?P<d>[\d,?]+?)(?P<sep>[;/t!Jl\\]|,\.)?(?P<den>94|04|9|\"|)", t)
    if not m or not m.group("d"):
        return [], False
    rules.add("T2")
    d, sep = m.group("d"), m.group("sep")
    variants = [d]
    if not sep and d.endswith("1"):   # 区切りの "/" が "1" に化けた可能性
        variants = [d[:-1], d]
    cands = []
    for v in variants:
        for n in (1, 2):
            whole, num = v[:-n], v[-n:]
            if not whole or not whole.replace(",", "") or "?" in v:
                continue
            if "," in whole and not re.fullmatch(r"\d{1,3}(?:,\d{3})+", whole):
                continue
            if "," not in whole and len(whole) > 3:   # T4
                rules.add("T4")
                continue
            if "," in num:
                continue
            if not (0 < int(num) < 94) or (n == 2 and num.startswith("0")):
                continue
            cands.append((int(whole.replace(",", "")), int(num)))
    return sorted(set(cands)), False


def bm_value(whole, num):
    return whole + (num or 0) / 94


def main():
    os.makedirs(OUT, exist_ok=True)
    ships = []
    for f in sorted(glob.glob(os.path.join(SRC, "*.xlsx"))):
        rows = list(openpyxl.load_workbook(f, read_only=True).worksheets[0].iter_rows(values_only=True))
        for r in rows[1:]:
            d = dict(zip(rows[0], r))
            ships.append((f"{d['Prefix']}_{int(d['serial_no']):04d}", str(d["text"] or "")))
            SHIP_INFO[f"{d['Prefix']}_{int(d['serial_no']):04d}"] = [str(d.get("Name") or ""), str(d.get("CLASS") or ""),
                                                                     str(d.get("Genre") or "")]

    facts, fcheck = facts_ref, []
    pms = PMS
    seg_count = collections.Counter()

    def add(sid, n, ctx, kind, raw, rules, status, ft="", inch="", whole="", num="", value="", qual="", unc=False,
            note="", cands=""):
        facts.append([sid, n, ctx, kind, raw, ft, inch, whole, num, value, unc, qual, " ".join(sorted(rules)),
                      status, note, cands, pms.pop("last", None)])

    for sid, text in ships:
        for n, (ctx, head, body, grules) in enumerate(segment(text), 1):
            seg_count[ctx] += 1
            rules = set(grules)
            s = body.replace("f t", "ft")
            calc = re.search(r"\s*\((\d[\d,]*)\s?\\4 by calc\.\)\s*", s)
            if calc:   # T5
                rules.add("T5")
                s = s[:calc.start()] + " " + s[calc.end():]
            # 区間の構造（, x ( ) . bm Draught）は空白の揺れの影響を受けないので、正規化は値ごとに行う
            notes = []
            # X1：欠けの記述
            for pat in [r"dimensions (?:unknown|missing[^)]*|unavailable)", r"to design exactly",
                        r"Dimensions quoted are always those of design[^.]*", r"^-\s*-?"]:
                mm = re.search(pat, s, re.I)
                if mm:
                    rules.add("X1")
                    notes.append(mm.group(0).strip())
            # 寸法の4値：最初の "ft" から、bm・disp・Draught の前まで
            dim_end = re.search(r"\.\s*[\d,\s\"i]*[\d?][^.]*?\s?bm\b|\bDraught\b|\bdisp|\bMean draught\b|\d\s?bm\b", s)
            dims = s[:dim_end.start() if dim_end else len(s)]
            if re.search(r"[\dOQDBS?]\s?ft", dims):
                parse_dims(sid, n, ctx, dims, set(rules), add, fcheck)
            # bm
            for mb in re.finditer(r"(?:(?<=\.)|(?<=\.\s)|(?<=^)|(?<=\s))([\d,\s\"i?;/t!Jl\\]+?(?:,\.)?)\s?bm\b", s):
                tok = mb.group(1).strip()
                if not re.search(r"\d", tok):
                    continue
                r = set(rules)
                cands, frac_lost = parse_bm(tok, r)
                if calc:
                    notes.append(f"source also gives {calc.group(1)} and a lost fraction 'by calc.'")
                if len(cands) == 1 and not frac_lost:
                    clean = "T2" not in r or re.search(r"[;/]", tok) or re.search(r"[t!Jl\\\"]", tok) and not tok.replace(" ", "")[:-2].endswith("1")
                    st = "parsed" if clean else "repaired"
                    add(sid, n, ctx, "BuildersMeasurement", tok + "bm", r, "parsed", whole=cands[0][0], num=cands[0][1],
                        note="; ".join(notes))
                elif len(cands) == 1 and frac_lost:
                    add(sid, n, ctx, "BuildersMeasurement", tok + "bm", r, "needs_review", whole=cands[0][0],
                        note="; ".join(notes + ["fraction (ninety-fourths) unreadable"]))
                else:
                    r.add("U1")
                    add(sid, n, ctx, "BuildersMeasurement", tok + "bm", r, "needs_review" if cands else "unparsed",
                        note="; ".join(notes + ["integer/fraction split not unique" if cands else "unreadable"]),
                        cands=" | ".join(f"{w} {k}/94" for w, k in cands))
            # 喫水
            md = re.search(r"(?<!Mean )Draught\s+(?P<a>[^/,]+?in)\s*(?:\((?:fwd|forward)\))?\s*[/,]\s*(?P<b>[^.(]+?in)"
                           r"\s*(?:\(aft\))?(?P<q>\s*\([^)]*\))?", s)
            if md:
                r = set(rules) | {"R1"}
                q = (md.group("q") or "").strip(" ()")
                if q:
                    r.add("R2")
                for kind, tok in (("DraughtForward", md.group("a")), ("DraughtAft", md.group("b"))):
                    rr = set(r)
                    pm = parse_meas(tok, rr)
                    pms["last"] = pm
                    if pm is None:
                        add(sid, n, ctx, kind, tok, rr, "unparsed", qual=q)
                    else:
                        add(sid, n, ctx, kind, tok, rr, pm["status"], ft=pm["ft"] if pm["ft"] is not None else "",
                            inch=pm["in"] if pm["in"] is not None else "", qual=q,
                            note=("unclear: " + ",".join(pm["unclear"])) if pm["unclear"] else "")
            elif re.search(r"Draught", s):
                tail = s[s.find("Draught"):][:80]
                add(sid, n, ctx, "Draught", tail, rules, "unparsed",
                    note="draught given in another form or cut off at a line end")
            # 排水量
            for mp in re.finditer(r"(?:(?<=\s)|(?<=/)|(?<=^))([\d,]+)\s?(?:tons\s+)?(?:disp(?:l)?\b\.?|displacement|dis-placement)", s):
                add(sid, n, ctx, "Displacement", mp.group(0), rules | {"P1"}, "parsed",
                    value=int(mp.group(1).replace(",", "")))
            if notes and not any(x[0] == sid and x[1] == n for x in facts):
                add(sid, n, ctx, "Note", body[:120], rules, "needs_review", note="; ".join(notes))

    formula_pass(facts)
    manual_info = apply_visual_checks(facts)
    fcheck = final_formula_check(facts)
    review = [[x[0], x[1], x[2], x[3], x[4], x[13], x[14], x[15]] for x in facts if x[13] != "parsed"]
    facts = [x[:15] for x in facts]
    header = ["ship", "segment", "context", "kind", "raw", "feet", "inches", "tons_bm_whole", "tons_bm_94ths", "value",
              "uncertain", "qualifier", "rules", "status", "note"]
    write(os.path.join(OUT, "dimension_facts.csv"), header, facts)
    write(os.path.join(OUT, "dimension_review.csv"),
          ["ship", "segment", "context", "kind", "raw", "status", "note", "candidates (reference only)"], review)
    write(os.path.join(OUT, "visual_check_missing.csv"), MANUAL_HEADER, manual_info["missing"])
    write(os.path.join(OUT, "formula_check.csv"),
          ["ship", "segment", "keel_ft", "breadth_ft", "bm_stated", "bm_calc", "rel_diff", "note"], fcheck)
    summary = {
        "ships": len(ships),
        "ships_with_segment": len({x[0] for x in facts}),
        "segments": dict(seg_count),
        "facts": len(facts),
        "by_kind": dict(collections.Counter(x[3] for x in facts)),
        "by_status": dict(collections.Counter(x[13] for x in facts)),
        "by_kind_status": {f"{k}/{s}": c for (k, s), c in sorted(collections.Counter((x[3], x[13]) for x in facts).items())},
        "rule_usage": dict(collections.Counter(r for x in facts for r in x[12].split())),
        "formula_checked": len([x for x in fcheck if x[6] != ""]),
        "formula_warnings_over_0.5pct": len([x for x in fcheck if x[6] != "" and abs(x[6]) > WARN]),
        "visual_checks": {k: v for k, v in manual_info.items() if k != "missing"},
        "visual_check_rows_not_in_manual_file": len(manual_info["missing"]),
    }
    with open(os.path.join(OUT, "summary.json"), "w", encoding="utf-8") as fh:
        json.dump(summary, fh, ensure_ascii=False, indent=2)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def parse_dims(sid, n, ctx, dims, rules, add, fcheck):
    """L1・L2・B1〜B4：'a, b x c x d'"""
    m_about = re.search(r"\babout\b", dims)
    if m_about:
        rules.add("L2")
    d = re.sub(r"\babout\s*", "", dims)

    def unc_of(tok):
        """L2（2026-10-14、試しの判定 SM_9036）：'about' はそれより後ろの値にだけ掛ける（"115ft 0in, about 99ft 3in x ..."）"""
        pos = dims.find(tok.strip()) if tok.strip() else -1
        return bool(m_about) and pos >= m_about.start()
    if "," in d.split("x")[0]:
        lengths_part, rest = d.split("x")[0].split(",", 1)
        g_tok, k_tok = lengths_part, rest
    else:   # 長さが1つだけ：砲甲板長か竜骨長か原文からは決まらない
        g_tok, k_tok = "", d.split("x")[0]
        r1 = set(rules) | {"L1"}
        add(sid, n, ctx, "LengthUnspecified", k_tok.strip(), r1, "needs_review", unc=unc_of(k_tok),
            note="only one length is given; gundeck or keel for tonnage is not stated")
        k_tok = ""
    parts = [p for p in re.split(r"\sx\s", d)]
    parts[0] = k_tok
    extra = []
    if len(parts) > 3:   # L3
        rules.add("L3")
        extra = parts[2:-1]
        parts = [parts[0], parts[1], parts[-1]]
    elif len(parts) != 3:
        add(sid, n, ctx, "Dimensions", dims.strip(), rules, "needs_review",
            note=f"{len(parts)} values separated by 'x' (expected 3: keel for tonnage x breadth x depth)")
        return
    rules.add("L1")
    vals = {}

    def put(kind, tok, extra_rules=(), qual=""):
        r = set(rules) | set(extra_rules)
        pm = parse_meas(tok, r)
        if pm is None:
            if re.search(r"\d", tok):
                add(sid, n, ctx, kind, tok.strip(), r, "unparsed", qual=qual, unc=unc_of(tok))
            return
        PMS["last"] = pm
        add(sid, n, ctx, kind, tok.strip(), r, pm["status"], ft=pm["ft"] if pm["ft"] is not None else "",
            inch=pm["in"] if pm["in"] is not None else "", qual=qual, unc=unc_of(tok),
            note=("unclear: " + ",".join(pm["unclear"])) if pm["unclear"] else "")
        vals[kind] = pm

    if g_tok.strip(" -"):
        put("GundeckLength", g_tok)
    if parts[0].strip():
        put("KeelLengthForTonnage", parts[0])
    b = parts[1]
    paren = re.search(r"\(([^)]*)\)", b)
    main_b = re.sub(r"\([^)]*\)?", "", b)
    if paren:
        inner = paren.group(1)
        if re.search(r"for ton", inner):
            put("BreadthForTonnage", inner, ["B1"])
            put("BreadthMarkedOA" if re.search(r"\boa\b", main_b) else "BreadthUnlabelled", main_b, ["B1"])
        elif re.search(r"\bmid\b|\bmld\b", inner, re.I):
            put("BreadthForTonnage", main_b, ["B2"])
            put("MouldedBreadth", inner, ["B2"])
        elif re.search(r"\boa\b", inner):
            put("BreadthForTonnage", main_b, ["B3"])
            put("BreadthMarkedOA", inner, ["B3"])
        else:
            put("BreadthForTonnage" if not re.search(r"\boa\b", main_b) else "BreadthMarkedOA", main_b, ["B4"])
            r = set(rules) | {"B4"}
            add(sid, n, ctx, "BreadthUnlabelled", inner.strip(), r, "needs_review", unc=unc_of(inner),
                note="breadth in parentheses without a label")
    else:
        put("BreadthMarkedOA" if re.search(r"\boa\b", main_b) else "BreadthForTonnage", main_b)
    for tok in extra:
        r = set(rules)
        pm = parse_meas(tok, r)
        add(sid, n, ctx, "DimensionUnlabelled", tok.strip(), r, "needs_review", unc=unc_of(tok),
            ft=pm["ft"] if pm and pm["ft"] is not None else "", inch=pm["in"] if pm and pm["in"] is not None else "",
            note="an additional value between breadth and depth; its kind is not stated in the source or the glossary")
    depth = re.split(r"\.\s|\.$", parts[2])[0]
    dq = re.search(r"\(([^)]*)\)", depth)
    put("DepthInHold", re.sub(r"\([^)]*\)", "", depth), qual=dq.group(1) if dq else "")
    if extra and facts_ref:   # L3：最後の値を深さとするのは書式の位置からの推定なので、要確認にする
        last = facts_ref[-1]
        if last[3] == "DepthInHold" and last[13] == "parsed":
            last[13] = "needs_review"
            last[14] = "; ".join(filter(None, [last[14], "taken as depth by its position after an extra value (rule L3)"]))
    vals_for_formula[(sid, n)] = vals


vals_for_formula = {}
PMS = {}
SHIP_INFO = {}   # 艦の記号 → [艦名, クラス名, 艦種]（目視確認ファイルで本の該当箇所を探しやすくするため。2026-10-05）
facts_ref = []   # main() の facts（L3 で直前の値の状態を変えるため）
WARN = 0.005   # F1：解析済みの値で、式と原文の bm の相対差がこれを超えたら formula_check.csv で警告にする
# 解析済み107区間の差の中央値は 0.002%、97区間が 0.5% 以内（2026-10-05）。差の分布に裾があるので、許容幅で候補を
# 1つに絞ることはせず、差の小さい順に上位3つを差の値つきで示す
# F2（2026-10-05 ユーザー決定、案2）：最も合う候補の差が 0.01% 以下で、次点の差がその5倍以上（差が 0.001% 未満なら
# 0.001% とみなして比べる）の場合に限り、その候補を記録の層の値とする。status=formula_resolved とし、目視確認の対象にする
F2_BEST, F2_RATIO, F2_FLOOR = 0.0001, 5, 0.00001


def formula_pass(facts):
    """F1：区間ごとに bm を検算し、要確認の値に式に合う候補を付ける（候補は参考。記録の値は変えない）"""
    rows = []
    segs = collections.defaultdict(dict)
    for x in facts:
        segs[(x[0], x[1])].setdefault(x[3], x)
    for (sid, n), kinds in segs.items():
        k, b, t = kinds.get("KeelLengthForTonnage"), kinds.get("BreadthForTonnage"), kinds.get("BuildersMeasurement")
        if not (k and b and t):
            continue

        def opts_len(x):
            """（ft 換算の値、表示、(ft, in)）の候補"""
            if x[13] == "parsed":
                return [(to_ft(int(x[5]), float(x[6] or 0)), None, None)]
            pm = x[16]
            return [(to_ft(f, i), fmt_ftin_pair(f, i), (f, i)) for f, i in inch_candidates(pm)] \
                if pm and pm["ft_raw"] else []

        def opts_bm(x):
            """（bm の値、表示、(整数, 分子)）の候補"""
            if x[13] == "parsed":
                return [(bm_value(int(x[7]), int(x[8] or 0)), None, None)]
            if x[15]:
                out = []
                for c in x[15].split(" | "):
                    w, fr = c.split(" ")
                    out.append((bm_value(int(w), int(fr.split("/")[0])), c, (int(w), int(fr.split("/")[0]))))
                return out
            if x[7] != "":   # 端数が読めない（T3）
                return [(int(x[7]) + j / 94, f"{x[7]} {j}/94", (int(x[7]), j)) for j in range(94)]
            return []

        ks, bs, ts = opts_len(k), opts_len(b), opts_bm(t)
        if not (ks and bs and ts):
            continue
        if len(ks) == len(bs) == len(ts) == 1:
            calc = ks[0][0] * bs[0][0] ** 2 / 188
            diff = (calc - ts[0][0]) / ts[0][0]
            rows.append([sid, n, round(ks[0][0], 4), round(bs[0][0], 4), round(ts[0][0], 4), round(calc, 2),
                         round(diff, 5), "warning: differs by more than 0.5%" if abs(diff) > WARN else ""])
            continue
        # 要確認の値ごとに、候補（表示）→ 式との最小の差。上位3つを参考として示し、F2 の条件を満たせば値を決める
        combos = [(abs(kv[0] * bv[0] ** 2 / 188 - tv[0]) / tv[0], kv, bv, tv) for kv in ks for bv in bs for tv in ts]
        for x, idx in ((k, 1), (b, 2), (t, 3)):
            if x[13] == "parsed":
                continue
            best = {}
            for c in combos:
                lab, payload = c[idx][1], c[idx][2]
                if lab not in best or c[0] < best[lab][0]:
                    best[lab] = (c[0], payload)
            ranked = sorted(best.items(), key=lambda kv: kv[1][0])
            top = " | ".join(f"{lab} ({d:.3%})" for lab, (d, _) in ranked[:3])
            prev = x[15]
            x[15] = "closest to the formula: " + top + (f"; parsed candidates: {prev}" if prev else "")
            # F2：最も合う候補の差が F2_BEST 以下で、次点の差がその F2_RATIO 倍以上なら、その候補を値とする
            if len(ranked) >= 2 and x[13] == "needs_review":
                (lab1, (d1, pay1)), (lab2, (d2, _)) = ranked[0], ranked[1]
                if d1 <= F2_BEST and d2 >= F2_RATIO * max(d1, F2_FLOOR):
                    if idx == 3:
                        x[7], x[8] = pay1
                    else:
                        x[5], x[6] = pay1
                    x[13] = "formula_resolved"
                    x[12] = " ".join(sorted(set(x[12].split()) | {"F2"}))
                    x[14] = "; ".join(filter(None, [x[14], f"F2: chosen {lab1} ({d1:.3%}); next {lab2} ({d2:.3%}); "
                                                           "requires visual check against the page image"]))
        rows.append([sid, n, "", "", "", "", "", "needs review; see dimension_review.csv"])
    return rows


def value_text(x):
    """記録した値の表示（目視確認ファイル用）"""
    if x[3] == "BuildersMeasurement":
        return f"{x[7]} {x[8]}/94" if x[7] != "" and x[8] != "" else (f"{x[7]} ?/94" if x[7] != "" else "")
    if x[3] == "Displacement":
        return str(x[9])
    return f"{x[5]}ft {float(x[6]):g}in" if x[5] != "" and x[6] != "" else ""


def suggestion(x):
    if x[13] == "formula_resolved":
        return value_text(x)
    m = re.match(r"closest to the formula: ([^(]+?) \(", x[15] or "")
    return m.group(1) if m else ""


def parse_corrected(kind, text):
    """'70ft 5in' '70ft 5½in' '70ft 5.5in' → (ft, in)、'253 6/94' '1,081' → (整数, 分子)"""
    t = re.sub(r"\s*(?:bm|tons?|oa\.?|for (?:tonnage|tons)|mid\.?)\s*$", "", text.strip(), flags=re.I).strip()
    if kind == "BuildersMeasurement":
        # 表計算ソフトが "253 6/94" を約分して "253 3/47" と保存することがあるので、94分の1に戻せる分数は受け入れる
        m = re.fullmatch(r"([\d,]+)(?:\s+(\d{1,2})/(\d{1,2}))?", t)
        if not m:
            return None
        num, den = int(m.group(2) or 0), int(m.group(3) or 94)
        if den == 0 or (num * 94) % den or num * 94 // den >= 94:
            return None
        return int(m.group(1).replace(",", "")), num * 94 // den
    m = re.fullmatch(r"(\d+)\s*ft\s*(\d+(?:\.\d+)?)?\s*([½¼¾⅛⅜⅝⅞])?\s*(?:in)?", t)
    if not m:
        return None
    return int(m.group(1)), float(m.group(2) or 0) + (FRAC[m.group(3)] if m.group(3) else 0)


def apply_visual_checks(facts):
    """V1：人が記入した目視確認の結果を反映する。ファイルが無ければ、確認の対象を書き出して作る（上書きはしない）"""
    targets = [x for x in facts if x[13] != "parsed"]
    key = lambda x: (x[0], str(x[1]), x[3], x[4])
    info = collections.Counter()
    if not os.path.exists(MANUAL):
        os.makedirs(os.path.dirname(MANUAL), exist_ok=True)
        write(MANUAL, MANUAL_HEADER, [[x[0], *SHIP_INFO.get(x[0], ["", "", ""]), x[1], x[2], x[3], x[4], x[13], suggestion(x), x[14] if x[13] == "formula_resolved"
                                       else (x[15] or x[14]), "", "", "", "", ""] for x in targets])
        info["manual_file_created"] = 1
    checks = {(r["ship"], r["segment"], r["kind"], r["raw"]): r for r in csv.DictReader(open(MANUAL, encoding="utf-8-sig"))}
    missing = []
    for x in targets:
        r = checks.get(key(x))
        if r is None:
            missing.append([x[0], *SHIP_INFO.get(x[0], ["", "", ""]), x[1], x[2], x[3], x[4], x[13], suggestion(x),
                            x[15] or x[14], "", "", "", "", ""])
            continue
        v = (r["visual_check"] or "").strip().lower()
        if not v:
            info["not_yet_checked"] += 1
            continue
        who = ", ".join(filter(None, [r["checked_by"], r["checked_on"]]))
        if v == "confirmed" and x[13] == "formula_resolved":
            x[13] = "visually_confirmed"
        elif v == "confirmed" and parse_corrected(x[3], suggestion(x) or "") is not None:
            # 参考として示した候補（式との差が最も小さいもの）を、目視で正しいと確認した
            val = parse_corrected(x[3], suggestion(x))
            if x[3] == "BuildersMeasurement":
                x[7], x[8] = val
            else:
                x[5], x[6] = val
            x[13] = "visually_confirmed"
        elif v == "corrected":
            val = parse_corrected(x[3], r["corrected_value"])
            if val is None:
                info["corrected_value_unreadable"] += 1
                continue
            same = (x[7], x[8]) == val if x[3] == "BuildersMeasurement" else \
                (x[5] != "" and x[6] != "" and (int(x[5]), float(x[6])) == val)
            if x[3] == "BuildersMeasurement":
                x[7], x[8] = val
            else:
                x[5], x[6] = val
            # 訂正値が式で決めた値と同じなら、確認済みとして扱う
            x[13] = "visually_confirmed" if same and x[13] == "formula_resolved" else "visually_corrected"
        elif v == "unreadable":
            x[14] = "; ".join(filter(None, [x[14], "page image also unreadable"]))
            info["unreadable_in_image"] += 1
            continue
        else:
            info[f"ignored ({v} on {x[13]})"] += 1
            continue
        x[12] = " ".join(sorted(set(x[12].split()) | {"V1"}))
        x[14] = "; ".join(filter(None, [x[14], f"visual check: {v}" + (f" ({who})" if who else "")
                                        + (f"; {r['note']}" if r["note"] else "")]))
        info[x[13]] += 1
    info = dict(info)
    info["missing"] = missing
    return info


def final_formula_check(facts):
    """F1：目視確認を反映した後の、値が確定したもの（parsed・formula_resolved・visually_*）で bm を検算する"""
    fixed = ("parsed", "formula_resolved", "visually_confirmed", "visually_corrected")
    segs = collections.defaultdict(dict)
    for x in facts:
        segs[(x[0], x[1])].setdefault(x[3], x)
    rows = []
    for (sid, n), kinds in segs.items():
        k, b, t = kinds.get("KeelLengthForTonnage"), kinds.get("BreadthForTonnage"), kinds.get("BuildersMeasurement")
        if not (k and b and t):
            continue
        if not all(x[13] in fixed for x in (k, b, t)) or "" in (k[5], k[6], b[5], b[6], t[7], t[8]):
            rows.append([sid, n, "", "", "", "", "", "not checked: a value is not determined (see dimension_review.csv)"])
            continue
        kv, bv = to_ft(int(k[5]), float(k[6])), to_ft(int(b[5]), float(b[6]))
        tv = bm_value(int(t[7]), int(t[8]))
        calc = kv * bv * bv / 188
        diff = (calc - tv) / tv
        src = sorted({x[13] for x in (k, b, t)} - {"parsed"})
        rows.append([sid, n, round(kv, 4), round(bv, 4), round(tv, 4), round(calc, 2), round(diff, 5),
                     "; ".join(filter(None, ["warning: differs by more than 0.5%" if abs(diff) > WARN else "",
                                             ("includes " + ", ".join(src)) if src else ""]))])
    return rows


def fmt_ftin_pair(ft, inch):
    return f"{ft}ft {inch:g}in"


def fmt_ftin(v):
    ft = int(v + 1e-9)
    inch = round((v - ft) * 12 * 8) / 8
    return f"{ft}ft {inch:g}in"


def write(path, header, rows):
    with open(path, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        w.writerows(rows)


if __name__ == "__main__":
    main()
