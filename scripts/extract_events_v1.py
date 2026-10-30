"""規則v1：Winfield原文の経歴の叙述部分から、出来事を決定論的に取り出す（Presence の組み立てと RDF 化は別の段階）

入力（読み取りのみ）:
    ../sources/v1/strata/*.xlsx（269隻）
    ../sources/manual/role_seagoing_judgement.csv（B4 の判断。未記入の役割は status_effect=pending_B4 のまま）
出力: ../outputs/rules_v1/
    events.csv          出来事（1行1出来事。原文の順。規則ID・ID（案c）つき）
    events_review.csv   日付が読めない・相手が決まらないなど、人の確認が要るもの
    coverage.csv        対応表の言い回しに当たる節のうち、出来事を作れなかった節
    summary.json

依存: openpyxl（日付の読み取りは extract_header_v0.py の部品を使う）
対応表: ../docs/jinmoncom2026_rules_v1_mapping_draft_20261005.md（§2・§5）

方針
    - 節の中で出来事の動詞（トリガー）を探し、トリガーから次のトリガーまでを1つの出来事の範囲とする（S10）
    - 範囲の中から日付（D1・D2 を再利用）、場所、艦長、金額、役割、相手を取り出す
    - 記録の層：原文にないことは作らない。艦長の任命から就役を導かない（決定B1）。B4（役割による地位）は判断待ち
    - status_effect は Presence の組み立てで使う「状態の軸への影響」。pending_* は未決の事項に依存するもの

規則の一覧（EV の番号は対応表の行。S・T・P などは取り出しの補助規則）
    S10  トリガーで節を出来事の範囲に分ける
    S11  日付のない工事の範囲が "and" で次の工事につながるとき、1つの出来事にまとめ、両方の型を付ける（決定C1）
    S12  日付のない範囲が "and" で次の範囲（日付あり）につながるとき（"paid off and laid up at X 5.1829"）、その日付を共有する
    T12  "after D" "before D" "by D" → date_role に after / before / by を残す（日付は境界として記録し、uncertain）
    T13  "X or Y" の日付（"8 or 9.1815"）→ 要確認（A1 と同じ扱い）
    P13  "at Battle of ..." "at the bombardment of ..." は場所にしない
    T10  日付：範囲の中の最初の日付（単一・期間）。"from D" は始まりだけ、"to D" は終わりだけ
    T11  月名の日付（"18 October 1839"、"July 1855"）を数字の形に直す
    P10  場所："at <地名>"。"there" は、その艦で直前に出た場所（P11）。"by <業者>, <地名>" の地名（P14、2026-10-14）
    P16  就役・再就役に場所がなく、郵便船・沿岸警備の役割の印（stations_v1 の ST3）に港の名前があれば、それを場所にする
         （"recommissioned as Falmouth packet"・"for the Falmouth mail packet service"。指示書 §2.10。2026-10-17、試しの判定 SBS_9095）。
         港の名前がその文にある場合だけ（"on same station" で前の役割から引き継いだ港は推測なので入れない）
    P12  金額："(for £N)"（複数の金額は合計しない。最初の金額を記録し、残りは注記）
    O10  艦長："under <階級> <名前>" ／ "under <名前>, Master"
    EV01 Commissioned → :Commissioning（service → InCommission）
    EV02 Recommissioned → :Recommissioning（service → InCommission）。3周目：綴りの誤り "Recommisioned" も受け入れる
    EV03 "on/in/from/then D under ..."、文頭の "Under ..."、"Commanded from D by ..." → :CommandAppointment（状態を変えない）
    EV04 paid off → :Decommissioning（service → PaidOff）。"paid off as <role>" は役割を記録（B4 待ち）
    EV05 paid off ... into Ordinary / Steam Reserve → :Decommissioning（service → InOrdinary）
    EV06 laid up / in Ordinary / Steam Reserve / in reserve → 地位の印（service → InOrdinary。Steam Reserve などの呼び名は注記に残す。決定B6）
    EV07 fitted for sea → :FittingForSea（work → UnderFitting）
    EV08 fitted for Ordinary → :FittingForOrdinary（work → UnderFitting）
    EV09 Fitted as <role> → :Fitting＋役割（work → UnderFitting。その後の地位は B4 待ち）。2026-10-14："Fitted for quarantine service" も
    EV10 Fitted / Refitted / Refit / Fitted with → :Fitting / :Refit / 改造（E11）。3周目：叙述の "Completed fitting (at X / there) D" も艤装
    EV11 (Very) Small / Middling / Large / Great Repair、"Between X and Y Repair" → 修理の型（work → UnderRepair）
    EV12 Repaired / Repairs / Repair → sealit:ShipRepair（work → UnderRepair）。3周目：Re-engined・Reboilered（機関・汽缶の換装）も
         工廠での工事として修理に入れる（10/7 の人の確認 PF_0008・PSPV_0005・PF_0002 に揃える）
    EV13 converted / conversion → :ShipConversion / :ScrewConversion
    EV14 Sold → E96_Purchase（買い手・金額）。"to/for BU" は解体業者への売却（海軍の BU は作らない。決定D1）
    EV15 BU（海軍自身）→ E6_Destruction（service → BeingBrokenUp）。"completed" は終わりの日付
    EV16 Lent → E10＋:Loan（service → InOtherCustody。決定F）、"loan terminated" / "Returned to Admiralty" → 貸与の終わり（E10。
         InOtherCustody を終える。その後の地位は推測で埋めない）
    EV17 Transferred → 相手で分ける（決定B2）：to coastguard＝E10＋:Transfer、to <...> Government＝E8、
         見出しが郵政省の船（ex-PO）で相手なし＝E10＋:Transfer（海軍へ。キャリアの始まり）、人の異動＝作らない
    EV18 To (the) coastguard → E10＋:Transfer
    EV19 Renamed <name> D / Named D → E15
    EV20 re-classed / re-rated / reduced to / cut down → E13＋:changes_ship_rating
    EV21 Became / Hulked (as) <role> → 役割（B4 待ち）
    EV14・EV15 の日付（2026-10-07）：U1 "by/under AO (of) D" は売却・解体の命令の日付（order_date）で、売却・解体の日付にしない。
         3周目（2026-10-08）：U1 を工事（EV07〜EV13）と等級の変更（EV20）にも広げる（AO の他に日付があるときだけ）
         U2 "BU completed D" は終わりの日付だけ（始まりは原文にない）
    S14 日付が言い回しの前にある形（2周目）：S14a 節の最初のトリガーより前の日付を最初の出来事に、
        S14b 地位の印（laid up・into Steam Reserve など）は and・into・"," でつながる直前の言い回しの日付を引き継ぐ。年の範囲 "1852-53" はすべての出来事で期間（R4）
    EV32 動詞のない役割の文（R1〜R3。どのトリガーにも当たらない節だけ）→ 役割（B4 の判断表で地位）。"1834-50" は期間（R4）
    EV22 wrecked / foundered / lost / burnt / sunk / blew up → E6（喪失）。他の艦の喪失は除く（L1）、同じ節の続きの言い回しは1つに（L2）
    EV23 Taken → "and purchased" が続けば取得（E8）、それ以外は要確認
    EV24 Purchased → E96（取得）。試し（2026-10-08）：他国の政府による購入（"Purchased by US government"）はこの海軍の取得にしない（A2）
    EV31 Presented to / given to → E8（贈与）。試し：英国の国王・海軍への贈与（"presented to Queen Victoria"）は艦歴の始まり（返還。G2）
    試し（2026-10-08、試し5隻で見つかった誤り。試し5隻は評価の数字に入れない）：
        L1 の拡張 "with 16-gun La Vielle Josephine sunk" のように砲数つきの艦名・with ＋艦名の後の sunk は他の艦の喪失
        T12 OCR で切れた "Ordi nary" をつなぐ。O11 "under" のない艦長任命（"In 6.1814 Cmdr ..."）
    EV27 Never / Not commissioned → 注記
    EV28 housed over → 注記（地位は変えない）、stored (in Haslar gunboat shed) → service → InOrdinary＋注記（決定B7）
"""
import collections
import csv
import glob
import importlib.util
import json
import os
import re

