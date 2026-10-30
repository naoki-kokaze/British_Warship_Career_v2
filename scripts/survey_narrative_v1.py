"""規則v1の対応表の草案のために、Winfield原文の経歴の叙述部分の言い回しを数える（調査用。RDFは作らない）

入力（読み取りのみ）: ../sources/v1/strata/*.xlsx（269隻）
出力: ../outputs/rules_v1_survey/
    category_counts.csv    言い回しの種類ごとの、節の数・艦の数・例
    clauses.csv            節ごとの、当てはまった種類（なしを含む）
    unmatched_sample.csv   どの種類にも当てはまらない節（無作為に100件）
    summary.json
    role_contexts.csv      役割（"as a receiving ship" など）ごとの、出てくる言い回し（文脈）と、その後に就役が続くか
../sources/manual/role_seagoing_judgement.csv
                           役割ごとの判断の記入用（航海する用途か、港に留まる用途か）。無ければ作るだけで上書きしない

節の切り方: 見出し行（艦名・造船所）と定型部分（Ord:・K:・L:・C:・寸法・First cost・Men・Guns・Machinery）を除き、
"; " と、略語（Capt. Cmdr. Dyd. など）以外の ". "＋大文字 で区切る。数字の間のOCR由来の空白は詰める。
種類（CATEGORIES）は、対応表の草案の行に当たる。1つの節が複数の種類に当てはまってよい。
"""
import collections
import csv
import glob
import json
import os
import random
import re

import openpyxl

import sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import dataset_paths as P   # 開発用／評価用の切り替え（JINMON_DATASET）
SRC = P.STRATA
OUT = P.out("rules_v1_survey")

HEAD = re.compile(r"^(Ord|Re-ord|\(Re-\)L|K|L|C|First cost|Men|Guns|Machinery|As built|As lengthened|As converted|"
                  r"Dimensions|Tonnage as completed|Draught|Conversion Ord|Begun|Design|Armament|App)\b|"
                  r"^Completed(?:\s+fitting)?\s+[\d.?]+\.?$|"   # 3周目：日付だけの "Completed D"（定型部分。規則 F2 が扱う。"Completed 12.1849 at X as ..." などの叙述は対象外）
                  r"^(?:UD|LD|MD|QD|Fc|Fe|OD|RH)\s+\d|^[\d,.;/ ]*\s?bm\b|^[A-Z]$|^[\d,.]+\s?disp", re.I)
ABBR = r"(?<!Capt)(?<!Cmdr)(?<!Lieut)(?<!Dyd)(?<!Adm)(?<!St)(?<!No)(?<!Mr)(?<!Co)(?<!Bros)(?<!Ltd)(?<!Rear-Adm)(?<![\s.(][A-Z])"  # 人名の頭文字（G. Bailey）では切らない
D = r"\d{1,2}\.\d{4}|\d{1,2}\.\d{1,2}\.\d{4}|\d{4}"
OFFICER = r"(?:Capt|Cmdr|Commander|Captain|Lieut|Lieutenant|Master|Mate|Second Master|Staff Cmdr|Navigating Lieut)"

