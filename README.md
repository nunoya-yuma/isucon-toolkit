# isucon-toolkit

ISUCON 用のスクリプトと手順書。

## 使い方

1. 競技開始後、[docs/runbook.md](docs/runbook.md) の手順に沿ってサーバーの状態を大会リポジトリへ取り込む。
2. `scripts/` の中身を大会リポジトリのルートにコピーし、`toolkit.env`（大会ごとの設定。全スクリプトが読み込む）を書き換える。

| スクリプト | 用途 |
|---|---|
| `install-tools.sh <host>` | alp と pt-query-digest をインストールする |
| `deploy.sh <host> [branch]` | push 済みのブランチを pull し、設定配置（`server/` と `hosts/<host>/`）・`migrations/*.sql` の適用・ビルド・再起動する |
| `logs.sh clear <host> [db-host]` | ベンチマーク前にアクセスログとスロークエリログを空にする |
| `logs.sh analyze <host> [db-host]` | ベンチマーク後にログを集計し、`logs/<timestamp>/` に保存する |
| `profile.sh <host> [seconds]` | ベンチマーク中に Go アプリの pprof / fgprof を取り、`logs/<timestamp>/` に保存する |
| `final-check.sh <host>...` | 最終ベンチマークの前と再起動の後に、デプロイ状態・サービス・ログとプロファイラの停止・アプリの応答を確かめる |

## 練習環境

練習用のサーバーに T 系インスタンス（t2/t3/t3a/t4g）を使わない。CPU クレジットが尽きると性能が大きく絞られ、スコアが 0 になったり SSH が応答しなくなったりする。AWS の無料プランでも `c7i-flex.large` は選べた（2026-10 確認）。

過去問のイメージでは大会のドメインの TLS 証明書が期限切れになっていることがある（ISUCON14 は 2025-12 に失効）。サーバー内で HTTPS を検証して叩く処理（ISUCON14 の matcher など）は失敗するので、アプリを `http://localhost:<port>` で直接叩くように変える。

複数台を試すときは、同じ AMI・セキュリティグループでインスタンスを増やし、そのセキュリティグループに「同じグループからのすべての通信」を許可するルールを足す。新しいインスタンスのホスト鍵は、`aws ec2 get-console-output` に出るフィンガープリントと `ssh-keyscan` の結果を突き合わせて確かめられる。