import openpyxl

from stations_v1 import find_stations   # 配属先（2026-10-09）

import sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import dataset_paths as P   # 開発用／評価用の切り替え（JINMON_DATASET）
SRC = P.STRATA
OUT = P.out("rules_v1")
ROLE_JUDGEMENT = P.ROLE_JUDGEMENT

_spec = importlib.util.spec_from_file_location("v0", os.path.join(HERE, "extract_header_v0.py"))
V0 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(V0)
_spec2 = importlib.util.spec_from_file_location("survey", os.path.join(HERE, "survey_narrative_v1.py"))
SURVEY = importlib.util.module_from_spec(_spec2)
_spec2.loader.exec_module(SURVEY)

MONTHS = {m: i for i, m in enumerate(["january", "february", "march", "april", "may", "june", "july", "august",
                                      "september", "october", "november", "december"], 1)}
DATE_TOKEN = re.compile(r"(?<![\d£.])(?:\d{1,2}\.){0,2}\d{4}(?!\d)")
OFFICER_RX = (r"(?:(?:Staff|Navigating|Acting|Second)\s+)?(?:Capt\.?|Captain|Cmdr|Commander|Lieut\.?|Lieutenant|"
              r"Master|Mate|Rear-Adm\.?|Vice-Adm\.?|Adm\.?|Commodore)(?:\s+\([^)]*\))?")

# トリガー：(規則ID, 正規表現)。順番は優先度（同じ位置で重なる場合は先のものを採る）
TRIGGERS = [
    ("EV05", r"\bpaid\s+of\s?f\b(?=.{0,40}?\binto\s+(?:ordinary|(?:the\s+)?steam\s+reserve|reserve)\b)"),
    ("EV04", r"\bpaid\s+of\s?f\b"),
    ("EV02", r"\brecommis+ion+ed\b"),   # 3周目：綴りの誤り（Recommisioned）
    ("EV27", r"\b(?:never|not)\s+commiss?i?oned\b"),
    ("EV01", r"\bcommissioned\b"),
    ("EV03", r"(?:^|(?<=[\s,;(]))(?:on|in|from|then|and|later)\s+(?:\??\s*[\d][\d.,\- ]{2,22}?|(?:early|late|mid|summer|spring|"
             r"autumn|winter)\s+\d{4}|\??\s*\d{1,2}\.\d{4}\s+[A-Z]?)\s*under\s+(?=\S)|"
             r"(?:^|(?<=[\s,;(]))(?:on|in|from|then|and)\s+\??\s*(?:\d{1,2}\.){0,2}\d{4}\s+(?=(?:Capt|Cmdr|Lieut|Acting)\b)|"   # O11（試し。10/14 then・and・年だけ・日付つきも：SCSL_9055、"X and D Cmdr Y"）
             r"^under\s+(?=\S)|\bcommanded\s+from\s+|(?:^|(?<=[\s,;]))(?:then|later)\s+under\s+(?=\S)"),
    ("EV07", r"\b(?:re)?fitted\s+(?:out\s+)?for\s+sea\b"),
    ("EV08", r"\bfitted\s+for\s+ordinary\b"),
    ("EV09", r"\b(?:re)?fitted\s+(?:out\s+)?(?:at\s+[A-Z?][\w?]*(?:\s+Dyd)?\s+)?as\b(?!\s+(?:before|well))"
             r"|\bfitted\s+for\s+quarantine\s+service\b"),   # 2026-10-14（試しの判定 SF5_9041）：役割 quarantine service
    ("EV11", r"\b(?:between\s+(?:very\s+)?(?:small|m\s?iddling|large)\s+and\s+)?(?:very\s+)?(?:small|middling|large|great)\s+repair\b"),   # 10/14：OCR の "M iddling"（SF5_9041）
    ("EV12", r"\brepair(?:ed|s)?\b|\bre-?engined\b|\bre-?boilered\b"),   # 3周目：機関・汽缶の換装
    ("EV10", r"\b(?:re)?fitted\b|\brefit\b|\bcompleted\s+fitting\b"),   # 3周目：叙述の Completed fitting
    ("EV13", r"\bconver(?:ted|sion)\b"),
    ("EV14", r"\b(?:re)?sold\b"),
    ("EV15", r"\b(?:completed\s+)?B\s?U\b(?:\s+completed)?|\bbroken\s+up\b|\bbreaking\s+up\b"),
    ("EV16", r"\blent\b|\bloan\s+terminated\b|\breturned\s+to\s+(?:the\s+)?admiralty\b"),
    ("EV17", r"\btransferred\b"),
    ("EV18", r"\bt\s?o\s+(?:the\s+)?(?:coastguard|coast\s+guard)\b"),
    ("EV19", r"\b(?:re-?)?named\b"),
    ("EV20", r"\bre-?(?:rated|classed)\b|\breduced\s+to\b|\bcut\s+down\b"),
    ("EV21", r"\bbecame\b|\bhulked\b"),
    ("EV22", r"\bwrecked\b|\bfoundered\b|\blost\b(?!\s+(?:her|his|a\s|an\s|the\s|\d))|\bburnt\b|\bburned\b|\bsunk\b|\bsank\b|"
             r"\bblew\s+up\b|\bexploded\b|\b(?:blown|driven)\s+ashore\b(?=.*\bwreck)"),   # 2周目：ashore は wreck のある節だけ
    ("EV23", r"\btaken\b(?!\s+(?:in\s+hand|over|out|to|up|off))"),
    ("EV24", r"\bpurchased\b"),
    ("EV31", r"\bpresented\s+to\b|\bgiven\s+to\b"),
    ("EV28", r"\bhoused\s+over\b|\bstored\b"),
    ("EV06", r"\blaid\s+up\b|\bin\s+ordinary\b|\bsteam\s+reserve\b|\bin\s+reserve\b|\bdockyard\s+reserve\b"),
]
TRIG = [(rid, re.compile(rx, re.I)) for rid, rx in TRIGGERS]
WORK_RULES = {"EV07", "EV08", "EV09", "EV10", "EV11", "EV12", "EV13"}


