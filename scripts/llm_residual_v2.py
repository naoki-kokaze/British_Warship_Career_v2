"""v2 の LLM の部分：規則で出来事にならなかった節（残り）だけを LLM に読ませ、キャリアの状態の変化の候補を出させる

方針（2026-10-07 ユーザー承認。対応表 §14）
    - LLM は候補を指し示すだけ。値は作らせない：種類は閉じた語彙、根拠は原文の引用、日付は原文の文字列のまま
    - 検証（validate）で、引用と日付の文字列が原文の節にあるかを確かめ、なければ捨てる。日付は規則の部品で読み直し、
      役割は判断表（sources/manual/role_seagoing_judgement.csv）で地位にする
    - LLM 由来の候補は人が全件確認する（review 用の CSV）。RDF には :generated_by_rule "LLM:<モデル>:<プロンプトの版>"
    - 再現性：モデル ID とプロンプトの版を固定し、生の応答を保存する。変換は保存した応答から決定論的に行う
    - 安定性：同じ入力で2回実行し（run1・run2）、候補の一致率を出す

使い方（サンドボックスの外で。API の認証情報が必要）
    python3 llm_residual_v2.py run 1          # 1回目。保存済みの艦は呼ばない（途中から再開できる）
    python3 llm_residual_v2.py run 2          # 2回目
    python3 llm_residual_v2.py run 1 --limit 3   # 試しに3隻だけ
    python3 llm_residual_v2.py run 1 --ships SF5_9041,SBS_9095   # 指定した艦だけ
    評価用（JINMON_DATASET=eval_v2）では run 1 の1回だけ実行し、--ships trial / --ships main で
    選定一覧（outputs/eval_v2/eval_v2_selection.csv）の試し／本評価の艦に絞れる
    python3 llm_residual_v2.py validate       # 保存した応答を検証し、候補と安定性を出す（API は呼ばない）
    python3 llm_residual_v2.py review-sheet   # 人の確認の記録（sources/manual/llm_residual_review.csv）に新しい候補を書き足す

入力: ../outputs/rules_v1/events.csv、../outputs/rules_v1_survey/clauses.csv、prompts/llm_residual_v1.md
出力: ../outputs/llm_residual/raw/run<N>/<艦>.json（生の応答とメタデータ）、candidates.csv、llm_residual_summary.json
依存: anthropic（0.104.1 で確認）
"""
import collections
import csv
import hashlib
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import dataset_paths as P   # 開発用／評価用の切り替え（JINMON_DATASET）
EVENTS = P.out("rules_v1/events.csv")
CLAUSES = P.out("rules_v1_survey/clauses.csv")
ROLES = P.LLM_ROLE_TABLES
PROMPT = os.path.join(HERE, "prompts/llm_residual_v1.md")
OUT = P.out("llm_residual")
MODEL = "claude-opus-5-5"
PROMPT_VERSION = "llm_residual_v1"
KINDS = ["commissioning", "recommissioning", "decommissioning", "in_ordinary", "role", "role_end", "fitting", "repair",
         "conversion", "sale", "acquisition", "breaking_up", "loss", "renaming", "loan", "transfer", "rating_change"]
