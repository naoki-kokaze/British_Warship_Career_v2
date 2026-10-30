"""規則v1：出来事の列から、2軸（任務上の地位・工廠での工事）の Presence を組み立てる（記録の層）

入力：../outputs/rules_v1/events.csv（extract_events_v1.py の出力）
出力：../outputs/rules_v1/presences.csv・presence_checks.csv・presence_summary.json

組み立ての規則（決定 A1・B1・C1・D1・F、2026-10-01〜07）
    P1  任務上の地位（service）：status_effect の service:<状態> を持つ出来事で Presence が始まる。
        始まりの日付は、その出来事の終わりの日付（P182i：出来事の終わりの後に始まる）
    P2  同じ艦の次の「地位に関わる出来事」（service:*・end・BeingBrokenUp）で終わる。終わりの日付は、
        次の出来事の始まりの日付（P182：次の出来事の始まりの前に終わる）。次の出来事がなければ終わりは空（開いたまま）
    P3  1つの出来事に service が2つあるとき（"paid off as tender" → PaidOff;InNonCombatDuty）は、
        退役後の期間を作らず、後ろの地位にする（決定B1の "paid off into Ordinary" と同じ）
    P4  地位の印（EV06：laid up / in Ordinary / Steam Reserve など。type が "(status)"）が、すでに同じ地位の
        Presence の中で出てきた場合は、新しい Presence を作らず、その Presence の注記に加える
    P5  :BeingBrokenUp（海軍自身による解体）は、解体の出来事の期間そのもの（始まり〜完了）。終端の地位。
        "BU completed D" は終わりだけ（始まりは空。U2）
    P6  end（売却・喪失・贈与など）は、開いている Presence を終えるだけで、新しい Presence は作らない
    P7  service:end_InOtherCustody（返還）は :InOtherCustody を終える。その後の地位は推測で埋めない
    P8  工事（work）：work:<状態> を持つ出来事の期間そのものを1つの Presence にする（工事の軸は出来事と同じ期間）
    P8a 1つの出来事の工事の状態が重なれば1つにし、修理と艤装の両方なら :UnderRepairAndFitting の1つにする（決定C1。2026-10-14）
    P9  地位の変化を伴わない出来事（none・role_seagoing・空）は Presence を作らない
    P10 日付のない出来事の Presence は、日付を空にして順番（event_no）だけを残す。日付を推測しない
    P11 出来事は原文の順（event_no）に読む。ただし、キャリアの終わり（end）の後に、それより前の日付の出来事が
        続く場合（叙述の冒頭に "Sold 11.1887 to BU" とある PGV_0005 など）は、終わりの出来事を日付の上での位置
        （その日付以前の最後の出来事の後）に移す
    P13 役割の文（EV32）に終わりがあれば（"1834-50"・"to 1868"）、港での任務の Presence はそこで終わる。その後は空ける
    P14 B1r：退役後・予備役の後（または就役の記録がないとき）の、任地・任務つきの最初の艦長任命は、就役中の Presence を
        始める（就役の出来事は作らない。derived = B1r と注記で区別）。任地のない任命は状態を変えない（決定B1のまま）
    P12 キャリアの終わりの後の出来事からは Presence を作らない（植民地政府の下での再就役、転売後の喪失など。K2 に記録）
    P15 竣工が "for Ordinary"（見出しの C: の行、header_facts.csv の qualifier）なら、竣工の終わりから予備役の Presence を
        始める（2026-10-17、試しの判定 SF5_9041 "C: 11.9-20.9.1813 at Plymouth for Ordinary, then laid up"）。続く地位の印
        "laid up" は P4 でこの Presence の注記になる。start_event は見出しの竣工のノード（completion_<艦>）

検査（SHACL の前の下見。SHACL 本体は RDF 化の後）
    K1  就役の記録のない退役（決定B1の警告）
    K2  キャリアの終わり（end・BeingBrokenUp）の後の出来事
    K3  地位の Presence の日付が前の Presence より前に戻る（日付の細かさを揃えて比べる。OCR の年の誤りの候補）
    K4  解体の始まり（なければ完了）の後に始まる工事（決定D1）

要確認の印（review_note。2026-10-07、裁定 §11.5 の3）
    F1  就役中・退役後の Presence が、その艦の日付つきの文を1つも挟まずに5年以上続く（就役中は退役の書き落とし、
        退役後は次の地位が書かれていないことの候補。規則P2の仮定に依存する）。港での任務は長く続くのが普通なので対象外
    F2  B1r で導いた就役中（P14）
"""
import csv
import json
import os
import re
from collections import Counter

import sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import dataset_paths as P   # 開発用／評価用の切り替え（JINMON_DATASET）
OUT = P.out("rules_v1")
EVENTS = os.path.join(OUT, "events.csv")
HEADER_FACTS = os.path.join(P.out("rules_v0"), "header_facts.csv")

WORK_STATUS = {"UnderRepair", "UnderFitting", "UnderRepairAndFitting"}
# B1r の任地・任務（"for the East Indies and China"、"in the West Indies"、"for voyage home"、"on ... station"）
DEST = __import__("re").compile(
    r"\bfor\s+(?:the\s+)?(?:[A-Z]|voyage|passage|service)|\b(?:in|on|to)\s+(?:the\s+)?(?:[A-Z][a-z]+\s+)*(?:station|squadron|"
    r"Indies|Mediterranean|Baltic|Pacific|Channel|Africa|America|China|Brazil|Lisbon|Cape)\b|\bstation\b|\bsquadron\b")


def effects(ev):
    return [e for e in ev["status_effect"].split(";") if e]


def service_states(ev):
    return [e.split(":", 1)[1] for e in effects(ev) if e.startswith("service:") and not e.startswith("service:end_")]


def work_states(ev):
    """P8a（2026-10-14、試しの判定 SBS_9095・PSPV_9003）：同じ工事の状態が重なれば1つにする（型を2つ持つ修理
    ":Refit + sealit:ShipRepair"）。修理と艤装が1つの出来事（境目のない1つの期間）にあれば、決定C1 のとおり
    :UnderRepairAndFitting の Presence を1つにする（"Middling Repair and fitted for Ordinary ... 3.1819-5.1820"）"""
    states = list(dict.fromkeys(e.split(":", 1)[1] for e in effects(ev) if e.startswith("work:")))
    if "UnderRepair" in states and "UnderFitting" in states:
        states = ["UnderRepairAndFitting"] + [s for s in states if s not in ("UnderRepair", "UnderFitting")]
    return states


def is_service_boundary(ev):
    """地位の Presence を終える出来事か"""
    eff = effects(ev)
    return bool(service_states(ev)) or "end" in eff or any(e.startswith("service:end_") for e in eff)


def date_key(d):
    """'1864-07-07' / '1864-07' / '1864' を比べられる形に（不明な部分は 00）"""
    if not d:
        return ""
    parts = d.split("-") + ["00", "00"]
    return "".join(p.zfill(2) if i else p.zfill(4) for i, p in enumerate(parts[:3]))


def earlier(a, b):
    """a が b より前か（細かさの粗いほうに揃えて比べる。'1836-12' と '1836-12-09' は同時とみなす）"""
    n = min(len(a.split("-")), len(b.split("-")))
    return date_key("-".join(a.split("-")[:n])) < date_key("-".join(b.split("-")[:n]))


def reorder(evs):
    """P11：日付の上で後ろにあるべき終わりの出来事を移す"""
    evs = list(evs)
    for ev in [e for e in evs if "end" in effects(e) and e["begin"]]:
        i = evs.index(ev)
        later = [e for e in evs[i + 1:] if e["begin"] and earlier(e["begin"], ev["begin"])]
        if not later:
            continue
        j = max(evs.index(e) for e in later)
        evs.insert(j + 1, evs.pop(i))
        ev["_moved"] = True
    return evs


def pid(ship, begin, status, used):
    key = (date_key(begin) or "00000000")
    base = f"{ship}_{key}_presence_{status}"
    used[base] += 1
    return base if used[base] == 1 else f"{base}_{used[base]}"


def years(d):
    m = __import__("re").match(r"(\d{4})(?:-(\d{2}))?", d or "")
    return int(m.group(1)) + ((int(m.group(2)) - 1) / 12 if m.group(2) else 0) if m else None


def flag_silent(presences, events, threshold=5):
    """F1・F2：要確認の印"""
    dates = {}
    for ev in events:
        d = years(ev["begin"] or ev["end"])
        if d is not None:
            dates.setdefault(ev["ship"], []).append(d)
    for p in presences:
        if p.get("derived") == "B1r":
            p["review_note"] = "F2: in commission derived from a command appointment (rule B1r); no commissioning stated"
            continue
        if p["axis"] != "service" or p["status"] not in ("InCommission", "PaidOff"):
            continue
        b, e = years(p["begin"]), years(p["end"])
        if b is None or e is None or e <= b:
            continue
        inside = sorted(d for d in dates.get(p["ship"], []) if b + 0.01 < d < e - 0.01)
        gap = max(x2 - x1 for x1, x2 in zip([b] + inside, inside + [e]))
        if gap >= threshold:
            p["review_note"] = (f"F1: no dated statement for {gap:.0f} years; the status is assumed to continue "
                                f"(rule P2){' - the end of the commission may be unstated' if p['status'] == 'InCommission' else ' - the next status is not stated (decision B1)'}")


