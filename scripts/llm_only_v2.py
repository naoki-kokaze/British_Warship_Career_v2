"""比較用（案B）：規則を通さず、LLM だけで v2 の RDF を書かせる（2026-10-19）

方針（2026-10-19 ユーザー承認。docs/jinmoncom2026_llm_only_baseline_and_qa_20261019.md §2）
    - 本評価と同じ30隻（eval_v2_main_order.csv の必須・追加）。規則とLLMの違いだけを比べる（オントロジー・判定基準は同じ）
    - LLM に渡すのは院生に渡しているのと同じ情報：指示書 §2「データの読み方」・§3「略語」、v2 オントロジー、原文。
      §4 以降の判定基準と、規則の対応表は渡さない（渡すと「規則を文章で渡しただけ」になる）
    - LLM には持てる力を出させる。生成のモデルは2つ（10/20 ユーザー承認）：
        gemini-4-argon（本体。判定者 Claude が自分の出力を判定する偏りを避ける。安定版で再現できる）、
        claude-opus-5-5（補助。effort high。LLM の残り部分と同じモデル）。gemini-2.5-pro（v1 と同じモデル）は使えれば追加
      Gemini は思考の量・temperature を既定のまま使い、使った思考のトークン数を記録する（SDK 1.47 は思考の上限しか指定できない）
    - 判定は llm_judge_v2.py に、v2 と同じ形のメッセージで渡す（どちらの出力かは判定者に知らせない）
    - 再現性：モデル ID・プロンプトの版・仕様とオントロジーのハッシュを記録し、生の応答を保存する。
      RDF は保存した応答から決定論的に作る（build）。原文は生の応答に保存しない

使い方（サンドボックスの外で。API の認証情報が必要：Claude は ANTHROPIC_API_KEY、Gemini は GEMINI_API_KEY）
    JINMON_DATASET=eval_v2 python3 llm_only_v2.py models                          # 使える Gemini のモデル ID を一覧する
    JINMON_DATASET=eval_v2 python3 llm_only_v2.py show SL3_9081                   # API を呼ばずに入力の大きさを確かめる
    JINMON_DATASET=eval_v2 python3 llm_only_v2.py run 1 --model gemini-4-argon    # 30隻。保存済みの艦は呼ばない（再開できる）
    JINMON_DATASET=eval_v2 python3 llm_only_v2.py build 1 --model gemini-4-argon  # 応答から RDF を作り、読み込めるか・用語・ID を検査する
    --ships SL3_9081 で1隻だけ。--model の既定は claude-opus-5-5
    判定：JUDGE_RDF_DIR=../outputs/eval_v2/llm_only_v2/<モデル>/rdf_run1 JUDGE_OUT=../outputs/eval_v2/llm_only_v2/<モデル>/judge \
          JINMON_DATASET=eval_v2 python3 llm_judge_v2.py run 2 --ships main

入力: ../docs/jinmoncom2026_annotation_guideline_v2_20261008.md（§2・§3）、../outputs/ontology_v2/warship_career_ontology_v2.ttl、
      prompts/llm_only_v2.md、原文（STRATA の text 列）、eval_v2_main_order.csv
出力: ../outputs/eval_v2/llm_only_v2/<モデル>/raw/run<N>/<艦>.json、rdf_run<N>/events_v2.ttl・header_v2.ttl、build_report_run<N>.csv
依存: anthropic、google-genai（1.47.0 で確認）、rdflib、openpyxl
"""
import csv
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import dataset_paths as P
from llm_judge_v2 import GUIDELINE, ONTOLOGY, read, selection, sha12, ship_filter, source_text

