# British_Warship_Career_v2

19世紀イギリス海軍の艦船の経歴を、知識グラフ（RDF）として記述するデータの第2版（v2）です。生成の工程と評価に用いたスクリプト、オントロジー、SHACL シェイプ、規則で生成した RDF、評価の結果を収録しています。

第1版（v1、LLM による生成）は [British_Warship_Career](https://github.com/naoki-kokaze/British_Warship_Career) にあります。

## 関連論文

小風尚樹・岩田晴登・小川潤・大向一輝「オントロジー準拠を指示したLLM生成知識グラフの品質評価：歴史研究者・計算機・エージェント型AIの協働による三角測量」『じんもんこん2026論文集』2026年12月（刊行予定）。

## 典拠資料と原文の扱い

艦船の経歴の記述は、以下の文献に依拠しています。

Winfield, Rif. *British Warships in the Age of Sail, 1817–1863: Design, Construction, Careers and Fates*. Seaforth Publishing, 2014.

**典拠文献の原文は、著作権上の理由により本リポジトリでは公開しません。** 公開版は `scripts/make_public_release_v2.py`（作成元のリポジトリにあり、本リポジトリには含みません）で作り、次の加工をしています。

- RDF の `:source_text`（各ノードの典拠となる原文の節）を削除しました。各ノードの ID は艦の ID で始まるので、原本の該当艦の記載と照合できます。
- CSV から、原文の節を含む列（`raw`・`context`・`clause`・`quote`・`examples` など）を削除しました。
- オントロジーで用語集の定義文を引いていた `rdfs:comment` は、出典の指示に置き換えました。
- 原文の連続する10語が公開版に残っていないことを機械的に検査しています。艦長名などの固有名詞、寸法の数字列、注記の短い一句は、事実または短い引用として残しています。

## 構成

フォルダの形は作成時のまま（`scripts/` から `../outputs`・`../sources` を読む）です。

| フォルダ | 内容 |
|---|---|
| `outputs/ontology_v2/` | オントロジーv2（CIDOC CRM・SeaLiT に基づく）と SHACL シェイプ3本 |
| `outputs/rdf_v2/` | 開発用269隻の RDF（定型部分 `header_v2.ttl`・経歴 `events_v2.ttl`）と SHACL の報告 |
| `outputs/eval_v2/rdf_v2/` | 評価用71隻の RDF と SHACL の報告 |
| `outputs/rules_v0/`・`rules_v01/`・`rules_v1/` | 規則で取り出した定型部分・寸法・出来事・状態の期間（記録の層） |
| `outputs/provenance_v2/` | RDF の出所の割合（規則・推測を含む規則・LLM） |
| `outputs/eval_v2/eval_v2_selection.csv` | 評価用の艦の選定結果 |
| `outputs/eval_v2/annotator_A_main30_20261024.csv` | 評価者Aによる本評価30隻の判定（コメントの列は削除） |
| `sources/manual/` | 人が記入した判断表（役割の判断、寸法の目視確認、LLM の候補の採否） |
| `scripts/` | 規則のパイプライン、v1 との比較、評価のスクリプト |
| `scripts/prompts/` | LLM に与えた指示（残りの節の読み取り、判定者、比較用の生成） |

## 再現の手順

入力の原文（`sources/v1/strata/*.xlsx`・`sources/eval_v2/strata/*.xlsx` の本文）は同梱していません。Winfield (2014) から各艦の記載を用意し、艦の ID と本文の形にすれば、規則の部分は決定論的に同じ出力になります。艦の ID と区分は v1 リポジトリの `strata/` にあります。

```bash
pip install rdflib pyshacl openpyxl
cd scripts
python3 extract_header_v0.py && python3 extract_dimensions_v01.py && python3 extract_events_v1.py
python3 build_presence_v1.py && python3 convert_header_v2.py && python3 convert_events_v2.py
python3 run_shacl_v2.py ../outputs/ontology_v2/shapes_events_v2.ttl out.csv ../outputs/rdf_v2/events_v2.ttl
# 評価用の艦は JINMON_DATASET=eval_v2 を付けて同じ順に実行する
```

LLM を使う段階（`llm_residual_v2.py`・`llm_judge_v2.py`・`llm_only_v2.py`）は、環境変数 `ANTHROPIC_API_KEY`（Gemini は `GEMINI_API_KEY`）が要ります。LLM の出力は実行のたびに変わりうるため、採用した候補は `sources/manual/llm_residual_review.csv` に記録し、規則の出力に統合しています（`merge_llm_events_v2.py`）。

スクリプト中のコメントは日本語で、作成時の判断の日付や記録への参照を含みます。評価の記録シートのうち、本リポジトリに収録していないもの（2人目の判定、LLM 判定者の明細、裁定の記録）を読むスクリプトは、そのままでは動きません。

## ライセンス

- コード（`scripts/`）：MIT License（`LICENSE`）
- データ・オントロジー（`outputs/`・`sources/manual/`）：[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)（`LICENSE-DATA`）

## プロジェクトメンバー

小風尚樹（国立歴史民俗博物館）、岩田晴登・小川潤・大向一輝（東京大学大学院）
