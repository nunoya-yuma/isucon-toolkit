# isucon-toolkit

ISUCON 用のスクリプトと手順書。

## 新しい入口 `tk`（移行中）

`tk status`と**単一台の**`tk deploy`を追加しています。既存の`scripts/`・`contest-ops/`は残っており、まだ`tk`からは呼びません。[原則](docs/principles.md)・[構成](docs/design.md)・[タスク仕様](docs/tasks.md)を参照してください。

| 入口 | 副作用 | 成熟度 |
|---|---|---|
| `tk status [--detail] [台...\|@app]` | 実機は読取りだけ。手元の`runs/`へ記録 | 1：ローカル/mockで確認 |
| `tk deploy [--plan] <commit\|branch> [台\|@app]` | checkout・設定の配布・build・再起動。`--plan`は実機読取りだけ | 1：ローカル/mockで確認。実機試験は未実施 |

### 手元の準備

手元にはbash・Python 3.8以降・Git・SSHが必要です。実機はLinux、bash、Python 3.8以降、Git、systemd、パスワードなしの`sudo -n`が必要です。SSHの接続先とhost keyは事前に確認してください。`tk`はユーザー・鍵・SSH設定を変更しません。

大会repoの直下から実行します（toolkit自体は`tools/toolkit/`へ固定SHAで複写）。

```bash
cp tools/toolkit/templates/tk.env.example tk.env
# tk.envの台名・パス・unit・build・HTTP確認先を記入する
# .gitignoreに runs/ と tk.env と、実機の可変データを加える
tools/toolkit/tk status
tools/toolkit/tk deploy --plan feat/change contest-1
tools/toolkit/tk deploy feat/change contest-1
```

`tk.env`は信頼するローカルのshell設定です。秘密値は書かず、必要なら`BUILD_CMD`で実機の既存の環境ファイルをsourceします。現在のGitルートの`tk.env`を読み、`TK_CONFIG=/path/to/tk.env`でも指定できます。台名はName tagと同じSSH alias（ハイフン可）を使います。benchmark台は不要です。`origin`はチームの大会repoにしてください。

deploy時、feature branchは固定SHAを`origin`の同名branchへpushします。既定branchはpushせず、そのbranchの公開済み履歴に含まれるかだけを確認します。SHA入力も公開済みbranchから辿れるかの確認だけです。確認できなければ警告してSSH配送を続けます。

設定・操作の順序・終了コードは[タスク仕様](docs/tasks.md)が正です。初回はdeploy先を1台明示してください。

### 実機の準備（新規設置専用・1回）

アプリの場所は`APP_USER`所有のcloneとして先に用意します。元ファイルと、DB・lock・アップロードなどの動くデータを保全・列挙し、Gitの操作で消さないことを確認します。ここではclone化やデータ移動は自動化しません。

次は`APP_USER=isucon`、同名の既存groupの例です。台名・ユーザー・groupは実機に合わせてください。既存の状態領域を上書きせず、`tk`を実行していないときに行います。

```bash
ssh contest-1 'set -eu
sudo -n test ! -e /var/lib/tk
sudo -n test ! -e /var/lib/tk-recv.git
sudo -n install -d -m 0700 /var/lib/tk /var/lib/tk/ops
sudo -n install -m 0600 /dev/null /var/lib/tk/lock
sudo -n install -d -o isucon -g isucon -m 0750 /var/lib/tk-recv.git
sudo -n -u isucon git init --bare /var/lib/tk-recv.git
echo "OK: tk state and receiver created"'
```

### 道具なしの確認と復旧

```bash
ssh contest-1 sudo ls /var/lib/tk/ops/
ssh contest-1 sudo cat /var/lib/tk/ops/<操作ID>.json
tools/toolkit/tk status --detail contest-1
```

後続の人の変更がないことを確認してから、記録の`recovery`を読み、各コマンドを実行します。復旧は前SHAへのdetached checkoutで、branch名を自動では戻しません。詳細と適用条件は[タスク仕様のdeploy・復旧](docs/tasks.md#8-deploy)を参照してください。

### 検証と実装上の境界

```bash
python3 -m unittest discover -s tests -v
shellcheck tk lib/common.sh tasks/status.sh tasks/deploy.sh
```

2026-10-30、ローカルGit/HTTPとmock SSH/sudo/systemctlで確認（実装`67a2511`、レビュー修正後のSHAはPRに記載）。実機の権限・systemd・Docker・実際のSSH切断は未検証で、成熟度1です。

実装上の提案と初回の制限は[実装PR #13](https://github.com/nunoya-yuma/isucon-toolkit/pull/13)に記載しています。

## 既存の使い方（移行中も利用可能）

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
