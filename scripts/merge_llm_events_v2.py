"""④ LLM の候補のうち、人が採用したもの（sources/manual/llm_residual_review.csv の verdict = accept / modify）を、
規則の出来事の列（outputs/rules_v1/events.csv）に加える（対応表 §14）

処理の順：extract_events_v1.py（規則）→ この統合 → build_presence_v1.py → convert_events_v2.py → SHACL。
規則を再実行すると LLM の行は消えるので、そのつどこの統合を実行し直す。何度実行しても結果は同じ（既にある LLM の行は
いったん除いてから加え直す）

統合の前の確認（通らない行は加えず、理由を表示する）
    - verdict が accept か modify
    - date_text が原文の節にある（人が直した値も含めて）。例外：verdict が modify で reason が "OCR:" で始まる行は、
      人が頁の画像で OCR の誤りを直した値なので照合しない（2026-10-14 ユーザー決定。本評価の分に限った暫定。
      OCR の訂正表を抽出の前に当てる仕組みは、第4章の PS4・PS5・PS7 の15件の確認時に検討する）
    - kind が閉じた語彙にある。role / role_end の役割は判断表（role_seagoing_judgement.csv）にある
    - renaming は new_name がある
出所：rules 列に "LLM:<モデル>:<プロンプトの版>:<ハッシュ>"（RDF の :generated_by_rule になる）、note 列に人の判断

評価用（JINMON_DATASET=eval_v2）は案(b)（2026-10-08 決定。対応表 §15・ログ 10/8）：verdict が空の行（人がまだ確認していない
候補）も、上の自動の確認を通れば加える。note に "not yet reviewed (evaluation design b)" と書き、院生の判定のあとで人が確認する。
reject の行は加えない（あとで人が確認したときに、完成品の品質を計算し直すのに使う）

使い方: python3 merge_llm_events_v2.py [--events <events.csv>]（既定は outputs/rules_v1/events.csv を上書き）
"""
import collections
import csv
import glob
import importlib.util
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import dataset_paths as P   # 開発用／評価用の切り替え（JINMON_DATASET）
EVENTS = P.out("rules_v1/events.csv")
CLAUSES = P.out("rules_v1_survey/clauses.csv")
REVIEW = P.manual("llm_residual_review.csv")
ROLES = P.LLM_ROLE_TABLES
RAW = P.out("llm_residual/raw")

UNREVIEWED_OK = P.DATASET == "eval_v2"   # 案(b)

# 種類 → 規則の出来事と同じ書き方（type・cidoc・status_effect・ID の種類の部分）
KIND = {
    "commissioning": (":Commissioning", "E7", "service:InCommission", "commissioning"),
    "recommissioning": (":Recommissioning", "E7", "service:InCommission", "recommissioning"),
    "decommissioning": (":Decommissioning", "E7", "service:PaidOff", "decommissioning"),
    "in_ordinary": ("(status)", "", "service:InOrdinary", "laid_up"),
    "role": ("(role)", "", None, "role"),
    "role_end": ("(role end)", "", "service:end_InNonCombatDuty", "role_end"),
    "fitting": (":Fitting", "E11", "work:UnderFitting", "fitting"),
    "repair": ("sealit:ShipRepair", "E11", "work:UnderRepair", "repair"),
    "conversion": (":ShipConversion", "E11", "none", "conversion"),
    "sale": ("E96_Purchase (sale)", "E96", "end", "sale"),
    "acquisition": ("E96_Purchase (acquisition)", "E96", "start", "purchase"),
    "breaking_up": ("E6_Destruction (breaking up)", "E6", "service:BeingBrokenUp", "breaking_up"),
    "loss": ("E6_Destruction (loss)", "E6", "end", "loss"),
    "renaming": ("E15 (renaming)", "E15", "none", "renaming"),
    "loan": ("E10 :Loan", "E10", "service:InOtherCustody", "loan"),
    "transfer": ("E10 :Transfer", "E10", "service:InOtherCustody", "transfer"),
    "rating_change": ("E13 :changes_ship_rating", "E13", "none", "rerating"),
}


def norm(s):
    return re.sub(r"\s+", " ", s or "").strip()


def provenance():
    """生の応答のメタデータから "LLM:<モデル>:<プロンプトの版>:<ハッシュ>" を作る（すべての応答で同じであることを確かめる）"""
    tags = set()
    for fn in glob.glob(os.path.join(RAW, "run*", "*.json")):
        r = json.load(open(fn, encoding="utf-8"))
        tags.add(f"LLM:{r['served_model']}:{r['prompt_version']}:{r['prompt_sha256_12']}")
    if len(tags) != 1:
        sys.exit(f"the raw responses do not share one model and prompt: {sorted(tags)}")
    return tags.pop()