# 種類：(ID, 名前, 正規表現, 対応の案（オントロジ）, 状態の軸への影響)
CATEGORIES = [
    ("EV01", "commissioned", r"(?<!re)(?<!never )(?<!not )\bcommissioned\b", ":Commissioning（E7）", "service → :InCommission"),
    ("EV02", "recommissioned", r"\brecommissioned\b", ":Recommissioning（E7）", "service → :InCommission"),
    ("EV03", "officer change (On/In/From/then D under ...)",
     rf"^(?:on|in|from|then|and)\s+(?:{D})?.{{0,15}}\bunder\s+{OFFICER}|(?:^|,\s*)then\s+(?:{D})\s+under\s+{OFFICER}|"
     rf"^under\s+{OFFICER}|\bunder\s+[A-Z][^,;]*?,\s*(?:Master|Second Master)\b",
     "（要決定）艦長交代＝同じ就役の続き", "変化なし（要決定）"),
    ("EV04", "paid off", r"\bpaid\s+of\s?f\b(?!\s+into\s+(?:ordinary|(?:the\s+)?steam\s+reserve))", ":Decommissioning（E7）", "service → :PaidOff"),
    ("EV05", "paid off into Ordinary", r"\bpaid\s+of\s?f\b.{0,30}\binto\s+(?:ordinary|(?:the\s+)?steam\s+reserve)\b", ":Decommissioning（E7）",
     "service → :InOrdinary（退役後の期間を作らない。決定B1）"),
    ("EV06", "laid up / in Ordinary", r"\blaid\s+up\b|\bin\s+ordinary\b|\bsteam\s+reserve\b|\bin\s+reserve\b", "（出来事なし）", "service → :InOrdinary"),
    ("EV07", "fitted for sea", r"\bfitted\s+(?:out\s+)?for\s+sea\b", ":FittingForSea（E11）", "work → :UnderFitting"),
    ("EV08", "fitted for Ordinary", r"\bfitted\s+for\s+ordinary\b", ":FittingForOrdinary（E11）", "work → :UnderFitting"),
    ("EV09", "fitted as <role>", r"\bfitted\s+(?:out\s+)?as\b", ":ShipConversion（E11）＋役割",
     "service → :InNonCombatDuty（役割による。要決定）"),
    ("EV10", "fitted (other) / refitted", r"\b(?:re)?fitted\b(?!\s+(?:out\s+)?(?:for\s+sea|for\s+ordinary|as)\b)|\brefit\b",
     ":Fitting / :Refit（E11）", "work → :UnderFitting（目的による）"),
    ("EV11", "repair (Small/Middling/Large/Great)", r"\b(?:small|middling|large|great)\s+repair", ":SmallRepair 等（E11）",
     "work → :UnderRepair"),
    ("EV12", "repaired / repair (other)", r"\brepair(?:ed|s)?\b(?<!small repair)(?<!middling repair)(?<!large repair)(?<!great repair)",
     "sealit:ShipRepair（E11）", "work → :UnderRepair"),
    ("EV13", "converted / conversion", r"\bconver(?:ted|sion)\b", ":ShipConversion / :ScrewConversion（E11）",
     "（改造の内容による）"),
    ("EV14", "sold", r"\bsold\b", "E96_Purchase（E8）＋P179（金額）", "キャリアの終わり"),
    ("EV15", "BU (by the Navy)", r"\bB\s?U\b|\bbroken\s+up\b|\bbreaking\s+up\b", "E6_Destruction",
     "service → :BeingBrokenUp（売却後の BU は除く。決定D1）"),
    ("EV16", "lent to / loan", r"\blent\b|\bloan(?:ed)?\b", "E10 ＋ :Loan", "（キャリアの扱いは分析の層。決定F）"),
    ("EV17", "transferred to", r"\btransferred\b", "E10 ＋ :Transfer", "（同上）"),
    ("EV18", "to the coastguard / to <department> (verbless)", r"\bt\s?o\s+(?:the\s+)?(?:coastguard|coast\s+guard|war\s+dep|customs|board\s+of\s+trade)",
     "（要決定）E10 ＋ :Transfer か", "（要決定）"),
    ("EV19", "renamed / named", r"\b(?:re)?named\b", "E15_Identifier_Assignment", "変化なし"),
    ("EV20", "reduced / re-rated / re-classed", r"\breduced\s+to\b|\bre-?(?:rated|classed)\b|\bcut\s+down\b|\bras[eé]e", "E13 ＋ :changes_ship_rating",
     "変化なし（等級は Presence の型）"),
    ("EV21", "harbour roles (hulk, receiving, depot, guard, training, ...)",
     r"\bhulked\b|\bbecame\b|\b(?:hulk|receiving\s+ship|depot|guard\s?ship|training\s+ship|hospital\s+ship|lazarette|powder|coal|prison|"
     r"store\s?ship|tender|accommodation|barracks|quarantine|cholera|chapel|school\s+ship|breakwater)\b",
     "役割（:has_ship_role）", "service → :InNonCombatDuty（要決定）"),
    ("EV22", "wrecked / foundered / lost / burnt", r"\bwreck(?:ed)?\b|\bfounder(?:ed)?\b|\blost\b|\bburnt\b|\bburned\b|\bexplod|\bsunk\b|\bsank\b",
     "E6_Destruction（喪失）", "キャリアの終わり"),
    ("EV23", "taken / captured (by the enemy)", r"\btaken\s+by\b|\bcaptured\s+by\b", "E8（拿捕による喪失）",
     "キャリアの終わり"),
    ("EV24", "purchased / taken (acquisition)", r"\bpurchased\b|^taken\s+(?:\d|on|in|by\s+(?:the\s+)?(?:british|hms))",
     "E8 / E96（取得）", "キャリアの始まり"),
    ("EV25", "operations (sailed, arrived, in action, took <prize>, battle, ...)",
     r"\bsailed\b|\barrived\b|\bin\s+action\b|\btook\b|\bbattle\b|\bbombardment\b|\bbombarded\b|\boperations\b|"
     r"\bcaptured\b|\bengaged\b|\bescorted\b|\bconveyed\b|\bcruise\b",
     "（範囲外の候補）作戦上の出来事", "変化なし"),
    ("EV26", "flagship / station (for <station>, flagship of)", r"\bflagship\b|\bfor\s+(?:the\s+)?(?:channel|mediterranean|"
     r"east\s+indies|north\s+america|west\s+indies|cape|pacific|china|home|brazil|south\s+america|africa|lisbon|baltic|irish|"
     r"north\s+sea|downs|nore|coast\s+blockade|channel\s+fleet|particular\s+service)\b",
     "（範囲外の候補）配備先・旗艦", "変化なし"),
    ("EV27", "never / not commissioned", r"\b(?:never|not)\s+commiss?i?oned\b", "（出来事なし）注記", "変化なし"),
    ("EV29", "location / movement (At <place> from D, to <place> D)",
     r"^(?:at|to|later\s+at|later\s+to|then\s+at|then\s+to)\s+(?:the\s+)?[A-Z]", "Presence の場所（P167）", "変化なし（場所）"),
    ("EV30", "dismasted / damaged / defects", r"\bdismasted\b|\bdamaged\b|\bdefect", "（範囲外の候補）損傷", "変化なし"),
    ("EV31", "presented / given (gift)", r"\bpresented\s+to\b|\bgiven\s+to\b|\bgift\b", "E8（贈与。所有権の移転）",
     "キャリアの終わり"),
    ("EV28", "housed over / stored", r"\bhoused\s+over\b|\bstored\b", "（出来事なし）予備役の状態の注記", "（要決定）"),
]
COMPILED = [(cid, name, re.compile(rx, re.I), m, a) for cid, name, rx, m, a in CATEGORIES]


