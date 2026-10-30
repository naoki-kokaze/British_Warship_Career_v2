"""配属先（ステーション・海域）を、就役・再就役・艦長任命の範囲から規則で取り出す（2026-10-09、ユーザー決定）

extract_events_v1.py から呼ぶ（EV01・EV02・EV03 の範囲だけ）。出来事の列 events.csv の stations 列（JSON）になり、
convert_events_v2.py が :StationDeployment のノードにする。

決定（2026-10-09、ログ 10/9）
    1. 配属先は就役（再就役・艦長任命）の出来事に付ける。就役した港（crm:P7、規則 P10）とは別のノード
    2. "on same station" は直前の配属先で補い、推測の印（review note）を付ける
    3. RDF には原文どおりの表記を入れる。歴史的なステーションへのまとめは別の対応表（station_labels.csv の
       proposed_station 列。ユーザーの確認待ち）で、院生の判定の対象外
    4. 海域・ステーションだけを配属先にする。目的（Naval Review、Spanish Armament、surveying などの言葉だけ）、
       航海の行き先（voyage / passage to ...）、艦隊名だけのもの（Flying Squadron など）は配属先にしない
    5. 配属先は欠落を問う対象（指示書 §4）

規則
    ST1 地名の一覧（GAZETTEER）にある海域・ステーションを、手がかりの語（for / in / on / to / off / at / still /
        then / later、および "X and Y" の Y）の後で取る。一覧にない "<地名> station" も取る（ST2）
    ST2 一覧にない "<大文字の語> station"（"Dover station"、"Leith station"）
    ST3 沿岸警備・郵便船（"for the coastguard at Greenock"、"as a coastguard ship on the Humber"、"for the mail packet
        service at Falmouth"、"as a Falmouth packet"）は配属先にしない（役割。2026-10-09 ユーザー判断）。役割の印として
        返し（role=True）、呼び出し側は RDF に入れず、次の "on same station" の補いの相手にだけ使う
    ST4 "on (the) same station" / "for (the) same station" → 直前の配属先（推測。review note）。直前が ST3 の役割の印なら
        補わない（沿岸警備の配置を海域で補わない）
    ST5 順序：then / later / subsequently / finally の後の配属先は次の段（seq + 1）。"X and Y" は同じ段
    ST7 "..., then D under X, all in the Mediterranean" の all は、同じ節で前に並ぶ艦長任命・就役にもかかる（原文が明示）
    ST6 配属先の直後（または "then 1852 to" の直前）の日付は、その配属先の日付
    除外 voyage / passage / transport / convey / relief / cable-laying / home の後の地名、"from the X"（行き先・出発地）、
        括弧の中の died / invalided / appointed などの説明
"""
import re