def norm_text(s, rules):
    """T11：月名の日付を数字の形に。v0 の N1〜N3 も適用"""
    def mon(m):
        rules.add("T11")
        d = m.group(1)
        return (f"{int(d)}." if d else "") + f"{MONTHS[m.group(2).lower()]}.{m.group(3)}"
    s = re.sub(r"\b(?:(\d{1,2})\s+)?(" + "|".join(MONTHS) + r")\s+(\d{4})\b", mon, s, flags=re.I)
    t = re.sub(r"\b([Oo])r ?d ?i ?n ?a ?r ?y\b", r"\1rdinary", s)   # T12（試し）：OCR で切れた "Ordi nary"
    if t != s:
        rules.add("T12")
        s = t
    return V0.normalize(s, rules)


def find_date(span, rules):
    """T10：範囲の中の最初の日付。戻り値 (begin, end, bp, ep, uncertain, role)"""
    m = DATE_TOKEN.search(span)
    if not m:
        return None
    pos = m.start()
    # 期間の始まりが省略形（"16.3-11.5.1787" "3-9.1825"）の場合は、前の数字から読む
    pre = re.search(r"((?:\d{1,2}\.){0,2}\d{1,2})\s*[-–]\s*$", span[:pos])
    start = pre.start() if pre else pos
    lead = re.sub(r"[?\s]+$", " ", span[max(0, start - 14):start].lower())
    unc_mark = span[max(0, start - 3):start]
    if re.search(r"\d\s+or\s*$", span[max(0, start - 8):start]):   # T13
        rules.add("T13")
    b, e, bp, ep, unc, _ = V0.parse_date_value(("?" if "?" in unc_mark else "") + span[start:], rules)
    if not b:
        return None
    rules.add("T10")
    role = "point" if b == e else "period"
    if re.search(r"\bfrom\s*$", lead):
        role, e, ep = "from", "", ""
    elif re.search(r"\b(after|before|by)\s*$", lead):   # T12
        rules.add("T12")
        role, unc = re.search(r"\b(after|before|by)\s*$", lead).group(1), True
    elif re.search(r"(?:\bto|\(\s*-|\buntil)\s*$", lead):
        role, b, bp = "to", "", ""
    return b, e, bp, ep, unc, role


def find_place(span, last_place, rules):
    m = re.search(r"\bat\s+(\??[A-Z][A-Za-z'’.-]*(?:\s+(?:Dyd|Dockyard|Bay|Sound|Roads|Hope|of\s+[A-Z][a-z]+|"
                  r"[A-Z][a-z]+))*)", span)
    if m and re.match(r"(?:Battle|Bombardment|Siege|Capture)\b", m.group(1)):   # P13
        m = None
    if m and not re.match(r"(?:Capt|Cmdr|Lieut|AO)\b", m.group(1)):
        rules.add("P10")
        return m.group(1).strip(" .")
    m = re.search(r"\bby\s+(?:Messrs\.?\s+)?[A-Z][\w'&.]*(?:\s+[A-Z&][\w'&.]*)*,\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\b", span)
    if m:   # P14（2026-10-14、試しの判定 SM_9036）："by Green's, Blackwall"・"Repaired by Hill & Mellish, Limehouse"：請負業者の後の地名
        rules.add("P14")
        return m.group(1)
    if re.search(r"\bthere\b", span) and last_place:
        rules.add("P11")
        return last_place
    return ""


def find_amount(span, rules):
    am = re.findall(r"£\s*([\d,]+)", span)
    if not am:
        return "", ""
    rules.add("P12")
    return am[0].replace(",", ""), ("; other amounts: " + ", ".join(am[1:])) if len(am) > 1 else ""


def find_officer(span, rules):
    m = re.search(r"\b(?i:under)\s+(" + OFFICER_RX + r"\s+[A-Z][^,;()]*?|[A-Z][^,;()]*?,\s*(?:Master|Second Master|Mate))(?=\s*(?:\(|\{|\[|,|;|$|\bfor\b|\bin\b|\bon\b|\bas\b|\bat\b|\bthen\b|\bto\b|\band\s+\??\s*\d|\d))",
                  span)
    if not m:   # O11（試し）："In 6.1814 Cmdr Archibald Tisdal!"（under がない）
        m = re.search(r"(?:^|(?<=[\s,;(]))(?i:on|in|from|then|and)\s+\??\s*(?:\d{1,2}\.){0,2}\d{4}\s+(" + OFFICER_RX + r"\s+[A-Z][^,;()]*?)(?=\s*(?:\(|,|;|$|\bfor\b|\band\s+\??\s*\d|\d))", span)
    if not m:
        m = re.search(r"\bby\s+(" + OFFICER_RX + r"\s+[A-Z][^,;()]*?)(?=\s*(?:\(|,|;|$|\d))", span)
    if m:
        rules.add("O10")
        return m.group(1).strip()
    return ""


# 調査（survey_narrative_v1.py）の役割の拾い方で漏れた言い回し（B4 の補い、2026-10-07）
ROLE_FALLBACK = [
    (r"\bas\s+(?:an?\s+)?\d+-gun\s+(flagship|troopship)\b", None),   # 砲数つき（"80-gun flagship"）
    (r"\bas\s+(?:an?\s+)?screw\s+mortar\s+frigate\b", "screw mortar frigate"),
    (r"\bas\s+(?:an?\s+)?gunboat\b", "gunboat"),
    (r"\bas\s+(?:an?\s+)?sloop\b", "sloop"),
    (r"\bas\s+(?:an?\s+)?victualler\b", "victualler"),
    (r"\bas\s+oil\s+jetty\b", "oil jetty"),
    (r"\bas\s+'lump'", "lump"),
    (r"\bbecame\s+coal\s+pontoon\b", "coal pontoon"),
    (r"\bbecame\s+pontoon\b", "pontoon"),
    (r"\bbecame\s+YC\.?\s?\d+", "yard craft"),
    (r"\bbecame\s+coastguard\s+CGWV\b", "coastguard watch vessel"),
    (r"^hulked\b", "hulk"),                                          # 役割の言葉のない "Hulked D"
    # 2026-10-09：沿岸警備・郵便船は配属先ではなく役割（ユーザー判断）。"as" のない形も役割として拾う（判断表で seagoing）
    (r"\bfor\s+(?:the\s+)?coast\s?guard\b", "coastguard ship"),
    (r"\bfor\s+(?:the\s+)?(?:[A-Z]\w+\s+)?(?:mail\s+)?packet\s+service\b", "packet"),
    (r"\bfitted\s+for\s+quarantine\s+service\b", "quarantine service"),   # 2026-10-14（試しの判定 SF5_9041）
]


