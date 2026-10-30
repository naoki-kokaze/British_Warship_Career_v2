"""規則パイプラインの入力・出力の場所を、データセットごとに切り替える（2026-10-08）

環境変数 JINMON_DATASET で選ぶ。
    dev（既定）  開発用269隻。入力 ../sources/v1/strata、出力 ../outputs/<sub>（従来どおり）
    eval_v2      評価用の新しい艦（select_eval_ships_v2.py の選定）。入力 ../sources/eval_v2/strata、
                 出力 ../outputs/eval_v2/<sub>

評価用でも共有するもの（規則は開発用で固めたものをそのまま使う）
    - 役割の判断表 ../sources/manual/role_seagoing_judgement.csv（評価用で新しい役割が出ても書き足さない）
    - オントロジ・シェイプ ../outputs/ontology_v2/
評価用で別にするもの（人の記入）
    - LLM 候補の確認の記録、寸法の目視確認 → ../sources/manual/eval_v2/
    - LLM の候補で見つかった新しい役割の判断 → ../sources/manual/eval_v2/role_judgement_llm_additions.csv
      （LLM の候補の検証・統合でだけ読む。規則は読まないので、規則の結果は本評価のデータで変わらない。2026-10-14）

使い方（例）: JINMON_DATASET=eval_v2 python3 extract_header_v0.py
"""
import os

HERE = os.path.dirname(os.path.abspath(__file__))
DATASET = os.environ.get("JINMON_DATASET", "dev")
if DATASET not in ("dev", "eval_v2"):
    raise SystemExit(f"unknown JINMON_DATASET: {DATASET} (dev / eval_v2)")

_EVAL = DATASET == "eval_v2"
STRATA = os.path.join(HERE, "../sources/eval_v2/strata" if _EVAL else "../sources/v1/strata")
ROLE_JUDGEMENT = os.path.join(HERE, "../sources/manual/role_seagoing_judgement.csv")
# LLM の候補の検証・統合で読む判断表（評価用では共有の判断表＋評価用の追加分。無ければ共有の判断表だけ）
LLM_ROLE_TABLES = [p for p in (ROLE_JUDGEMENT, os.path.join(HERE, "../sources/manual/eval_v2/role_judgement_llm_additions.csv"))
                   if p == ROLE_JUDGEMENT or (_EVAL and os.path.exists(p))]
ONTOLOGY_DIR = os.path.join(HERE, "../outputs/ontology_v2")


def out(sub):
    """出力のフォルダ（例 out("rules_v1")）"""
    return os.path.join(HERE, "../outputs/eval_v2" if _EVAL else "../outputs", sub)


def manual(name):
    """人の記入のファイル（判断表を除く）"""
    return os.path.join(HERE, "../sources/manual/eval_v2" if _EVAL else "../sources/manual", name)