ROLE_HEADS = (r"ship|vessel|hulk|depot|tender|troopship|storeship|store\s?ship|flagship|packet|lazarette|hospital|"
              r"prison|barracks|chapel|lighter|tug|dredger|school|breakwater|magazine|yacht|craft|cutter|schooner|"
              r"guardship|blockship|block\s?ship|battery|factory|workshop|church|accommodation|museum|target")
ROLE_RE = re.compile(r"\b(?:as|became|become|becomes|hulked(?:\s+at\s+[A-Z][\w ]*?)?\s+as)\s+(?:(?:a|an|the)\s+)?"
                     r"((?:[A-Za-z'&-]+\s+){0,4}?(?:" + ROLE_HEADS + r"))\b", re.I)
CONTEXTS = [("commissioned", r"\b(?:re)?commissioned\b"), ("fitted", r"\b(?:re)?fitted\b|\bconverted\b|\bcompleted\b"),
            ("became", r"\bbecame\b|\bbecome\b"), ("hulked", r"\bhulked\b"), ("paid_off", r"\bpaid\s+of\s?f\b"),
            ("lent", r"\blent\b|\bloan"), ("sold", r"\bsold\b|\bresold\b"), ("transferred", r"\btransferred\b"),
            ("harbour_service", r"\bharbour\s+service\b")]
ROLE_STOP = {"a", "an", "the", "her", "his", "temporary", "permanent", "new", "former", "partially"}
MANUAL_ROLES = P.ROLE_JUDGEMENT


