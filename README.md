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

`tk.env`は信頼するローカルのshell設定です。秘密値を直接書かず、必要なら`BUILD_CMD`から実機の既存の環境ファイルをsourceしてください。台名は運営のName tagと同じSSH aliasを使います。ハイフンを含む英数字・`.`・`_`を許し、空白やshellの特殊文字は拒否します。benchmark台の設定は不要です。設定は現在のGitルートの`tk.env`から読みます。別の場所なら`TK_CONFIG=/path/to/tk.env`で指定できます。

入力branchは開始時に一度だけSHAに解決します。手元の未commitファイルは配りません。Gitの`origin`はチームの大会repoにしてください。公開用ref `refs/heads/tk/<操作ID>`へSHAをpushし、失敗すれば警告してSSH配送を続けます。実機の受信用bare repoへは`refs/tk/incoming/<操作ID>`をpushし、lock内でfetch・SHA照合・checkoutします。複数のapp台が設定されているときは、deploy先を1台明示してください。

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

### 状態と復旧

`status`は台ごとに10秒まで並行に確認し、届かない台は`unconfirmed`とします。`match`はcheckoutと最後の成功SHAの一致だけです。サービス・HTTPは別の列で表示します。記録なし、dirty、不一致、running、応答NGなどは終了1になります。app以外の台ではHTTP確認を行いません。GitHubの到達可能性や、Git管理外の設定の実物の一致は判定しません。

実機の記録は`/var/lib/tk/ops/<操作ID>.json`、元の設定は同じ操作IDの`backup/`です。PythonのJSONをcatできるよう、整形して保存しています。索引や常駐プロセスはありません。最新の記録は実機で書いた時刻から選び、同時刻なら候補をそのまま表示します。`lock.json`は最後の取得記録で、現在もlock中である証明ではありません。

```bash
tools/toolkit/tk status --detail contest-1
ssh contest-1 sudo ls /var/lib/tk/ops/
ssh contest-1 sudo cat /var/lib/tk/ops/<操作ID>.json
```

失敗時は、**後続の人の変更がないことを確かめてから**、JSONの`recovery`の各行を読んで実行します。完成したbackupだけを戻し、新規ファイルを削除し、前のSHAへdetached checkoutし、元の稼働状況に応じてサービスをrestart/stopするコマンドです。branch名は自動で戻しません。新しく作った空ディレクトリ、Git objects、Docker等のbuild cacheは残ることがあります。

`server/`と`hosts/<台>/`は、絶対パスに対応する通常ファイルだけを扱います。台別が共通設定を上書きします。アプリのフォルダ配下を`server/`から重ねて配ることは拒否します。設定の手動変更はbackupし、上書きします。ファイル削除・symlinkの配布・DDL/migrationsは実行しません。`--plan`は宛先と旧/新hashを表示し、設定の内容や秘密値は表示しません。

nginxは構文検査後reload、MySQLと変更したsystemd unitは稼働しているものだけrestartします。最後にappをbuild・restartし、`READY_HOST`を付けたHTTP確認を待ちます。無効化されたappのunitはpreflightで拒否します。buildコマンドはAPP_DIRで実行されます。`--plan`と実行の間の変更は実行時に読み直します。直接SSHなど、同じlockを使わない操作との衝突は防ぎません。

単一台deployの終了コードは、0＝成功、1＝変更後の失敗または結果不明、2＝設定/引数誤り、3＝変更前の拒否です。SSH切断時に変更を推定せず、手元へ`unknown`を残します。長時間のbuildには実機側600秒、SSH全体には900秒の上限があります。途中終了で`running`が残った場合は、人が記録と実機を調べます。

### 実装と検証

入口と設定読込みはbash、JSON・Gitの結果の整理・退避・HTTP確認はPython標準ライブラリです。順序が読める`lib/remote.py`が実機側の単一台deployを担当し、汎用の状態遷移エンジンは作っていません。lockはPythonの`fcntl.flock`を使い、Linuxの`flock`コマンドと同じlockに協調します。

```bash
python3 -m unittest discover -s tests -v
shellcheck tk lib/common.sh tasks/status.sh tasks/deploy.sh
```

2026-10-30、実装commit `67a2511`をローカルGit・HTTPとmock SSH/sudo/systemctlで確認。成功・未commit保護・build失敗・途中中断・部分backup・同時deploy・同一SHAのready失敗・`--plan`の無変更を確認しています。実機の権限・systemd・SSH切断やDockerの起動は未検証で、実機試験後に成熟度2へ上げます。

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