def main(events_path=EVENTS):
    spec = importlib.util.spec_from_file_location("E", os.path.join(HERE, "extract_events_v1.py"))
    E = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(E)
    tag = provenance()
    judgement = {r["role"]: [v for k, v in r.items() if k.startswith("judgement")][0]
                 for p in ROLES for r in csv.DictReader(open(p, encoding="utf-8-sig"))}
    clause = {(c["ship"], int(c["clause_no"])): c["clause"] for c in csv.DictReader(open(CLAUSES, encoding="utf-8-sig"))}
    events = [e for e in csv.DictReader(open(events_path, encoding="utf-8-sig")) if not e["rules"].startswith("LLM:")]
    cols = list(events[0].keys())
    review = list(csv.DictReader(open(REVIEW, encoding="utf-8-sig"))) if os.path.exists(REVIEW) else []

    added, skipped = [], collections.Counter()
    for r in review:
        v = r["verdict"].strip().lower()
        if not v and UNREVIEWED_OK:
            v = "unreviewed"
        if v not in ("accept", "modify", "unreviewed"):
            skipped[v or "(not decided)"] += 1
            continue
        ship, n = r["ship"], int(r["clause_no"])
        text = clause.get((ship, n), "")
        kind, role, dtext = r["kind"].strip(), r["role"].strip().lower(), r["date_text"].strip()
        problem = ""
        if kind not in KIND:
            problem = f"kind '{kind}' not in the vocabulary"
        elif dtext and norm(dtext) not in norm(text) and not (v == "modify" and r["reason"].startswith("OCR:")):
            problem = f"date_text '{dtext}' not in the clause"
        elif kind == "role" and judgement.get(role) not in ("harbour", "seagoing"):
            problem = f"role '{role}' is not in the judgement table (add it there first)"
        elif kind == "renaming" and not r["new_name"].strip():
            problem = "renaming without new_name"
        if problem:
            print(f"not merged: {r['key']}: {problem}")
            skipped["problem"] += 1
            continue
        typ, cidoc, effect, _ = KIND[kind]
        if kind == "role":
            effect = "service:InNonCombatDuty" if judgement[role] == "harbour" else "role_seagoing"
        rules = set()
        dt = E.find_date(dtext, rules) if dtext else None
        yr = E.year_range(dtext) if dtext else None
        if yr and (not dt or (dt[2] == "year" and dt[0] == yr[0])):
            dt = (yr[0], yr[1], "year", "year", False, "period")
        b, e, bp, ep, unc, drole = dt if dt else ("", "", "", "", False, "")
        if v == "unreviewed":
            note = "LLM candidate, not yet reviewed (evaluation design b)"
        else:
            note = f"LLM candidate {'accepted' if v == 'accept' else 'modified'} by human review ({r['decided'] or 'undated'})"
        if r["reason"].strip():
            note += f": {r['reason'].strip()}"
        if v == "modify":
            note += f" [LLM said: {r['llm_kind']} / {r['llm_role'] or '-'} / {r['llm_date_text'] or '-'}]"
        added.append({c: "" for c in cols} | {
            "ship": ship, "clause_no": str(n), "rules_trigger": "LLM", "type": typ, "cidoc": cidoc,
            "begin": b, "end": e, "begin_precision": bp, "end_precision": ep, "date_role": drole, "uncertain": str(unc),
            "role_text": role if kind in ("role", "role_end") else "", "new_name": r["new_name"].strip(),
            "status_effect": effect, "rules": tag, "status": "parsed", "note": note, "raw": r["quote"],
            "_slug": KIND[kind][3]})

    # 原文の順（節の番号、同じ節では規則の出来事の後）に並べ直し、event_no を振り直す。ID は案c（§5.5）で LLM の行にだけ付ける
    by_ship = collections.defaultdict(list)
    for ev in events:
        by_ship[ev["ship"]].append(ev)
    for ev in added:
        by_ship[ev["ship"]].append(ev)
    ids = {ev["id"] for ev in events}
    out = []
    for ship in by_ship:
        evs = sorted(by_ship[ship], key=lambda x: (int(x["clause_no"]), 1 if x["rules_trigger"] == "LLM" else 0,
                                                    int(x["event_no"]) if x.get("event_no") else 0))
        prev_date = "00000000"
        for i, ev in enumerate(evs, 1):
            ev["event_no"] = str(i)
            if ev["rules_trigger"] == "LLM":
                d = (ev["begin"] or ev["end"]).replace("-", "")
                base = f"{ship}_{(d + '0000')[:8] if d else prev_date}_{ev.pop('_slug')}_llm"
                if not d:
                    base += "_u1"
                k, new_id = 1, base
                while new_id in ids:
                    k += 1
                    new_id = f"{base}_{k}"
                ev["id"] = new_id
                ids.add(new_id)
            d = (ev["begin"] or ev["end"]).replace("-", "")
            if d:
                prev_date = (d + "0000")[:8]
            out.append(ev)
    with open(events_path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(out)
    print(json.dumps({"dataset": P.DATASET, "provenance": tag, "merged": len(added),
                      "merged_unreviewed": sum("not yet reviewed" in a["note"] for a in added), "rule_events": len(events),
                      "not_merged": dict(skipped)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main(sys.argv[sys.argv.index("--events") + 1] if "--events" in sys.argv else EVENTS)
