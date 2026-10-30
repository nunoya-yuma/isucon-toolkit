# isucon-toolkit

ISUCON 用のスクリプトと手順書。

## 新しい入口 `tk`（移行中）

`tk status`・`tk deploy`・`tk final-check`・`tk reboot`を追加しています。既存の`scripts/`・`contest-ops/`は残っており、まだ`tk`からは呼びません。[原則](docs/principles.md)・[構成](docs/design.md)・[タスク仕様](docs/tasks.md)を参照してください。

| 入口 | 副作用 | 成熟度 |
|---|---|---|
| `tk status [--detail] [台...\|@app]` | 実機は読取りだけ。手元の`runs/`へ記録 | 2：練習の実機で確認（2026-10-30） |
| `tk deploy [--plan] <commit\|branch> [台...\|@app]` | 指定順にcheckout・設定の配布・build・再起動。非成功で停止。`--plan`は実機読取りだけ | 単一台は2（`9778c81`）、複数台は1（ローカル/mockのみ） |
| `tk final-check [--detail] [台...\|@app]` | 実機は読取りだけ。手元の`runs/`へ記録 | 1：ローカル/mockのみ |
| `tk reboot [--plan] [台...\|@app]` | 指定順に1台ずつ再起動。boot IDの変化を確認できなければ停止。`--plan`は順序の表示だけ | 1：ローカル/mockのみ |

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

`BUILD_CMD`を決めたら、わざとコンパイルを失敗させたcommitで1回試してください。dockerのアプリでは、`docker compose build`がコンパイルしない作りがあります（起動時に`go run`するなど）。その場合、構文の誤りはbuildでは見つからず、`ready`の段まで進んでから失敗します。

deploy時、feature branchは固定SHAを`origin`の同名branchへpushします。既定branchはpushせず、そのbranchの公開済み履歴に含まれるかだけを確認します。SHA入力も公開済みbranchから辿れるかの確認だけです。確認できなければ警告してSSH配送を続けます。

設定・操作の順序・終了コードは[タスク仕様](docs/tasks.md)が正です。deployは対象を省くと`@app`を設定順に、rebootは全台を設定順に処理します。失敗や結果不明で止まったら、残りは接続せず`skipped`となります。続ける前に実機の状態を確認し、必要な台だけを指定してください。

### 最後の確認と再起動

```bash
tools/toolkit/tk final-check
tools/toolkit/tk reboot --plan contest-1 contest-2
tools/toolkit/tk reboot contest-1 contest-2
tools/toolkit/tk final-check
# 最終のbenchmarkは人がポータルから実行する
```

`final-check`は項目ごとに`OK`・`NG`・`未確認`を表示し、NGや未確認があれば終了1です。Gitのfetch・lock・設定変更は行いません。サービスの確認はapp役の`APP_SERVICE`とhost上の`nginx.service`・`mysql.service`に限定します。コンテナ内のnginx・MySQLは対象に含めません。nginxは行頭の`access_log`指令を走査する簡易確認で、contextの継承や条件式は解釈しません。設定本文は結果に出しません。

`FINAL_PROFILER_PORT`を設定すると、選んだ全台でそのポートの待受を確認します（空なら省略）。MySQLのログはrootの既存のローカル認証で読み、読めなければ未確認にします。

`reboot`は開始時のboot IDと要求を実機へ記録し、再接続でboot IDが変わってから同じ記録を完了にします。待機上限は`REBOOT_TIMEOUT`（既定300秒）。タイムアウト・返答の消失は成功とせず、記録の`running`を残します。再起動後のアプリ・DBなどは別の`final-check`で確認します。元のboot IDやメモリの状態には戻せません。接続できない台はコンソールなどで手動復旧してください。

時間切れの後は、`ssh <台> sudo cat /var/lib/tk/ops/<操作ID>.json`の開始時`boot_id`と、`ssh <台> cat /proc/sys/kernel/random/boot_id`を人が比べます。値が変わっていても、手動確認だけでは`running`の記録は変わらず、`final-check`のoperationはNGのままです。記録をそろえるためだけに再rebootせず、確認した結果をチームへ共有してください。

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

途中で止まった操作（killなど）の記録は、手で戻した後も`running`のまま残り、`status`は終了1のままです。戻した後に、同じcommitをもう一度`tk deploy`すると、完了の記録ができて終了0に戻ります。この再deployは、記録をそろえるだけでなく、buildとサービスの再起動をもう一度行います。

### 検証と実装上の境界

```bash
python3 -m unittest discover -s tests -v
shellcheck tk lib/common.sh tasks/*.sh
```

2026-10-30、ローカルGit/HTTPとmock SSH/sudo/systemctlで確認（実装`67a2511`、レビュー修正後のSHAはPRに記載）。

同日、main `9778c81`を練習の実機（ISUCON12予選のAMI、dockerで動くアプリ、ログインユーザーとアプリのユーザーが違う台）の1台で確認し、成熟度2としました。確かめたのは、dirtyの拒否・成功・起動の失敗とbuildの失敗からの手での復旧・同時のdeployのlock・buildを待つ間のkill・SSHの切断です（各1回）。設定のファイルを書いている途中（`apply`の段）のkill、複数台へのdeployは試していません。

実装上の提案と初回の制限は[実装PR #13](https://github.com/nunoya-yuma/isucon-toolkit/pull/13)に記載しています。

複数台deploy・final-check・rebootの追加と単一台処理の整理は、ローカルGit/HTTPとmock SSH/sudo/systemctlでのみ確認しています。この変更を含む実機試験は未実施です。

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