# 長いものを先に（"North America and the West Indies" を "North America" と "West Indies" に割らない）
# (正規表現, まとめの案, 種類)。まとめの案は station_labels.csv の proposed_station になる（RDF には入れない）
GAZETTEER = [
    (r"North[\s-]+America(?:n)?\s+(?:and|&)\s+(?:the\s+)?West\s+Indies(?:\s+[Ss]tations?)?", "North America and West Indies", "sea"),
    (r"East\s+Indies\s+(?:and|&)\s+China(?:\s+[Ss]tations?)?", "East Indies and China", "sea"),
    (r"(?:(?:the\s+)?(?:[Ss]outh[\s-]*e+ast|[Ee]ast|southeeast)\s+coast\s+(?:of\s+)?)?South\s+America(?:n)?(?:\s+[Ss]tations?)?",
     "South-East Coast of America", "sea"),
    (r"southe+ast\s+America", "South-East Coast of America", "sea"),
    (r"(?:the\s+)?(?:[Ww]est\s+)?[Cc]oast\s+of\s+Africa|African\s+(?:coast|[Ss]tations?)", "West Africa", "sea"),
    (r"Cape\s+of\s+Good\s+Hope(?:\s+[Ss]tation)?|(?<=the\s)Cape\b", "Cape of Good Hope", "sea"),
    (r"North\s+America(?:n)?(?:\s+[Ss]tation)?", "North America", "sea"),
    (r"East\s+I\s?ndi(?:es|a)(?:\s+[Ss]tation)?", "East Indies", "sea"),
    (r"China(?:\s+[Ss]tation)?", "China", "sea"),
    (r"West\s+Indies", "West Indies", "sea"),
    (r"Jamaica(?:\s+[Ss]tation)?", "Jamaica", "sea"),
    (r"Leeward\s+Islands(?:\s+[Ss]tation)?", "Leeward Islands", "sea"),
    (r"Bahamas", "Bahamas", "sea"),
    (r"Hal\s?i?fax(?:\s+[Ss]tation)?", "Halifax", "sea"),
    (r"Newfoundland(?:\s+(?:[Ss]tation|service))?", "Newfoundland", "sea"),
    (r"Black(?:\s+and\s+Mediterranean)?\s+Seas?", "Black Sea", "sea"),
    (r"Med\s?iterranean(?:\s+(?:[Ss]tation|[Ss]eas?))?", "Mediterranean", "sea"),
    (r"Baltic", "Baltic", "sea"),
    (r"North\s+Sea(?:\s+(?:[Ss]tation|service))?", "North Sea", "sea"),
    (r"Scottish\s+waters", "Scottish waters", "sea"),   # 2026-10-14（試しの判定 PSPV_9003："for surveying North Sea and Scottish waters"）
    (r"(?<!Bristol\s)Channel\s+Islands", "Channel Islands", "sea"),
    (r"(?<!Bristol\s)Channel(?:\s+(?:[Ss]quadron|[Ff]leet|[Ss]tation|service))?", "Channel", "sea"),
    (r"Downs", "The Downs", "sea"),
    (r"Nore", "The Nore", "sea"),
    (r"Texel", "North Sea", "sea"),
    (r"Lisbon(?:\s+[Ss]tation)?|Tagus", "Lisbon", "sea"),
    (r"(?:(?:north\s+)?coast\s+of\s+Spain|Spanish\s+coast)", "Coast of Spain", "sea"),
    (r"(?:coast\s+of\s+Ireland|Irish\s+coast)|\bCork\b", "Ireland (Cork)", "sea"),
    (r"(?:North\s+)?Pacific", "Pacific", "sea"),
    (r"Australia(?:n\s+[Ss]tation)?(?:\s+and\s+New\s+Zealand)?|New\s+Zealand", "Australia", "sea"),
    (r"Toulon", "Mediterranean", "sea"),
    (r"Bay\s+of\s+Bengal", "East Indies", "sea"),
    (r"River\s+Plate|Brazil", "South-East Coast of America", "sea"),
    (r"Home\s+(?:[Ss]tation|waters)", "Home", "sea"),
]
GAZ = [(re.compile(rx), norm, kind) for rx, norm, kind in GAZETTEER]

CUE = re.compile(r"(?:\bfor|\bin|\bon|\bto|\boff|\bat|\bstill|\bthen|\blater|\band|&|\bsubsequently|\bfinally|,|\(|"
                 r"\bsurveying|\bsurvey\s+of)"
                 r"(?:\s+(?:the|same|end|\d{1,2}\.)?)*\s*$", re.I)
EXCLUDE_BEFORE = re.compile(r"\b(?:voyage|passage|transport|convey|relief|cable-laying|home|exploration|discovery)\b"
                            r"[^,;]*$|\bfrom\s+(?:the\s+)?$", re.I)
SEQ_WORD = re.compile(r"\b(?:then|later|subsequently|finally)\b", re.I)
PAREN_DROP = re.compile(r"\((?:[^()]*\b(?:died|invalided|dismissed|appointed|replac\w*|who|eldest|acting|temp|being|when|"
                        r"court-martial\w*|confirmed|earlier|except)\b[^()]*)\)", re.I)
GENERIC_STATION = re.compile(r"\b(?:for|on)\s+(?:the\s+)?((?:[A-Z][a-z]+\s+){1,2})[Ss]tation\b")
COASTGUARD = re.compile(r"\b(?:for|as)\s+(?:a\s+|the\s+)?coast\s?guard(?:\s+ship)?\s+(at|on)\s+(?:the\s+)?"
                        r"([A-Z][\w'’]*(?:\s+(?:Water|Roads|Sound))?)")
PACKET = re.compile(r"\b(?:(?:mail\s+)?packet\s+(?:service|brig)\s+(?:based\s+)?at\s+([A-Z]\w+)|(?:for\s+|as\s+)?(?:the\s+|a\s+)?([A-Z]\w+)\s+(?:mail\s+)?packet(?:\s+service)?\b)")
SAME = re.compile(r"\b(?:on|for)\s+(?:the\s+)?same\s+(station|service)\b", re.I)
DATE_AFTER = re.compile(r"^\s*(?:\(\s*)?(?:from\s+|to\s+|until\s+|-\s*)?((?:\d{1,2}[.\-–]){0,3}\d{4}(?:\s*[-–]\s*(?:\d{1,2}\.){0,2}\d{2,4})?)")
DATE_BEFORE = re.compile(r"(?:\b(?:then|later|and)|,)\s*(?:at\s+end\s+|in\s+)?((?:\d{1,2}\.){0,2}\d{4})\s+(?:to|at)\s+(?:the\s+)?$", re.I)


def _clean(span, officer):
    s = span
    if officer and officer in s:
        s = s.replace(officer, " " * len(officer))   # 艦長名の中の語を地名と取り違えない（位置は保つ）
    s = PAREN_DROP.sub(lambda m: " " * len(m.group(0)), s)
    return s