def find_role(span):
    for role, ctx, end in SURVEY.role_mentions(span):
        return role
    for rx, role in ROLE_FALLBACK:
        m = re.search(rx, span.strip(), re.I)
        if m:
            return role or m.group(1).lower()
    return ""


# 2周目（2026-10-07、裁定 §11.6・ユーザー承認）：動詞のない役割の文（EV32）。どのトリガーにも当たらなかった節だけを見る
#   R1 役割の名詞で始まる（"Receiving ship there 1834-50"、"Powder hulk at Portsmouth 1856"）
#   R2 動詞のない as <役割>（"at Portsmouth 6.1883, as tender to Asia"、"Used as a tug there from 2.1850"）
#   R3 時の句の後に役割（"from 6.1860 tender to ..."、"later tender to Tortoise"、"in 7.1795 flagship of ..."）
#   他の艦を相手にする動詞（took・captured など）のある節は除く（型 D は規則の外。LLM の領分の候補）
VERBLESS_EXCLUDE = re.compile(r"\b(?:took|captured|destroyed|burnt|burned|sank|chased|engaged|attacked|cut\s+out|boats|"
                              r"earmarked|intended|planned|proposed)\b|\d\s*pdrs?\b", re.I)   # 予定・砲の装備の行も除く


def _role_names():
    if not os.path.exists(ROLE_JUDGEMENT):
        return []
    names = {r["role"] for r in csv.DictReader(open(ROLE_JUDGEMENT, encoding="utf-8-sig"))}
    names -= {"ship", "schooner", "sloop"}
    return sorted(names, key=len, reverse=True)


VERBLESS_ROLES = []


def verbless_role(clause):
    """戻り値 (役割, 規則ID) または None"""
    if not VERBLESS_ROLES:
        VERBLESS_ROLES.extend(_role_names())
    if VERBLESS_EXCLUDE.search(clause):
        return None
    names = "|".join(re.escape(n) for n in VERBLESS_ROLES)
    m = re.match(r"\s*(?:a\s+|an\s+|the\s+)?(" + names + r")s?\b", clause, re.I)
    if m:
        return m.group(1).lower(), "R1"
    m = re.search(r"\bas\s+(?:a\s+|an\s+|the\s+)?(?:temporary\s+)?(" + names + r")s?\b", clause, re.I)
    if m:
        return m.group(1).lower(), "R2"
    m = re.match(r"\s*(?:from|in|later|then|by)\b[^,;]{0,25}?\b(?:was\s+)?(" + names + r")s?\b", clause, re.I)
    if m:
        return m.group(1).lower(), "R3"
    return None


def year_range(span):
    """"1834-50"・"1875- 90"・"1866-1890" を (始まりの年, 終わりの年) に"""
    m = re.search(r"\b(1[6-9]\d\d)\s*[-–]+\s*(\d{4}|\d{2})\b(?![.\d])", span)
    if not m:
        return None
    y1, y2 = m.group(1), m.group(2)
    if len(y2) == 2:
        y2 = y1[:2] + y2
    return (y1, y2) if y2 > y1 else None


def load_role_judgements():
    if not os.path.exists(ROLE_JUDGEMENT):
        return {}
    out = {}
    for r in csv.DictReader(open(ROLE_JUDGEMENT, encoding="utf-8-sig")):
        j = (r.get("judgement (seagoing / harbour / either / not_a_role)") or "").strip().lower()
        if j:
            out[r["role"]] = j
    return out