def completed_for_ordinary():
    """P15：見出しの竣工が "for Ordinary" の艦 → 竣工の行"""
    out = {}
    for r in csv.DictReader(open(HEADER_FACTS, encoding="utf-8-sig")):
        if r["field"] == "COMPLETED" and re.search(r"\bfor\s+Ordinary\b", r["qualifier"]) and (r["end"] or r["begin"]):
            out[r["ship"]] = r
    return out


def main():
    events = list(csv.DictReader(open(EVENTS, encoding="utf-8-sig")))
    for_ordinary = completed_for_ordinary()
    by_ship = {}
    for ev in events:
        by_ship.setdefault(ev["ship"], []).append(ev)
    presences, checks, used, moved, derived = [], [], Counter(), [], []

    for ship, evs in by_ship.items():
        evs.sort(key=lambda e: int(e["event_no"]))
        evs = reorder(evs)
        moved.extend(e["id"] for e in evs if e.get("_moved"))
        current = None          # 開いている地位の Presence
        ended_by = None         # キャリアを終えた出来事
        had_commission = False
        last_begin = ""
        c = for_ordinary.get(ship)
        if c:   # P15
            current = {"id": pid(ship, c["end"] or c["begin"], "InOrdinary", used), "ship": ship, "axis": "service",
                       "status": "InOrdinary", "begin": c["end"] or c["begin"],
                       "begin_precision": c["end_precision"] or c["begin_precision"], "end": "", "end_precision": "",
                       "start_event": f"completion_{ship}", "end_event": "", "relation": "after_start_event", "seq": "0",
                       "role_text": "", "note": "begins at the completion for Ordinary (rule P15)"}
            presences.append(current)
            last_begin = current["begin"]

        def close(p, ev, end_date, prec):
            p["end"], p["end_precision"], p["end_event"] = end_date, prec, ev["id"] if ev else ""

        for ev in evs:
            eff = effects(ev)
            if ended_by and (eff and eff != ["none"]) and "after the end of the RN career" not in ev["note"]:
                checks.append({"check": "K2", "ship": ship, "id": ev["id"],
                               "detail": f"event after the end of the career ({ended_by})", "raw": ev["raw"][:120]})
            if ended_by:
                continue   # P12

            # 工事（P8）
            for w in work_states(ev):
                presences.append({"id": pid(ship, ev["begin"], w, used), "ship": ship, "axis": "work", "status": w,
                                  "begin": ev["begin"], "begin_precision": ev["begin_precision"],
                                  "end": ev["end"], "end_precision": ev["end_precision"],
                                  "start_event": ev["id"], "end_event": ev["id"], "relation": "during",
                                  "seq": ev["event_no"], "role_text": "", "note": ""})

            # B1r（2周目、2026-10-07 ユーザー承認）：退役後・予備役の後（または就役の記録がないとき）の、任地・任務つきの
            # 最初の艦長任命は、就役中の Presence を始める。就役の出来事は作らず、規則で導いた値であることを注記する
            if (ev["type"] == ":CommandAppointment" and DEST.search(ev["raw"])
                    and (current is None and not had_commission or current and current["status"] in ("PaidOff", "InOrdinary"))):
                if current:
                    close(current, ev, ev["begin"], ev["begin_precision"])
                p = {"begin": ev["end"] or ev["begin"], "begin_precision": ev["end_precision"] or ev["begin_precision"],
                     "relation": "after_start_event"}
                p.update({"id": pid(ship, p["begin"], "InCommission", used), "ship": ship, "axis": "service",
                          "status": "InCommission", "end": "", "end_precision": "", "start_event": ev["id"], "end_event": "",
                          "seq": ev["event_no"], "role_text": "", "derived": "B1r",
                          "note": "derived by rule B1r: a command appointment with a destination after paying off "
                                  "(or with no commission recorded); no commissioning is stated in the source"})
                presences.append(p)
                current, had_commission = p, True
                derived.append(p["id"])
                continue

            if not is_service_boundary(ev):
                continue
            states = service_states(ev)

            # P13（2周目、2026-10-07）：役割の文（EV32）に終わりがある（"Receiving ship there 1834-50"、"hulk at Plymouth to 1868"）
            # 場合は、その終わりで地位の Presence を終える。その後は推測で埋めない
            role_end = ((ev["rules_trigger"] == "EV32" or ev["type"] in ("(status)", "(status: stored ashore)"))
                        and ev["date_role"] in ("period", "to") and ev["end"])   # 地位の印の期間（"In Ordinary 1817-20"）も
            if role_end and current and states and states[-1] == current["status"]:
                close(current, ev, ev["end"], ev["end_precision"])
                current["note"] = "; ".join(x for x in (current["note"], f"end stated: {ev['raw'][:60]}") if x)
                current = None
                continue

            # 地位の印（P4）
            if current and states and states[-1] == current["status"] and ev["type"] == "(status)":
                current["note"] = "; ".join(x for x in (current["note"], f"also stated: {ev['raw'][:60]}") if x)
                continue

            if "PaidOff" in states and not had_commission:
                checks.append({"check": "K1", "ship": ship, "id": ev["id"],
                               "detail": "paid off without a recorded commission (decision B1)", "raw": ev["raw"][:120]})
            if "InCommission" in states:
                had_commission = True

            # 開いている Presence を閉じる（P2・P6・P7）
            if current:
                close(current, ev, ev["begin"], ev["begin_precision"])
                current = None
            if "end" in eff:
                ended_by = ended_by or ev["id"]
            if not states:
                continue

            s = states[-1]   # P3
            if s == "BeingBrokenUp" or role_end:   # P5・P13：出来事（文）の期間そのもの
                p = {"begin": ev["begin"], "begin_precision": ev["begin_precision"], "relation": "during"}
                if s == "BeingBrokenUp":
                    ended_by = ended_by or ev["id"]
            else:
                p = {"begin": ev["end"] or ev["begin"], "begin_precision": ev["end_precision"] or ev["begin_precision"],
                     "relation": "after_start_event"}
            p.update({"id": pid(ship, p["begin"], s, used), "ship": ship, "axis": "service", "status": s,
                      "end": "", "end_precision": "", "start_event": ev["id"], "end_event": "",
                      "seq": ev["event_no"], "role_text": ev["role_text"], "note": ""})
            if s == "BeingBrokenUp" or role_end:
                p.update(end=ev["end"], end_precision=ev["end_precision"], end_event=ev["id"])
            if p["begin"] and last_begin and earlier(p["begin"], last_begin):
                checks.append({"check": "K3", "ship": ship, "id": p["id"],
                               "detail": f"begins {p['begin']} before the previous service Presence ({last_begin})",
                               "raw": ev["raw"][:120]})
            if p["begin"]:
                last_begin = p["begin"]
            presences.append(p)
            current = None if s == "BeingBrokenUp" or role_end else p

        # K4：解体中と工事の重なり
        bu = [p for p in presences if p["ship"] == ship and p["status"] == "BeingBrokenUp"]
        for b in bu:
            for w in (p for p in presences if p["ship"] == ship and p["axis"] == "work"):
                ref = b["begin"] or b["end"]   # "BU completed D" は始まりがない（U2）ので終わりと比べる
                if w["begin"] and ref and date_key(w["begin"]) > date_key(ref):
                    checks.append({"check": "K4", "ship": ship, "id": w["id"],
                                   "detail": f"dockyard work overlaps or follows {b['id']}", "raw": ""})

    flag_silent(presences, events)
    fields = ["id", "ship", "axis", "status", "begin", "begin_precision", "end", "end_precision",
              "start_event", "end_event", "relation", "seq", "role_text", "derived", "review_note", "note"]
    with open(os.path.join(OUT, "presences.csv"), "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, restval="")
        w.writeheader()
        w.writerows(presences)
    with open(os.path.join(OUT, "presence_checks.csv"), "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["check", "ship", "id", "detail", "raw"])
        w.writeheader()
        w.writerows(checks)
    svc = [p for p in presences if p["axis"] == "service"]
    summary = {
        "presences": len(presences),
        "by_axis_status": dict(Counter(f"{p['axis']}:{p['status']}" for p in presences).most_common()),
        "service_open_ended": sum(1 for p in svc if not p["end_event"]),
        "service_undated_begin": sum(1 for p in svc if not p["begin"]),
        "ships_with_presence": len({p["ship"] for p in presences}),
        "checks": dict(Counter(c["check"] for c in checks)),
        "end_events_moved_by_date": moved,
        "derived_B1r": derived,
        "review_notes": dict(Counter(p["review_note"].split(":")[0] for p in presences if p.get("review_note"))),
    }
    json.dump(summary, open(os.path.join(OUT, "presence_summary.json"), "w"), ensure_ascii=False, indent=2)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