def role_mentions(clause):
    """節の中の役割と、その前で最も近い言い回し（文脈）"""
    out = []
    for m in ROLE_RE.finditer(clause):
        words = [w for w in re.sub(r"\s+", " ", m.group(1).lower()).split() if w not in ROLE_STOP]
        words = [w for w in words if not re.fullmatch(r"\d+-gun|\d+", w)]
        role = " ".join(words).replace("store ship", "storeship").replace("guardship", "guard ship")
        before = clause[:m.start()]
        ctx, pos = "other", -1
        for name, rx in CONTEXTS:
            for mm in re.finditer(rx, before, re.I):
                if mm.start() > pos:
                    ctx, pos = name, mm.start()
        if m.group(0).lower().startswith(("became", "become")):
            ctx = "became"
        if m.group(0).lower().startswith("hulked"):
            ctx = "hulked"
        out.append((role, ctx, m.end()))
    return out


# 定型部分の節に続いてしまった叙述の書き出し（"C: ... at Deptford Dyd. Commissioned ..."、"First cost: ... Commissioned ..."）
# 2026-10-14：竣工に続く ", then laid up"（"C: 11.9-20.9.1813 at Plymouth for Ordinary, then laid up"。試しの判定 SF5_9041）も
NARR_START = re.compile(r"(?:\s|,\s*)(?=(?:Commissioned|Recommissioned|Fitted|Laid up|In Ordinary|Paid off|Hulked|Became|Lent|"
                        r"Sold|Renamed|Purchased|Taken|Transferred|Registered|then\s+(?:laid up|to Ordinary|in Ordinary))\b)")


def split_head(p):
    """2周目（2026-10-07）：定型部分の節の中に叙述の書き出しがあれば、そこから後を叙述の節として返す（括弧の外のみ）"""
    for m in NARR_START.finditer(p):
        before = p[:m.start()]
        if before.count("(") <= before.count(")"):
            return p[m.end():].strip()
    return ""


def clauses(text):
    lines = text.split("\n")
    title, lines = lines[0], lines[1:]
    # 2周目（2026-10-07）：見出しの行の閉じていない角括弧（"BOXER 1837-41 [ex-PO Ivanhoe, ... first purchased in December
    # 1821 by the PO ..."）の続きは見出しの一部（取得前の経歴）。"]" か定型部分の行までを除く（OCR で "]" が落ちることがある）
    if title.count("[") > title.count("]"):
        while lines:
            if "]" in lines[0]:
                lines[0] = lines[0].split("]", 1)[1]
                break
            if HEAD.match(lines[0].strip()):
                break
            lines.pop(0)
    flat = " ".join(lines)
    flat = re.sub(r"(?<=\d)\s+(?=[\d.])|(?<=\.)\s+(?=\d)", "", flat)
    parts = re.split(ABBR + r"\.\s+(?=[A-Z(])|;\s+", flat)
    out = []
    for p in (x.strip() for x in parts):
        if not p:
            continue
        if HEAD.match(p):
            p = split_head(p)
            if not p:
                continue
        out.append(p)
    return out