PROMPT = os.path.join(HERE, "prompts/llm_only_v2.md")
OUT_ROOT = P.out("llm_only_v2")
MODEL = "claude-opus-5-5"   # --model で切り替える。gemini で始まるものは Gemini API
EFFORT = "high"             # Claude のみ
MAX_TOKENS = 32000          # Claude：打ち切られたら 1.75 倍で1回だけ再試行
GEMINI_MAX_TOKENS = 65536   # モデルの出力の上限（output_token_limit）がこれより小さければ、そちらに合わせる（gemini-4-argon は 32768）
PROMPT_VERSION = "llm_only_v2_1"
SCHEMA = {
    "type": "object",
    "properties": {"turtle": {"type": "string"}, "notes": {"type": "string"}},
    "required": ["turtle", "notes"],
    "additionalProperties": False,
}
WARSHIP = "http://www.example.com/ontology/warship#"
MYDATA = "http://www.example.com/myData/"


def spec():
    """指示書の §2・§3（「## 2.」から「## 4.」の前まで）"""
    text = read(GUIDELINE)
    return text[text.index("## 2. "):text.index("## 4. ")].strip()


def system_text():
    return read(PROMPT).replace("{spec}", spec()).replace("{ontology}", read(ONTOLOGY))


def user_message(ship, sel, text):
    return (f"対象の艦: {ship}（{sel.get('name', '')}、系統 {sel.get('group', '')} {sel.get('group_name', '')}）\n"
            f"vessel_id: {ship}\n\n"
            f"## 原文（Winfield 2014、OCR のテキスト）\n\n```\n{text}\n```\n\n"
            "データの仕様とオントロジーに従ってこの艦の RDF を書き、指定の JSON スキーマで返してください。")


def show(ship):
    system = system_text()
    text = source_text(ship) or ""
    msg = user_message(ship, selection().get(ship, {}), text)
    print(f"system: {len(system)} 文字（仕様 {sha12(spec())}・オントロジー {sha12(read(ONTOLOGY))}）")
    print(f"user: {len(msg)} 文字（原文 {len(text)} 文字）")


def out_dir(model):
    return os.path.join(OUT_ROOT, model)


def models():
    from google import genai
    client = genai.Client()   # 変数に保持する（Client().models.list() と書くと、一覧の途中でクライアントが閉じられる）
    for m in client.models.list():
        if "generateContent" in (m.supported_actions or []):
            print(m.name.replace("models/", ""), "|", m.display_name, "| in", m.input_token_limit, "out", m.output_token_limit)


def call_gemini(client, model, system, msg, max_tokens):
    """1隻分を Gemini で生成する。返り値は記録に入れる dict（output_text・stop_reason・usage など）"""
    import logging
    from google.genai import types
    # 応答に思考の署名（thought_signature）が付くたびに出る「本文だけを返す」という警告を止める（本文の取り出しには影響しない）
    logging.getLogger("google_genai.types").setLevel(logging.ERROR)
    for attempt in range(4):
        try:
            resp = client.models.generate_content(
                model=model, contents=msg,
                config=types.GenerateContentConfig(system_instruction=system, max_output_tokens=max_tokens,
                                                   response_mime_type="application/json", response_json_schema=SCHEMA))
            break
        except Exception as e:   # 429・503 など。4回失敗したら諦める
            msg_e = str(e)
            print(f"  retry {attempt + 1}: {msg_e[:1500]}", file=sys.stderr)
            if "limit: 0" in msg_e or "NOT_FOUND" in msg_e:   # 利用枠が 0、モデルの提供終了（gemini-2.5-pro は新規利用者に提供終了、10/20）：待っても直らない
                return None
            time.sleep(30 * (attempt + 1))
    else:
        return None
    cand = resp.candidates[0] if resp.candidates else None
    finish = str(cand.finish_reason) if cand else "no candidate"
    u = resp.usage_metadata
    return {"served_model": resp.model_version, "effort": "default", "max_tokens": max_tokens,
            "stop_reason": "end_turn" if finish.endswith("STOP") else finish, "finish_reason_raw": finish,
            "output_text": resp.text or "",
            "usage": {"input_tokens": u.prompt_token_count, "output_tokens": u.candidates_token_count,
                      "thoughts_tokens": u.thoughts_token_count, "cache_read_input_tokens": u.cached_content_token_count}}


