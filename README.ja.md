# ASTify

[English](README.md)

Tree-sitter の AST とローカル埋め込みモデルを組み合わせ、ソースコードや
ドキュメントからナレッジグラフを生成するツールです。API キーや AI トークンは
不要です。

Apex、JavaScript、TypeScript、TSX は Tree-sitter で構文解析します。その他の
言語はヒューリスティック解析、ドキュメントやメタデータは埋め込み、KeyBERT、
spaCy NER で処理します。

## インストール

Python 3.10 以上が必要です。

```bash
# 推奨
uv tool install astify --from git+https://github.com/arufian/ASTify

# または pip
pip install git+https://github.com/arufian/ASTify

# spaCy 英語モデル
python -m spacy download en_core_web_sm
```

Windows、macOS、Linux に対応しています。初回実行時は埋め込みモデルを
ダウンロードするため、通常より時間がかかります。

## 基本的な使い方

```bash
# detect → extract → build → report → html を一括実行
astify /path/to/project

# 各ステップを個別実行
astify detect .
astify extract .
astify build .
astify report .
astify html .

# グラフを検索
astify query "authentication flow"
astify query "data flow between services" --dfs
astify path "JWT" "Redis"
astify explain "AuthService"
```

## 大規模コードベース

ASTify 0.3.0 では、数千ファイルのリポジトリでグラフが爆発的に増えないよう、
次の制限を標準で適用します。

- 類似度エッジは各ファイルにつき上位 20 件まで
- 共通キーワードとエンティティは、全ファイル間のクリークではなく共有ハブとして表現
- 埋め込み、KeyBERT、spaCy をバッチ処理
- 小規模グラフのみ正確な betweenness centrality を計算
- 中規模グラフはサンプリング、大規模グラフはコミュニティ間ブリッジを使用
- 大規模 HTML はコミュニティ単位に自動集約
- 詳細グラフは単一巨大 JSON ではなく SQLite に保存

標準設定:

```bash
astify . --max-neighbors 20 --batch-size 32
```

メモリが少ない環境、または Defender/OneDrive の監視対象になっている Windows
ワークスペース:

```bash
astify . --max-neighbors 10 --batch-size 16 --no-viz
astify html .
```

高コスト処理を明示的に強制するオプション:

```bash
astify build . --full-analysis  # 正確な betweenness。大規模グラフでは非推奨
astify build . --full-json      # 詳細 graph.json を強制出力
astify html . --full-html       # 詳細 HTML を強制出力
```

## 出力

```text
astify-out/
├── astify.db          # 抽出結果と詳細クエリグラフの SQLite ストア
├── .semantic.json     # --json 指定時のみ生成する互換用 JSON
├── graph.json         # 安全なサイズの場合、または --full-json 指定時
├── graph-summary.json # 分析・可視化用の縮約グラフ
├── analysis.json      # コミュニティ、中心ノード、分析方式
├── GRAPH_REPORT.md    # 人が読める分析レポート
└── graph.html         # インタラクティブな可視化
```

大規模グラフで `graph.json` が省略されても、`astify query`、`path`、`explain`
は `astify.db` を自動的に読み込みます。

Graphify 互換 JSON が必要な場合:

```bash
astify extract . --json
astify extract . -o semantic.json
astify extract . --graphify-path graphify-out/.graphify_semantic.json
```

## エッジの信頼度

- `EXTRACTED`: Tree-sitter AST から取得した構造的な関係
- `HEURISTIC`: 非対応言語の構文パターンから推定した関係
- `INFERRED`: 埋め込み、キーワード、NER から推定した意味的な関係

`INFERRED` エッジは、正確な呼び出し元、定義、変更箇所の証拠として扱わないで
ください。正確な構造情報が見つからない場合は、ソース検索または言語サーバーで
確認してください。

## テスト

```bash
python -m pytest -q
```

テストスイートには、500 ファイルの高類似度コーパスと、5,000 コードファイルの
ビルド回帰テストが含まれています。

## ライセンス

MIT
