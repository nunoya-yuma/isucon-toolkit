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

## 練習環境

練習用のサーバーに T 系インスタンス（t2/t3/t3a/t4g）を使わない。CPU クレジットが尽きると性能が大きく絞られ、スコアが 0 になったり SSH が応答しなくなったりする。AWS の無料プランでも `c7i-flex.large` は選べた（2026-10 確認）。