SCHEMA = {
    "type": "object",
    "properties": {
        "clauses": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "clause_no": {"type": "integer"},
                    "items": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "kind": {"type": "string", "enum": KINDS},
                                "subject_is_this_ship": {"type": "boolean"},
                                "quote": {"type": "string"},
                                "date_text": {"type": "string"},
                                "role": {"type": "string"},
                                "note": {"type": "string"},
                            },
                            "required": ["kind", "subject_is_this_ship", "quote", "date_text", "role", "note"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["clause_no", "items"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["clauses"],
    "additionalProperties": False,
}


def residual_by_ship():
    """{艦: (全節 [(番号, 文)], 対象の番号の集合)}。対象＝規則の出来事が1つもない節"""
    used = {(e["ship"], e["clause_no"]) for e in csv.DictReader(open(EVENTS, encoding="utf-8-sig"))
            if not e["rules"].startswith("LLM:")}   # 統合した LLM の行は数えない（対象が変わらないように）
    ships = collections.OrderedDict()
    for c in csv.DictReader(open(CLAUSES, encoding="utf-8-sig")):
        ships.setdefault(c["ship"], ([], set()))
        ships[c["ship"]][0].append((int(c["clause_no"]), c["clause"]))
        if (c["ship"], c["clause_no"]) not in used:
            ships[c["ship"]][1].add(int(c["clause_no"]))
    return {s: v for s, v in ships.items() if v[1]}


def user_message(ship, clauses, targets):
    lines = [f"Ship: {ship}", ""]
    for n, text in clauses:
        lines.append(f"{'[TARGET] ' if n in targets else ''}[{n}] {text}")
    return "\n".join(lines)


def ship_filter(arg):
    """--ships の値（艦のIDのカンマ区切り、または選定一覧の role：trial / main / reserve）を艦の集合にする"""
    if arg in ("trial", "main", "reserve"):
        sel = os.path.join(P.out(""), "eval_v2_selection.csv")
        return {r["id"] for r in csv.DictReader(open(sel, encoding="utf-8-sig")) if r["role"] == arg}
    return set(arg.split(","))


def run(run_id, limit=None, ships=None):
    import anthropic
    client = anthropic.Anthropic()
    system = open(PROMPT, encoding="utf-8").read()
    phash = hashlib.sha256(system.encode()).hexdigest()[:12]
    raw_dir = os.path.join(OUT, "raw", f"run{run_id}")
    os.makedirs(raw_dir, exist_ok=True)
    todo = residual_by_ship()
    done = 0
    for ship, (clauses, targets) in todo.items():
        if ships is not None and ship not in ships:
            continue
        path = os.path.join(raw_dir, f"{ship}.json")
        if os.path.exists(path):
            continue
        if limit is not None and done >= limit:
            break
        msg = user_message(ship, clauses, targets)
        for attempt in range(3):
            try:
                resp = client.beta.messages.create(
                    model=MODEL,
                    max_tokens=16000,
                    system=system,
                    messages=[{"role": "user", "content": msg}],
                    output_config={"effort": "medium", "format": {"type": "json_schema", "schema": SCHEMA}},
                    betas=["server-side-fallback-2026-07-01"],
                    extra_body={"fallbacks": "default"},
                )
                break
            except anthropic.RateLimitError:
                time.sleep(30 * (attempt + 1))
            except anthropic.APIConnectionError:
                time.sleep(10 * (attempt + 1))
        else:
            print(f"{ship}: failed after retries", file=sys.stderr)
            continue
        text = next((b.text for b in resp.content if b.type == "text"), "")
        iterations = [getattr(i, "type", "") for i in (getattr(resp.usage, "iterations", None) or [])]
        record = {
            "ship": ship, "run": run_id, "requested_model": MODEL, "served_model": resp.model,
            "fallback_ran": "fallback_message" in iterations, "prompt_version": PROMPT_VERSION, "prompt_sha256_12": phash,
            "stop_reason": resp.stop_reason, "targets": sorted(targets), "input": msg, "output_text": text,
            "usage": {"input_tokens": resp.usage.input_tokens, "output_tokens": resp.usage.output_tokens},
            "time": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        }
        json.dump(record, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        done += 1
        print(f"{ship}: {resp.stop_reason} ({resp.usage.input_tokens}+{resp.usage.output_tokens} tokens)")
    print(f"run{run_id}: {done} ships called, {len(todo)} ships with residual clauses")


def norm(s):
    return re.sub(r"\s+", " ", s or "").strip()


def validate():
    sys.path.insert(0, HERE)
    import importlib.util
    spec = importlib.util.spec_from_file_location("E", os.path.join(HERE, "extract_events_v1.py"))
    E = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(E)
    judgement = {r["role"]: [v for k, v in r.items() if k.startswith("judgement")][0]
                 for p in ROLES for r in csv.DictReader(open(p, encoding="utf-8-sig"))}
    todo = residual_by_ship()
    rows, stats = [], collections.Counter()
    keys = collections.defaultdict(set)
    for run_dir in sorted(os.listdir(os.path.join(OUT, "raw"))):
        for fn in sorted(os.listdir(os.path.join(OUT, "raw", run_dir))):
            rec = json.load(open(os.path.join(OUT, "raw", run_dir, fn), encoding="utf-8"))
            ship, run_id = rec["ship"], rec["run"]
            stats[f"run{run_id}_ships"] += 1
            if rec["stop_reason"] == "refusal":
                stats[f"run{run_id}_refusals"] += 1
                continue
            if rec.get("fallback_ran") or rec.get("served_model") != rec.get("requested_model"):
                stats[f"run{run_id}_served_by_other_model"] += 1
            try:
                out = json.loads(rec["output_text"])
            except json.JSONDecodeError:
                stats[f"run{run_id}_invalid_json"] += 1
                continue
            clause_text = dict(todo.get(ship, ([], set()))[0])
            targets = set(rec["targets"])
            seen = set()
            for c in out["clauses"]:
                n = c["clause_no"]
                if n not in targets:
                    stats["rejected_not_a_target"] += len(c["items"])
                    continue
                seen.add(n)
                text = clause_text.get(n, "")
                for it in c["items"]:
                    reason = ""
                    if not it["subject_is_this_ship"]:
                        reason = "not this ship"
                    elif norm(it["quote"]) not in norm(text):
                        reason = "quote not in the clause"
                    elif it["date_text"] and norm(it["date_text"]) not in norm(text):
                        reason = "date not in the clause"
                    rules = set()
                    dt = E.find_date(it["date_text"], rules) if it["date_text"] and not reason else None
                    yr = E.year_range(it["date_text"]) if it["date_text"] and not reason else None
                    if yr and (not dt or (dt[2] == "year" and dt[0] == yr[0])):   # 規則と同じ R4（"1866-90"）
                        dt = (yr[0], yr[1], "year", "year", False, "period")
                    role = it["role"].lower().strip()
                    effect = ""
                    if it["kind"] in ("role", "role_end") and not reason:
                        j = judgement.get(role, "")
                        effect = {"harbour": "service:InNonCombatDuty", "seagoing": "role_seagoing"}.get(j, "role_not_in_table")
                    rows.append({"run": run_id, "ship": ship, "clause_no": n, "kind": it["kind"], "role": role,
                                 "effect": effect, "date_text": it["date_text"], "begin": dt[0] if dt else "",
                                 "end": dt[1] if dt else "", "quote": it["quote"], "note": it["note"],
                                 "accepted_by_validation": "" if reason else "yes", "rejected_reason": reason,
                                 "clause": text, "served_model": rec.get("served_model", ""),
                                 "prompt": f"{rec['prompt_version']}:{rec['prompt_sha256_12']}",
                                 "human_verdict": "", "human_note": ""})
                    stats[f"run{run_id}_items"] += 1
                    stats[f"run{run_id}_{'accepted' if not reason else 'rejected'}"] += 1
                    if not reason:
                        keys[run_id].add((ship, n, it["kind"], norm(it["quote"]).lower(), norm(it["date_text"])))
            stats[f"run{run_id}_targets_not_returned"] += len(targets - seen)
    os.makedirs(OUT, exist_ok=True)
    fields = list(rows[0].keys()) if rows else ["run"]
    with open(os.path.join(OUT, "candidates.csv"), "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    summary = {"model": MODEL, "prompt_version": PROMPT_VERSION, "ships_with_residual": len(todo),
               "residual_clauses": sum(len(v[1]) for v in todo.values()), **dict(sorted(stats.items()))}
    if 1 in keys and 2 in keys:   # 安定性：検証を通った候補（艦・節・種類・引用・日付の文字列）の一致
        a, b = keys[1], keys[2]
        summary["stability"] = {"run1": len(a), "run2": len(b), "both": len(a & b),
                                "jaccard": round(len(a & b) / len(a | b), 3) if a | b else None,
                                "same_clause_and_kind": len({k[:3] for k in a} & {k[:3] for k in b}),
                                "jaccard_clause_and_kind": round(len({k[:3] for k in a} & {k[:3] for k in b}) /
                                                                 len({k[:3] for k in a} | {k[:3] for k in b}), 3)
                                if a | b else None}
    json.dump(summary, open(os.path.join(OUT, "llm_residual_summary.json"), "w"), ensure_ascii=False, indent=2)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


REVIEW = P.manual("llm_residual_review.csv")
REVIEW_FIELDS = ["key", "ship", "clause_no", "runs", "llm_kind", "llm_role", "llm_date_text", "effect_by_table", "quote",
                 "clause", "llm_note", "verdict", "kind", "role", "date_text", "new_name", "reason", "decided"]


def review_sheet():
    """③ 人の確認の記録。run1・run2 の検証を通った候補を、艦・節・種類・引用で1行にまとめて書き足す。
    既にある行（人の記入）は上書きしない。verdict：accept（そのまま採用）／modify（kind・role・date_text・new_name を直して採用）
    ／reject（不採用）。kind・role・date_text は LLM の値を初期値として入れておく"""
    rows = [r for r in csv.DictReader(open(os.path.join(OUT, "candidates.csv"), encoding="utf-8-sig"))
            if r["accepted_by_validation"]]
    merged = collections.OrderedDict()
    for r in rows:
        key = f"{r['ship']}|{r['clause_no']}|{r['kind']}|{norm(r['quote']).lower()}"
        m = merged.setdefault(key, {"key": key, "ship": r["ship"], "clause_no": r["clause_no"], "runs": set(),
                                    "llm_kind": r["kind"], "llm_role": r["role"], "llm_date_text": r["date_text"],
                                    "effect_by_table": r["effect"], "quote": r["quote"], "clause": r["clause"],
                                    "llm_note": r["note"], "verdict": "", "kind": r["kind"], "role": r["role"],
                                    "date_text": r["date_text"], "new_name": "", "reason": "", "decided": ""})
        m["runs"].add(r["run"])
    existing = []
    if os.path.exists(REVIEW):
        existing = list(csv.DictReader(open(REVIEW, encoding="utf-8-sig")))
    have = {r["key"] for r in existing}
    for r in existing:   # 既にある行の runs だけは更新する（2回目の実行で出たかどうか）
        if r["key"] in merged:
            r["runs"] = "+".join(sorted(merged[r["key"]]["runs"]))
    new = []
    for m in merged.values():
        if m["key"] not in have:
            m["runs"] = "+".join(sorted(m["runs"]))
            new.append(m)
    with open(REVIEW, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=REVIEW_FIELDS)
        w.writeheader()
        w.writerows(existing + new)
    print(f"{len(existing)} rows kept, {len(new)} rows added -> {REVIEW}")


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "run":
        lim = int(sys.argv[sys.argv.index("--limit") + 1]) if "--limit" in sys.argv else None
        ships = ship_filter(sys.argv[sys.argv.index("--ships") + 1]) if "--ships" in sys.argv else None
        run(int(sys.argv[2]), lim, ships)
    elif len(sys.argv) >= 2 and sys.argv[1] == "validate":
        validate()
    elif len(sys.argv) >= 2 and sys.argv[1] == "review-sheet":
        review_sheet()
    else:
        print(__doc__)