def main():
    os.makedirs(OUT, exist_ok=True)
    ships = []
    for f in sorted(glob.glob(os.path.join(SRC, "*.xlsx"))):
        rows = list(openpyxl.load_workbook(f, read_only=True).worksheets[0].iter_rows(values_only=True))
        for r in rows[1:]:
            d = dict(zip(rows[0], r))
            ships.append((f"{d['Prefix']}_{int(d['serial_no']):04d}", str(d.get("Name") or ""), str(d["text"] or "")))

    rows, cnt, sh, ex = [], collections.Counter(), collections.defaultdict(set), collections.defaultdict(list)
    for sid, name, text in ships:
        for i, c in enumerate(clauses(text), 1):
            hits = [cid for cid, _, rx, _, _ in COMPILED if rx.search(c)]
            rows.append([sid, i, c, " ".join(hits)])
            for h in hits:
                cnt[h] += 1
                sh[h].add(sid)
                if len(ex[h]) < 3:
                    ex[h].append(f"{sid}: {c[:110]}")
    unmatched = [r for r in rows if not r[3]]
    multi = [r for r in rows if len(r[3].split()) > 1]
    with open(os.path.join(OUT, "category_counts.csv"), "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(["id", "pattern", "clauses", "ships", "mapping (draft)", "state axis (draft)", "examples"])
        for cid, name, _, m, a in COMPILED:
            w.writerow([cid, name, cnt[cid], len(sh[cid]), m, a, " || ".join(ex[cid])])
    with open(os.path.join(OUT, "clauses.csv"), "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(["ship", "clause_no", "clause", "categories"])
        w.writerows(rows)
    random.seed(20261005)
    with open(os.path.join(OUT, "unmatched_sample.csv"), "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(["ship", "clause_no", "clause"])
        w.writerows([r[:3] for r in random.sample(unmatched, min(100, len(unmatched)))])
    # 役割の文脈と、その後に就役が続くか（同じ節の役割の後ろか、艦の次の節以降で、地位に関わる最初の言い回し）
    STATUS = {"EV01": "commission", "EV02": "commission", "EV04": "paid_off", "EV05": "paid_off", "EV06": "ordinary",
              "EV14": "sold", "EV15": "broken_up", "EV16": "lent", "EV17": "transferred", "EV22": "lost"}
    byship = collections.defaultdict(list)
    for r in rows:
        byship[r[0]].append(r)
    roles = collections.defaultdict(lambda: {"n": 0, "ships": set(), "ctx": collections.Counter(),
                                             "fitted_next": collections.Counter(), "ex": []})
    for sid, cl in byship.items():
        for i, r in enumerate(cl):
            for role, ctx, end in role_mentions(r[2]):
                d = roles[role]
                d["n"] += 1
                d["ships"].add(sid)
                d["ctx"][ctx] += 1
                if len(d["ex"]) < 3:
                    d["ex"].append(f"{sid}: {r[2][:120]}")
                if ctx == "fitted":
                    rest = r[2][end:]
                    nxt = "commission" if re.search(r"\b(?:re)?commissioned\b", rest, re.I) else None
                    for later in cl[i + 1:]:
                        if nxt:
                            break
                        for cid in later[3].split():
                            if cid in STATUS:
                                nxt = STATUS[cid]
                                break
                    d["fitted_next"][nxt or "none"] += 1
    ctx_names = [c for c, _ in CONTEXTS] + ["other"]
    role_rows = []
    for role, d in sorted(roles.items(), key=lambda kv: (-kv[1]["n"], kv[0])):
        fn = d["fitted_next"]
        role_rows.append([role, d["n"], len(d["ships"])] + [d["ctx"][c] for c in ctx_names] +
                         [sum(fn.values()), fn["commission"], "; ".join(f"{k}:{v}" for k, v in fn.most_common()),
                          " || ".join(d["ex"])])
    role_header = (["role", "mentions", "ships"] + [f"ctx_{c}" for c in ctx_names] +
                   ["fitted_as_mentions", "fitted_then_commissioned", "fitted_then (next status-related phrase)", "examples"])
    with open(os.path.join(OUT, "role_contexts.csv"), "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(role_header)
        w.writerows(role_rows)
    if not os.path.exists(MANUAL_ROLES):
        os.makedirs(os.path.dirname(MANUAL_ROLES), exist_ok=True)
        with open(MANUAL_ROLES, "w", newline="", encoding="utf-8-sig") as fh:
            w = csv.writer(fh)
            w.writerow(["role", "mentions", "ships", "contexts", "fitted_as_then", "examples",
                        "judgement (seagoing / harbour / either / not_a_role)", "note"])
            for rr in role_rows:
                ctxs = "; ".join(f"{c}:{v}" for c, v in zip(ctx_names, rr[3:3 + len(ctx_names)]) if v)
                w.writerow([rr[0], rr[1], rr[2], ctxs, rr[-2], rr[-1], "", ""])

    summary = {"ships": len(ships), "clauses": len(rows), "matched": len(rows) - len(unmatched),
               "roles": len(role_rows),
               "unmatched": len(unmatched), "multi_category": len(multi),
               "by_category": {cid: [cnt[cid], len(sh[cid])] for cid, *_ in COMPILED}}
    with open(os.path.join(OUT, "summary.json"), "w", encoding="utf-8") as fh:
        json.dump(summary, fh, ensure_ascii=False, indent=2)
    print(json.dumps({k: v for k, v in summary.items() if k != "by_category"}, ensure_ascii=False))
    for cid, name, *_ in COMPILED:
        print(cid, cnt[cid], len(sh[cid]), name)


if __name__ == "__main__":
    main()