def find_stations(span, officer, prev, find_date, rules):
    """戻り値: 配属先の list。各要素 {label, seq, kind, proposed, begin, end, bp, ep, date_text, inferred, rule}。
    role=True の要素は ST3 の役割の印（配属先ではない）
    prev: その艦で直前に記録した配属先（ST4 で使う）。find_date は extract_events_v1.find_date"""
    s = _clean(span, officer)
    hits = []   # (start, end, label, proposed, kind, rule)
    taken = []

    def free(a, b):
        return not any(a < y and x < b for x, y in taken)

    for m in COASTGUARD.finditer(s):
        hits.append((m.start(), m.end(), f"coastguard {m.group(1)} {m.group(2)}", "coastguard: " + m.group(2), "coastguard", "ST3"))
        taken.append((m.start(), m.end()))
    for m in PACKET.finditer(s):
        if free(m.start(), m.end()):
            place = m.group(1) or m.group(2)
            hits.append((m.start(), m.end(), "packet service at " + place, "packet: " + place, "packet", "ST3"))
            taken.append((m.start(), m.end()))
    for rx, norm, kind in GAZ:
        for m in rx.finditer(s):
            a, b = m.start(), m.end()
            if not free(a, b):
                continue
            before = s[max(0, a - 60):a]
            if not CUE.search(before) or EXCLUDE_BEFORE.search(before):
                continue
            hits.append((a, b, re.sub(r"\s+", " ", m.group(0)).strip(), norm, kind, "ST1"))
            taken.append((a, b))
    for m in GENERIC_STATION.finditer(s):
        a, b = m.start(1), m.end()
        if free(a, b) and not re.match(r"(?:Same|The)\b", m.group(1)):
            label = (m.group(1) + "station").strip()
            hits.append((a, b, label, label.replace(" station", ""), "sea", "ST2"))
            taken.append((a, b))
    # "same service" は直前の配属先が郵便船・沿岸警備のときだけ（"on same service" の測量などは配属先にしない）
    same = [(m.start(), m.end()) for m in SAME.finditer(s) if free(m.start(), m.end())
            and (m.group(1).lower() == "station" or (prev and prev[-1]["kind"] in ("packet", "coastguard")))]

    items = sorted([(h[0], h) for h in hits] + [(a, ("SAME", a, b)) for a, b in same], key=lambda x: x[0])
    out, seq, last_end = [], 0, 0
    for pos, h in items:
        gap = s[last_end:pos]
        if not out or SEQ_WORD.search(gap):
            seq += 1
        a, b = (h[1], h[2]) if h[0] == "SAME" else (h[0], h[1])
        dt, dtext = None, ""
        ma = DATE_AFTER.match(s[b:b + 30]) if h[0] == "SAME" or h[5] != "ST3" else None   # ST3 の後の日付は就役の日付

        mb = DATE_BEFORE.search(s[max(0, a - 40):a])
        if ma:
            dtext, dctx = ma.group(1), ma.group(0)   # "(-1845)" "to 1815" は終わり（find_date が前の語で判断する）
        elif mb:
            dtext = dctx = mb.group(1)
        if dtext:
            dt = find_date(dctx.strip(), set())   # 日付の読み取りの規則（D1・D2）は出来事の rules 列に混ぜない
            rules.add("ST6")
        rec = {"seq": seq, "date_text": dtext, "begin": dt[0] if dt else "", "end": dt[1] if dt else "",
               "bp": dt[2] if dt else "", "ep": dt[3] if dt else ""}
        if h[0] == "SAME":
            if not prev:
                last_end = b
                continue   # 補う相手がない（この艦で前に配属先が出ていない）
            last_seq = prev[-1]["seq"]
            for p in [x for x in prev if x["seq"] == last_seq]:
                if p.get("role"):   # 沿岸警備・郵便船の後の same station は、その役割の続き（配属先を補わない）
                    out.append(dict(p, rule="ST3"))
                    continue
                out.append(dict(rec, label=p["label"], proposed=p["proposed"], kind=p["kind"], inferred=True, rule="ST4"))
                rules.add("ST4")
        else:
            out.append(dict(rec, label=re.sub(r"^the\s+", "", h[2]), proposed=h[3], kind=h[4], inferred=False, rule=h[5],
                            role=h[5] == "ST3"))
            if h[5] != "ST3":
                rules.add(h[5])
        last_end = b
    if out and re.search(r"\ball\s+(?:in|on|at)\b", s):
        for o in out:
            o["all"] = True   # ST7（extract_events_v1.py が同じ節の前の出来事に写す）
    if len({o["seq"] for o in out if not o.get("role")}) > 1:
        rules.add("ST5")
    return out
