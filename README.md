# isucon-toolkit

ISUCON 用のスクリプトと手順書。

## 使い方

1. 競技開始後、[docs/runbook.md](docs/runbook.md) の手順に沿ってサーバーの状態を大会リポジトリへ取り込む。
2. `scripts/` のスクリプトを大会リポジトリのルートにコピーし、先頭の `per-contest settings` を書き換える。

| スクリプト | 用途 |
|---|---|
| `install-tools.sh <host>` | alp と pt-query-digest をインストールする |
| `deploy.sh <host> [branch]` | push 済みのブランチを pull し、設定配置・ビルド・再起動する |
| `logs.sh clear <host>` | ベンチマーク前にアクセスログとスロークエリログを空にする |
| `logs.sh analyze <host>` | ベンチマーク後にログを集計し、`logs/<timestamp>/` に保存する |