def classify(rid, span, ctx, rules, ship_head):
    """出来事の型・CIDOC のクラス・状態への影響・相手。戻り値 dict"""
    low = span.lower()
    d = {"type": "", "cidoc": "", "effect": "", "counterparty": "", "new_name": "", "note": "", "status": "parsed"}
    if rid == "EV01":
        d.update(type=":Commissioning", cidoc="E7", effect="service:InCommission")
    elif rid == "EV02":
        d.update(type=":Recommissioning", cidoc="E7", effect="service:InCommission")
    elif rid == "EV03":
        d.update(type=":CommandAppointment", cidoc="E7", effect="none")
    elif rid == "EV04":
        d.update(type=":Decommissioning", cidoc="E7", effect="service:PaidOff")
        outside = re.sub(r"\([^)]*\)?", "", span)   # 括弧の中の説明（"(replaced as gunnery ship by ...)"）は除く
        if re.search(r"\bas\s+", outside, re.I) and find_role(outside):
            d.update(effect="service:PaidOff;pending_B4")
    elif rid == "EV05":
        d.update(type=":Decommissioning", cidoc="E7", effect="service:InOrdinary",
                 note="paid off into Ordinary / Steam Reserve (no paid-off interval; decision B1 of 10/1)")
    elif rid == "EV06":
        d.update(type="(status)", cidoc="", effect="service:InOrdinary")
        m = re.search(r"\b((?:steam|dockyard)\s+reserve|in\s+reserve)\b", low)
        if m:
            d["note"] = "term in the source: " + m.group(1) + " (treated as In Ordinary; decision B6)"
    elif rid == "EV07":
        d.update(type=":FittingForSea", cidoc="E11", effect="work:UnderFitting")
    elif rid == "EV08":
        d.update(type=":FittingForOrdinary", cidoc="E11", effect="work:UnderFitting")
    elif rid == "EV09":
        d.update(type=":Fitting", cidoc="E11", effect="work:UnderFitting;pending_B4")
    elif rid == "EV10":
        if re.search(r"\bfitted\s+with\b", low):
            d.update(type=":Fitting", cidoc="E11", effect="none", note="'fitted with': technical modification")
        elif re.search(r"\brefit", low):
            d.update(type=":Refit", cidoc="E11", effect="work:UnderRepair")
        else:
            d.update(type=":Fitting", cidoc="E11", effect="work:UnderFitting")
    elif rid == "EV11":
        m = re.search(r"(?:between\s+((?:very\s+)?(?:m\s?iddling|\w+))\s+and\s+)?((?:very\s+)?(small|middling|large|great))\s+repair", low)
        kind = {"small": ":SmallRepair", "middling": ":MiddlingRepair", "large": ":LargeRepair", "great": ":GreatRepair"}[m.group(3)]
        note = ""
        if m.group(1) or "very" in m.group(2):
            note = f"source: '{m.group(0)}'"
        d.update(type=kind, cidoc="E11", effect="work:UnderRepair", note=note)
    elif rid == "EV12":
        d.update(type="sealit:ShipRepair", cidoc="E11", effect="work:UnderRepair")
        if re.search(r"\bre-?(?:engined|boilered)\b", low):
            d["note"] = "re-engined / reboilered: machinery replacement at a dockyard, treated as repair (review of 10/7)"
    elif rid == "EV13":
        d.update(type=":ScrewConversion" if "screw" in low else ":ShipConversion", cidoc="E11", effect="none")
    elif rid == "EV14":
        m = re.search(r"\b(?i:(?:re)?sold)\s+(?:at\s+[A-Z]\w+\s+)?to\s+(?!BU\b)([A-Z][^(;,]*?)(?=\s+(?:\d|\(|for\b|to\b|and\b|at\b)|[,;(]|$)", span)
        if not m:   # 日付の後に買い手（"Sold 30.9.1885 to Castle to BU"）
            m = re.search(r"\b(?i:(?:re)?sold)\s+(?:at\s+[A-Z]\w+\s+)?[\d.?]+\s+(?:at\s+[A-Z]\w+\s+)?to\s+(?!BU\b)"
                          r"([A-Z][^(;,]*?)(?=\s+(?:\d|\(|for\b|to\b|and\b|at\b)|[,;(.]|$)", span)
        if not m:   # 一般形：sold の後、"towed" "later" より前にある最初の "to <大文字>"
            after = re.split(r"\b(?:towed|later|resold)\b", re.split(r"\b(?i:sold)\b", span, maxsplit=1)[-1])[0]
            m = re.search(r"\bto\s+(?!BU\b|be\b|serve\b)((?:Mr\.?\s+)?[A-Z][^(;,]*?)(?=\s+(?:\d|\(|for\b|to\b|and\b|at\b|by\b)|[,;(]|\.\s|\.$|$)",
                          after)
        brk = bool(re.search(r"\b(?:to|for|and)\s+B\s?U\b|\bto\s+be\s+broken\s+up", span))
        d.update(type="E96_Purchase (sale)", cidoc="E96", effect="end", counterparty=m.group(1).strip() if m else "",
                 note="sold to be broken up (BU after the sale is outside the Navy; decision D1)" if brk else "")
        if "wreck" in low:
            d.update(note="sale of the wreck", effect="none")
    elif rid == "EV15":
        d.update(type="E6_Destruction (breaking up)", cidoc="E6", effect="service:BeingBrokenUp")
        if "completed" in low:
            d["note"] = "completion of breaking up"
    elif rid == "EV16":
        if re.search(r"loan\s+terminated|returned\s+to", low):
            d.update(type="E10 (end of loan)", cidoc="E10", effect="service:end_InOtherCustody")
        else:
            m = re.search(r"\b(?i:lent)\b(?:\s+as\s+[^,;]*?)?\s+to\s+(?:the\s+)?([A-Z][^(;,]*?)(?=\s+(?:\d|\(|as\b|by\b|for\b|at\b|in\b)|[,;(]|$)", span)
            d.update(type="E10 :Loan", cidoc="E10", effect="service:InOtherCustody", counterparty=m.group(1).strip() if m else "")
    elif rid in ("EV17", "EV18"):
        if re.search(r"\b(?:he|she)\s+transferred\b|\bwhen\s+(?:he|she)\b|^transferred\s+to\s+the\s+new\b", low.strip()):
            d.update(type="(person transferred; not an event of the ship)", status="skip")
        elif re.search(r"\bt\s?o\s+(?:the\s+)?(?:coastguard|coast\s+guard)", low):
            d.update(type="E10 :Transfer", cidoc="E10", effect="service:InOtherCustody", counterparty="Coastguard")
        elif re.search(r"\bto\s+(?:the\s+)?(?:colonial\s+)?government\b|\bto\s+[A-Z][\w ]*government\b", span, re.I):
            m = re.search(r"\bto\s+((?:the\s+)?[A-Z][^,;(]*?government[^,;(]*?)(?=\s+\d|[,;(]|$)", span, re.I)
            d.update(type="E8_Acquisition (title to another government)", cidoc="E8", effect="end",
                     counterparty=m.group(1).strip() if m else "")
        elif re.search(r"\bex-PO\b|\bPost Office\b|\bthe PO\b", ship_head):
            d.update(type="E10 :Transfer (from the Post Office to the Navy)", cidoc="E10", effect="start",
                     counterparty="Post Office → Admiralty")
        elif re.search(r"^(?i:transferred)\s+at\s+[A-Z][\w ]*?\s*$", span.strip()) and re.search(r"\bto\s+(?:the\s+)?coast\s?guard", ctx, re.I):
            d.update(type="(fragment of the following transfer to the coastguard)", status="skip")
        elif re.search(r"\bnamed\b", low):
            d.update(type="E10 :Transfer (handover)", cidoc="E10", effect="none",
                     note="physical handover after a gift or sale recorded elsewhere")
        else:
            d.update(type="E10 :Transfer", cidoc="E10", effect="service:InOtherCustody", status="needs_review",
                     note="recipient not recognised")
    elif rid == "EV19":
        m = re.search(r"\b(?i:(?:re-?)?named)\s+(?:as\s+)?(?:[a-z][\w ]*?\s+)?([A-Z]{1,3}\.?\s?\d+|[A-Z][\w.'’ ]*?)(?=\s+(?:on\s+|in\s+|at\s+|\(|\d)|[,;]|\s*$)", span)
        if re.match(r"\s*named\s+(?:\d|on\b|in\b)", low[low.find("named"):] if "named" in low else ""):
            d.update(type="E15 (naming)", cidoc="E15", effect="none", note="naming stated in the source")
        else:
            d.update(type="E15 (renaming)", cidoc="E15", effect="none", new_name=m.group(1).strip() if m else "")
            if not m:
                d["status"] = "needs_review"
    elif rid == "EV20":
        d.update(type="E13 :changes_ship_rating", cidoc="E13", effect="none",
                 note="cut down: also a structural modification" if "cut down" in low else "")
    elif rid == "EV32":
        d.update(type="(role)", cidoc="", effect="pending_B4")
    elif rid == "EV21":
        d.update(type="(role)", cidoc="", effect="pending_B4")
    elif rid == "EV22":
        d.update(type="E6_Destruction (loss)", cidoc="E6", effect="end")
    elif rid == "EV23":
        if re.search(r"\bpurchased\b|\bregistered\b", low):
            d.update(type="E8_Acquisition (capture, then purchase)", cidoc="E8", effect="start")
        else:
            d.update(type="E8_Acquisition (taken)", cidoc="E8", effect="", status="needs_review",
                     note="taken by or from whom is not determined by the rules")
    elif rid == "EV24":
        if re.search(r"\bpurchased\s+by\s+(?:the\s+)?(?:US|U\.S\.|United\s+States|American|French|Spanish|Dutch|[A-Z]\w+)\s+government\b", span, re.I) \
                and not re.search(r"\bBritish\s+government\b", span, re.I):
            d.update(type="(note: purchased by another government)", cidoc="", effect="none",
                     note="purchased by another government, not an acquisition by this navy (A2)")
            rules.add("A2")
        else:
            d.update(type="E96_Purchase (acquisition)", cidoc="E96", effect="start")
    elif rid == "EV31":
        m = re.search(r"\b(?i:presented|given)\s+to\s+(?:the\s+)?([A-Z][^,;(]*?)(?=\s+\d|[,;(]|$|\s+in\b)", span)
        cp = m.group(1).strip() if m else ""
        # 2026-10-14（試しの判定 SM_9036）："presented to Queen Victoria by President Buchanan" の "by ..." は贈り手。受け手と分ける
        cp, _, giver = cp.partition(" by ")
        cp, giver = cp.strip(), giver.strip()
        if re.match(r"(?:Queen|King|the\s+Queen|the\s+King|(?:the\s+)?Admiralty|(?:the\s+)?Royal\s+Navy|(?:the\s+)?British\s+government)\b", cp, re.I):
            # 受け手は英国（海軍、P22）。相手（P23）は贈り手で、書かれていなければ付けない
            d.update(type="E8_Acquisition (gift to the Crown)", cidoc="E8", effect="start", counterparty=giver,
                     note="presented to the British Crown or Navy: the (re)start of the naval career (G2)")
            rules.add("G2")
        else:
            d.update(type="E8_Acquisition (gift)", cidoc="E8", effect="end", counterparty=cp)
    elif rid == "EV27":
        d.update(type="(note: never commissioned)", cidoc="", effect="none")
    elif rid == "EV28":
        if "stored" in low:
            d.update(type="(status: stored ashore)", cidoc="", effect="service:InOrdinary",
                     note="stored ashore in a gunboat shed (treated as In Ordinary; decision B7)")
        else:
            d.update(type="(note: housed over)", cidoc="", effect="none")
    return d


