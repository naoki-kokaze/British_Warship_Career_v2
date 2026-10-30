あなたは、イギリス海軍の艦の経歴（Winfield 2014 の1項目）を、CIDOC-CRM にもとづく知識グラフ（RDF、Turtle）にする担当です。原文を読み、下の「データの仕様」とオントロジーに従って、この艦の RDF を書いてください。

## 書くもの

下の「データの仕様」（v2 のデータの読み方）が、RDF の形の定義です。そこに書かれている種類の情報を、原文から過不足なく RDF にしてください。

- 艦（オントロジーの艦のクラス。ID は `myData:<vessel_id>`）、最初の名前と改名
- 建造の経過（発注・起工・進水・竣工など）と費用
- 寸法・トン数（§2.9）
- 経歴の出来事（§2.4 の種類。就役・退役・艤装・修理・予備役・港での任務・売却・解体・喪失・貸与・改名・改造など）と、その日付・金額・場所
- 状態の期間（`crm:E93_Presence`。§2.2 の2つの軸と §2.3 の続き方の決まり）。出来事との前後のつながり（`crm:P182`・`crm:P182i`）も
- 配属先（§2.10）と艦長の任命

## 書き方の決まり

- 接頭辞は次のものを使う：`:` = `<http://www.example.com/ontology/warship#>`、`crm:` = `<http://www.cidoc-crm.org/cidoc-crm/>`、`myData:` = `<http://www.example.com/myData/>`、`rdfs:`、`xsd:`、`sealit:` = `<http://www.sealitproject.eu/ontology/>`
- この艦のノードの ID には、必ず対象の艦の vessel_id を含める（§2.7。例 `myData:<vessel_id>_<日付8桁>_<種類>`、寸法は `myData:dimension_<vessel_id>_...`、時間の幅は `myData:ts_<vessel_id>_...`）。場所・相手などほかの艦と共有しうるノードは `myData:place_<名前>`・`myData:station_<名前>`・`myData:actor_<名前>` とする
- 出来事には、根拠になった原文の箇所を `:source_text` に原文のまま入れる。艦長名は `:officer_text` に原文のまま
- 日付は §2.5 のとおり（`crm:P4_has_time-span` の時間の幅に、`crm:P82a_begin_of_the_begin`・`crm:P82b_end_of_the_end` などを `xsd:date` で）。原文に日付がなければ日付を推測して補わない
- 原文の読みに迷った箇所や、OCR の崩れで値を決められない箇所には `:review_note` に理由を書いてよい
- オントロジーと CIDOC-CRM にない用語を作らない
- `:generated_by_rule` は書かない

## 出力

指定の JSON スキーマで返してください。

- `turtle`：この艦の RDF（Turtle。`@prefix` の宣言から書き、それだけで読み込めるもの）
- `notes`：原文の読みで迷った点や、仕様で表せなかった情報。なければ空文字

## データの仕様（v2 評価 アノテーション指示書 §2・§3）

{spec}

## オントロジー（warship_career_ontology_v2.ttl）

```turtle
{ontology}
```
