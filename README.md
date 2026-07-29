# AI trend digest

毎日決まった時刻(既定: JST 7:00)に、Claude Code / Anthropic / arXiv / Hacker News / Reddit
から新着情報を集め、Claude APIで日本語要約に変換し、Notionの「AIトレンド Inbox」データベースに
下書き(ステータス = 未読)として保存するパイプラインです。

## 構成

```
.github/workflows/ai-digest.yml   毎日のスケジュール実行
scripts/collect.py                 各ソースから新着だけを収集
scripts/summarize.py               Claude APIで日本語要約に変換
scripts/notion_push.py             Notionへ下書きとして書き込み
state/seen_ids.json                重複防止用の既読URL一覧(実行のたびに更新・コミットされる)
```

## セットアップ手順

1. このフォルダの中身を、GitHub Actionsを動かしたいリポジトリのルートにコピーする
   (既存のリポジトリに置く場合は `.github/workflows/ai-digest.yml` と
   `scripts/`, `state/`, `requirements.txt` をそのまま配置すればOK)

2. リポジトリの **Settings > Secrets and variables > Actions** で以下のSecretsを登録する

   | Secret名 | 内容 |
   |---|---|
   | `ANTHROPIC_API_KEY` | Anthropic Consoleで発行したAPIキー |
   | `NOTION_API_KEY` | Notionの Internal Integration トークン(後述) |
   | `NOTION_DATA_SOURCE_ID` | (任意) 未設定なら今回作成した「AIトレンド Inbox」を指す既定値を使用 |

3. Notion側で Internal Integration を作成し、**「AIトレンド Inbox」データベースをそのIntegrationと共有(Share)**
   しておく。これを忘れると、トークンが正しくてもAPIが403エラーで失敗する。

4. まずは `workflow_dispatch` (Actionsタブの "Run workflow" ボタン) で手動実行し、
   Notionに下書きが正しく作成されることを確認してから、スケジュール実行に任せる。

## カスタマイズ

- **実行時刻**: `.github/workflows/ai-digest.yml` の `cron` を変更(UTC基準)。
  GitHubのscheduled cronは負荷状況により数分〜十数分遅れることがある。
- **収集ウィンドウ**: `collect.py` の `LOOKBACK_HOURS`(既定30時間)
- **キーワードフィルタ**: `collect.py` の `KEYWORDS`(arXivとr/singularityの絞り込みに使用)
- **要約モデル**: `summarize.py` の `MODEL`(既定 `claude-haiku-4-5-20251001`。
  分析の質を上げたい場合は `claude-sonnet-5` に変更)

## 既知の制約

- Anthropic公式ニュース(anthropic.com/news)は公式RSSがないため、HTMLの軽量スクレイピングに
  頼っている。サイト構造が変わると取得できなくなることがあるが、その場合はログに警告が出るだけで
  パイプライン全体は止まらない。
- 重複防止は `state/seen_ids.json` に記録したURLのみで判定している。このファイルをリセットすると
  同じ記事が再度Notionに作成されることがある(手動で消せば問題ない)。