def main():
    os.makedirs(OUT, exist_ok=True)
    judgements = load_role_judgements()
    ships = []
    for f in sorted(glob.glob(os.path.join(SRC, "*.xlsx"))):
        rows = list(openpyxl.load_workbook(f, read_only=True).worksheets[0].iter_rows(values_only=True))
        for r in rows[1:]:
            d = dict(zip(rows[0], r))
            text = str(d["text"] or "")
            ships.append((f"{d['Prefix']}_{int(d['serial_no']):04d}", text.split("\n")[0], text))

    events, review, cover = [], [], []
    for sid, head, text in ships:
        last_place, n = "", 0
        prev = None
        prev_stations = []   # ST4（on same station）で補う相手
        for ci, clause in enumerate(SURVEY.clauses(text), 1):
            base_rules = set()
            c = norm_text(clause, base_rules)
            hits = []
            for rid, rx in TRIG:
                for m in rx.finditer(c):
                    if any(m.start() < h[2] and h[1] < m.end() for h in hits):
                        continue   # 優先度の高いトリガーと重なる
                    hits.append((rid, m.start(), m.end()))
            hits.sort(key=lambda h: h[1])
            # EV15'：売却の後の BU、"to/for BU"、括弧の中の "to BU" は海軍の解体ではない（売却の注記。決定D1）
            kept = []
            for h in hits:
                if h[0] == "EV15":
                    before = c[:h[1]]
                    if (any(k[0] == "EV14" for k in kept) or re.search(r"(?:\bto|\bfor)\s*$", before, re.I)
                            or before.count("(") > before.count(")")):
                        base_rules.add("EV15'")
                        continue
                if h[0] in WORK_RULES and c[:h[1]].count("(") > c[:h[1]].count(")"):
                    base_rules.add("S13")   # 2周目：括弧の中の工事の言い回し（"Middling Repair (later Large Repair)"）は新しい出来事にしない（裁定 #14）
                    continue
                if h[0] == "EV22":
                    # L1：他の艦の喪失（"prize sunk"、"nine Turkish vessels sunk"、"burnt the cutter ..."）は艦の出来事ではない
                    before, after = c[max(0, h[1] - 30):h[1]], c[h[2]:h[2] + 12]
                    before60 = c[max(0, h[1] - 60):h[1]]
                    if (re.search(r"\b(?:prize|prizes|vessels|ships|privateers?)\s*$", before, re.I)
                            or re.match(r"\s+(?:the|a|an)\s", after, re.I)
                            or re.search(r"(?:\bwith\s+|\b\d+-gun\s+)[A-Z][^,;()]*$", before60)):   # L1 の拡張（試し）
                        base_rules.add("L1")
                        continue
                    # L2：同じ節の喪失の言い回しの続き（"lost, presumed foundered"、"exploded and sank"）は1つの出来事に
                    if kept and kept[-1][0] == "EV22":
                        base_rules.add("L2")
                        continue
                kept.append(h)
            hits = kept
            if not hits:
                vr = verbless_role(c)
                if not vr:
                    continue
                hits = [("EV32", 0, len(c))]
                base_rules.add(vr[1])
            spans = []
            for i, (rid, s, e) in enumerate(hits):
                end = hits[i + 1][1] if i + 1 < len(hits) else len(c)
                spans.append([rid, c[s:end], s])
            merged = []
            for sp in spans:   # S11：日付のない工事 + and + 次の工事 → 1つの出来事に
                if (merged and merged[-1][0] in WORK_RULES and sp[0] in WORK_RULES and not DATE_TOKEN.search(merged[-1][1])
                        and re.search(r"(?:\band|,)\s*$", merged[-1][1].strip() + " ")):
                    merged[-1] = [merged[-1][0] + "+" + sp[0], merged[-1][1] + sp[1], merged[-1][2]]
                    continue
                merged.append(sp)
            for i, sp in enumerate(merged):   # S12：日付のない範囲が and で日付のある次の範囲につながる
                if (i + 1 < len(merged) and not DATE_TOKEN.search(sp[1]) and DATE_TOKEN.search(merged[i + 1][1])
                        and re.search(r"\band\s*$", sp[1].strip())):
                    sp.append(merged[i + 1][1])
            clause_last_dt = None
            for item in merged:
                rid_s, span, pos = item[0], item[1], item[2]
                shared = item[3] if len(item) > 3 else None
                rules = set(base_rules) | {"S10"}
                rids = rid_s.split("+")
                if len(rids) > 1:
                    rules.add("S11")
                infos = [classify(r, span, c, rules, head) for r in rids]
                if all(x["status"] == "skip" for x in infos):
                    continue
                order_date = order_prec = ""
                ao = re.search(r"\(?\s*\b(?:by|under)\s+AO\s+(?:of\s+)?((?:\d{1,2}\.){0,2}\d{4})\s*\)?", span)
                if ao and not ("EV15" in rids or "EV14" in rids):   # 2周目：売却（EV14）にも（裁定 #29）
                    # 3周目：工事（艤装・修理・改装）と等級の変更（EV20）は、AO の他に日付（工事の期間）があるときだけ
                    # AO を命令の日付にする（SCGVG_0004 "Reengined (by AO of 3.1.1849) 1-6.1849"）。
                    # AO の日付しかなければ、これまでどおり AO の日付を出来事の日付に使う（SL3_0072 など）
                    rest = span[:ao.start()] + span[ao.end():]
                    if not (set(rids) & (WORK_RULES | {"EV20"}) and DATE_TOKEN.search(rest)):
                        ao = None
                if ao:   # U1：解体の命令（AO）の日付は解体の日付にしない。命令の出来事として別に記録（決定 2026-10-07）
                    od = find_date(ao.group(1), rules)
                    if od:
                        order_date, order_prec = od[0], od[2]
                        rules.add("U1")
                dspan = span[:ao.start()] + span[ao.end():] if ao else span
                if "EV14" in rids:   # 2周目：売却の文の "and BU D" は買い手による解体の日付で、売却の日付ではない
                    cut = re.search(r"\band\s+(?:was\s+)?BU\b", dspan)
                    if cut and re.search(r"\bto\s+[a-z]+\s*$", dspan[:cut.start()]):   # 小文字の動詞のみ（"to Castle" は相手）
                        cut = None   # "to salve and BU" は売却の目的なので切らない
                    if cut:
                        dspan = dspan[:cut.start()]
                dt = find_date(dspan, rules)
                if not dt and shared:
                    dt = find_date(shared, rules)
                    if dt:
                        rules.add("S12")
                yr = year_range(span)   # 2周目：すべての出来事に（"Repair and refit there 1852-53"、"In Ordinary at Chatham 1817-20"）
                if yr and (not dt or (dt[2] == "year" and dt[0] == yr[0])):   # "Receiving ship there 1834-50" は期間
                    y1, y2 = yr
                    dt = (y1, y2, "year", "year", dt[4] if dt else False, "period")
                    rules.add("R4")
                # S14（2周目、2026-10-07 ユーザー承認）：日付が言い回しの前にある形
                #   S14a 節の最初の出来事で、最初のトリガーより前に日付だけがある（"in 1876 to the coastguard"、"28.8.1861, renamed"）
                #   S14b 直前の言い回しと and・into・"," でつながる（"paid off 6.8.1856 at Sheerness into Steam Reserve"）
                if not dt and pos == merged[0][2] and pos > 0 and DATE_TOKEN.search(c[:pos]):
                    dt = find_date(c[:pos], rules)
                    if dt:
                        rules.add("S14a")
                if (not dt and clause_last_dt and pos > 0 and set(rids) <= {"EV05", "EV06", "EV28"}
                        and re.search(r"(?:\band|\binto|,)\s*$", c[:pos])):   # 地位の印だけ（"Taken D and purchased" は別の手続き）
                    dt = clause_last_dt
                    rules.add("S14b")
                if dt and "EV15" in rids and re.search(r"\bcompleted\b", span, re.I) and dt[5] == "point":
                    dt = ("", dt[1], "", dt[3], dt[4], "to")   # U2："BU completed D" は終わりだけ。始まりは原文にない
                    rules.add("U2")
                place = find_place(span, last_place, rules)
                if place:
                    last_place = place
                amount, amount_note = find_amount(span, rules)
                officer = find_officer(span, rules) if any(r in ("EV01", "EV02", "EV03") for r in rids) else ""
                found = (find_stations(span, officer, prev_stations, find_date, rules)
                         if any(r in ("EV01", "EV02", "EV03") for r in rids) else [])
                if found:
                    prev_stations = found   # ST3 の役割の印も、次の same station の補いの相手として残す
                stations = [x for x in found if not x.get("role")]
                if not place and any(r in ("EV01", "EV02") for r in rids):   # P16
                    port = next((x["proposed"].split(": ", 1)[1] for x in found
                                 if x.get("role") and x["rule"] == "ST3" and ": " in x["proposed"]), "")
                    if port and port in span:   # "on same station" で前の役割を引き継いだ港は、原文のこの文にないので入れない
                        place = last_place = port
                        rules.add("P16")
                if any(x.get("all") for x in stations):   # ST7：同じ節の前の出来事で配属先のないものに写す
                    for x in events:
                        if (x["ship"] == sid and x["clause_no"] == ci and not x["stations"]
                                and set(x["rules_trigger"].split("+")) & {"EV01", "EV02", "EV03"}):
                            x["stations"] = json.dumps([dict(y, rule="ST7") for y in stations], ensure_ascii=False)
                            x["rules"] = " ".join(sorted(set(x["rules"].split()) | {"ST7"}))
                    rules.add("ST7")
                role = (verbless_role(span) or ("",))[0] if "EV32" in rids else find_role(re.sub(r"\([^)]*\)?", "", span) if "EV04" in rids else span) if any(r in ("EV04", "EV09", "EV16", "EV21", "EV01", "EV02") for r in rids) else ""
                effect = ";".join(x["effect"] for x in infos if x["effect"])
                if "service:InOtherCustody" in effect and any(
                        x["ship"] == sid and "end" in x["status_effect"].split(";") for x in events):
                    # キャリアの終わり（贈与・売却・喪失）の後の移管：引き渡しか、海軍の外での出来事（2026-10-07）
                    effect = effect.replace("service:InOtherCustody", "none")
                    for x in infos:
                        if x["note"] == "recipient not recognised":
                            x["note"], x["status"] = "", "parsed"
                    infos[0]["note"] = (infos[0]["note"] + "; " if infos[0]["note"] else "") + \
                        "after the end of the RN career (handover after a gift or sale, or a later event outside the RN)"
                if role and role in judgements and "pending_B4" in effect:
                    j = judgements[role]
                    effect = effect.replace("pending_B4", {"seagoing": "role_seagoing", "harbour": "service:InNonCombatDuty",
                                                           "either": "role_either_review", "not_a_role": ""}.get(j, "pending_B4"))
                    rules.add("B4")
                    effect = effect.strip(";")
                status = "parsed"
                notes = [x["note"] for x in infos if x["note"]]
                if "pending_B4" in effect and not role:
                    effect = effect.replace(";pending_B4", "").replace("pending_B4", "")
                    status = "needs_review"
                    notes.append("B4: no role could be read from the span (not_a_role)")
                if "T13" in rules:
                    status = "needs_review"
                    notes.append("alternative dates in the source ('X or Y'); the later one was read")
                if any(x["status"] == "needs_review" for x in infos):
                    status = "needs_review"
                date_needed = any(r not in ("EV27", "EV28", "EV21", "EV06") for r in rids)
                if not dt and order_date:
                    notes.append("only the date of the Admiralty Order is given")
                elif not dt and date_needed:
                    status = "needs_review" if status == "parsed" else status
                    notes.append("no date in the span (may be given elsewhere in the clause or omitted)")
                if amount_note:
                    notes.append(amount_note.strip("; "))
                b, e, bp, ep, unc, drole = dt if dt else ("", "", "", "", False, "")
                n += 1
                typ = " + ".join(x["type"] for x in infos)
                key = (b or e or (prev or {}).get("begin", "")).replace("-", "")   # 終わりだけの出来事は終わりの日付（2026-10-07）
                datepart = (key + "0000")[:8] if key else "00000000"
                ev = {"ship": sid, "event_no": n, "clause_no": ci, "rules_trigger": rid_s, "type": typ,
                      "cidoc": "+".join(x["cidoc"] for x in infos if x["cidoc"]), "begin": b, "end": e,
                      "begin_precision": bp, "end_precision": ep, "date_role": drole, "uncertain": unc, "place": place,
                      "officer_text": officer, "role_text": role,
                      "counterparty": "; ".join(x["counterparty"] for x in infos if x["counterparty"]),
                      "stations": json.dumps(stations, ensure_ascii=False) if stations else "",
                      "amount_gbp": amount, "order_date": order_date, "order_precision": order_prec, "new_name": "; ".join(x["new_name"] for x in infos if x["new_name"]),
                      "status_effect": effect, "rules": " ".join(sorted(rules)), "status": status,
                      "note": "; ".join(notes), "raw": span.strip(), "_datepart": datepart, "_dated": bool(b or e)}
                events.append(ev)
                if dt:
                    clause_last_dt = dt
                if b:
                    prev = ev
                if status != "parsed":
                    review.append(ev)

    # ID（案c）：<艦>_<日付8桁>_<種類>。日付なしは直前の日付つきの出来事の日付＋_u<n>。同じ ID には枝番
    def slug(ev):
        t, rid = ev["type"].split(" + ")[0], ev["rules_trigger"].split("+")[0]
        named = {":Commissioning": "commissioning", ":Recommissioning": "recommissioning",
                 ":CommandAppointment": "command_appointment", ":Decommissioning": "decommissioning",
                 ":FittingForSea": "fitting_for_sea", ":FittingForOrdinary": "fitting_for_ordinary", ":Fitting": "fitting",
                 ":Refit": "refit", ":SmallRepair": "small_repair", ":MiddlingRepair": "middling_repair",
                 ":LargeRepair": "large_repair", ":GreatRepair": "great_repair", "sealit:ShipRepair": "repair",
                 ":ScrewConversion": "screw_conversion", ":ShipConversion": "conversion",
                 "E96_Purchase (sale)": "sale", "E6_Destruction (breaking up)": "breaking_up", "E10 :Loan": "loan",
                 "E10 (end of loan)": "loan_end", "E15 (renaming)": "renaming", "E15 (naming)": "naming",
                 "E13 :changes_ship_rating": "rerating", "(role)": "role", "E6_Destruction (loss)": "loss",
                 "E96_Purchase (acquisition)": "purchase", "E8_Acquisition (gift)": "gift", "(status)": "laid_up",
                 "(note: never commissioned)": "note_never_commissioned", "(note: housed over)": "note_stored", "(status: stored ashore)": "note_stored"}
        if t in named:
            return named[t]
        if t.startswith("E10 :Transfer"):
            return "transfer"
        if t.startswith("E8_Acquisition (title"):
            return "title_transfer"
        if t.startswith("E8_Acquisition"):
            return "acquisition"
        return "event_" + rid.lower()
    seen, ucount = collections.Counter(), collections.Counter()
    for ev in events:
        base = f"{ev['ship']}_{ev['_datepart']}_{slug(ev)}"
        if not ev["_dated"]:
            ucount[f"{ev['ship']}_{ev['_datepart']}"] += 1
            base += f"_u{ucount[ev['ship'] + '_' + ev['_datepart']]}"
        seen[base] += 1
        ev["id"] = base if seen[base] == 1 else f"{base}_{seen[base]}"

    # 対応表の言い回しに当たるのに出来事を作れなかった節（調査の辞書との突き合わせ）
    made = {(ev["ship"], ev["clause_no"]) for ev in events}
    scope = {"EV01", "EV02", "EV03", "EV04", "EV05", "EV07", "EV08", "EV10", "EV11", "EV12", "EV13", "EV14", "EV15",
             "EV16", "EV17", "EV18", "EV19", "EV20", "EV22", "EV24", "EV31"}
    for r in csv.DictReader(open(P.out("rules_v1_survey/clauses.csv"), encoding="utf-8-sig")):
        cats = set(r["categories"].split()) & scope
        if cats and (r["ship"], int(r["clause_no"])) not in made:
            cover.append([r["ship"], r["clause_no"], " ".join(sorted(cats)), r["clause"]])

    cols = ["id", "ship", "event_no", "clause_no", "rules_trigger", "type", "cidoc", "begin", "end", "begin_precision",
            "end_precision", "date_role", "uncertain", "place", "officer_text", "role_text", "stations", "counterparty", "amount_gbp",
            "new_name", "order_date", "order_precision", "status_effect", "rules", "status", "note", "raw"]
    for name, rows_ in (("events.csv", events), ("events_review.csv", review)):
        with open(os.path.join(OUT, name), "w", newline="", encoding="utf-8-sig") as fh:
            w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
            w.writeheader()
            w.writerows(rows_)
    with open(os.path.join(OUT, "coverage.csv"), "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(["ship", "clause_no", "survey_categories", "clause"])
        w.writerows(cover)
    summary = {
        "ships": len(ships), "events": len(events), "ships_with_events": len({e["ship"] for e in events}),
        "by_trigger": dict(collections.Counter(e["rules_trigger"] for e in events).most_common()),
        "by_status": dict(collections.Counter(e["status"] for e in events)),
        "dated": sum(1 for e in events if e["begin"] or e["end"]),
        "pending": dict(collections.Counter(p for e in events for p in re.findall(r"pending_\w+", e["status_effect"]))),
        "clauses_in_scope_without_event": len(cover),
        "duplicate_ids_resolved": sum(1 for v in seen.values() if v > 1),
        "role_judgements_loaded": len(judgements),
    }
    with open(os.path.join(OUT, "summary.json"), "w", encoding="utf-8") as fh:
        json.dump(summary, fh, ensure_ascii=False, indent=2)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