def run(run_id, ships, model=MODEL):
    gemini = model.startswith("gemini")
    if gemini:
        from google import genai
        client = genai.Client()
        limit = client.models.get(model=model).output_token_limit
        gemini_max = min(GEMINI_MAX_TOKENS, limit or GEMINI_MAX_TOKENS)
        print(f"{model}: max_output_tokens {gemini_max}（モデルの上限 {limit}）")
    else:
        import anthropic
        client = anthropic.Anthropic()
    sel = selection()
    system = system_text()
    meta = {"prompt_version": PROMPT_VERSION, "prompt_sha256_12": sha12(read(PROMPT)),
            "spec_sha256_12": sha12(spec()), "ontology_sha256_12": sha12(read(ONTOLOGY)),
            "system_sha256_12": sha12(system)}
    raw_dir = os.path.join(out_dir(model), "raw", f"run{run_id}")
    os.makedirs(raw_dir, exist_ok=True)
    done = 0
    for ship in sorted(ships):
        path = os.path.join(raw_dir, f"{ship}.json")
        if os.path.exists(path):
            continue
        text = source_text(ship)
        if text is None:
            print(f"{ship}: no source text", file=sys.stderr)
            continue
        msg = user_message(ship, sel.get(ship, {}), text)
        if gemini:
            got = call_gemini(client, model, system, msg, gemini_max)
            if got is None:
                print(f"{ship}: failed after retries", file=sys.stderr)
                continue
            record = {"ship": ship, "run": run_id, "requested_model": model, **got, **meta,
                      "source_sha256_12": sha12(text), "time": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
            json.dump(record, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
            done += 1
            print(f"{ship}: {record['stop_reason']} ({got['usage']['input_tokens']}+{got['usage']['output_tokens']} tokens, "
                  f"thoughts {got['usage']['thoughts_tokens']})")
            continue
        max_tokens, resp = MAX_TOKENS, None
        for attempt in range(4):
            try:
                # max_tokens が大きいと、SDK は10分を超えうる呼び出しにストリーミングを求める。受け取った最終の応答は create と同じ
                with client.messages.stream(
                    model=model,
                    max_tokens=max_tokens,
                    system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral", "ttl": "1h"}}],
                    output_config={"effort": EFFORT, "format": {"type": "json_schema", "schema": SCHEMA}},
                    messages=[{"role": "user", "content": msg}],
                ) as stream:
                    resp = stream.get_final_message()
            except anthropic.RateLimitError:
                time.sleep(30 * (attempt + 1))
                continue
            except anthropic.APIConnectionError:
                time.sleep(10 * (attempt + 1))
                continue
            if resp.stop_reason == "max_tokens" and max_tokens == MAX_TOKENS:
                max_tokens = int(MAX_TOKENS * 1.75)
                continue
            break
        if resp is None:
            print(f"{ship}: failed after retries", file=sys.stderr)
            continue
        out_text = next((b.text for b in resp.content if b.type == "text"), "")
        record = {"ship": ship, "run": run_id, "requested_model": model, "served_model": resp.model, "effort": EFFORT,
                  "max_tokens": max_tokens, "stop_reason": resp.stop_reason, **meta,
                  "source_sha256_12": sha12(text), "output_text": out_text,
                  "usage": {"input_tokens": resp.usage.input_tokens, "output_tokens": resp.usage.output_tokens,
                            "cache_read_input_tokens": getattr(resp.usage, "cache_read_input_tokens", None),
                            "cache_creation_input_tokens": getattr(resp.usage, "cache_creation_input_tokens", None)},
                  "time": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
        json.dump(record, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        done += 1
        print(f"{ship}: {resp.stop_reason} ({resp.usage.input_tokens}+{resp.usage.output_tokens} tokens, "
              f"cache read {record['usage']['cache_read_input_tokens']})")
    print(f"run{run_id}: {done} ships generated")


def defined_terms():
    from rdflib import Graph
    g = Graph().parse(ONTOLOGY)
    return {str(s) for s in g.subjects() if str(s).startswith(WARSHIP)}


def build(run_id, ships, model=MODEL):
    """保存した応答から RDF を作る。艦ごとに、読み込めるか・オントロジーにない : の用語・艦の ID を含まないノードを記録する。
    読み込めない艦は RDF に入れない（判定者には空の RDF が渡る＝軸1の問題として現れる）"""
    from rdflib import Graph, URIRef
    raw_dir = os.path.join(out_dir(model), "raw", f"run{run_id}")
    rdf_dir = os.path.join(out_dir(model), f"rdf_run{run_id}")
    os.makedirs(rdf_dir, exist_ok=True)
    known = defined_terms()
    merged = Graph()
    report = []
    for ship in sorted(ships):
        path = os.path.join(raw_dir, f"{ship}.json")
        if not os.path.exists(path):
            report.append({"ship": ship, "status": "no response"})
            continue
        rec = json.load(open(path, encoding="utf-8"))
        row = {"ship": ship, "stop_reason": rec["stop_reason"], "output_tokens": rec["usage"]["output_tokens"]}
        try:
            out = json.loads(rec["output_text"])
            g = Graph().parse(data=out["turtle"], format="turtle")
        except Exception as e:   # JSON か Turtle が壊れている
            row.update(status="parse error", detail=str(e)[:200])
            report.append(row)
            continue
        terms = {str(x) for t in g for x in t if isinstance(x, URIRef) and str(x).startswith(WARSHIP)}
        nodes = {str(s)[len(MYDATA):] for s in g.subjects() if isinstance(s, URIRef) and str(s).startswith(MYDATA)}
        foreign = [n for n in nodes if ship not in n and not (re.match(r"(place|station|actor|currency|unit)_", n) or n == "royal_navy")]
        row.update(status="ok", triples=len(g), nodes=len(nodes), undeclared_terms=" ".join(sorted(terms - known)),
                   nodes_without_ship_id=" ".join(sorted(foreign)), notes=out.get("notes", "")[:300])
        for p, ns in g.namespaces():
            merged.bind(p, ns, override=False)
        for t in g:
            merged.add(t)
        report.append(row)
    merged.serialize(os.path.join(rdf_dir, "events_v2.ttl"), format="turtle")
    Graph().serialize(os.path.join(rdf_dir, "header_v2.ttl"), format="turtle")   # 判定者は2つのファイルを読むので空の方も作る
    fields = ["ship", "status", "stop_reason", "output_tokens", "triples", "nodes", "undeclared_terms",
              "nodes_without_ship_id", "notes", "detail"]
    rp = os.path.join(out_dir(model), f"build_report_run{run_id}.csv")
    with open(rp, "w", encoding="utf-8-sig", newline="") as fp:
        w = csv.DictWriter(fp, fieldnames=fields)
        w.writeheader()
        w.writerows({k: r.get(k, "") for k in fields} for r in report)
    ok = sum(r.get("status") == "ok" for r in report)
    print(f"{ok}/{len(report)} ships parsed, {len(merged)} triples -> {rdf_dir}; report {rp}")
    for r in report:
        if r.get("status") != "ok" or r.get("undeclared_terms") or r.get("nodes_without_ship_id"):
            print(f"  {r['ship']}: {r.get('status')} {r.get('undeclared_terms', '')} {r.get('nodes_without_ship_id', '')[:120]}")


if __name__ == "__main__":
    args = sys.argv[1:]
    ships = ship_filter(args[args.index("--ships") + 1]) if "--ships" in args else ship_filter("main")
    model = args[args.index("--model") + 1] if "--model" in args else MODEL
    if args[:1] == ["models"]:
        models()
    elif args[:1] == ["show"] and len(args) > 1:
        show(args[1])
    elif args[:1] == ["run"] and len(args) > 1:
        run(int(args[1]), ships, model)
    elif args[:1] == ["build"] and len(args) > 1:
        build(int(args[1]), ships, model)
    else:
        print(__doc__)
