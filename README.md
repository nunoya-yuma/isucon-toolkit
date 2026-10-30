# isucon-toolkit

ISUCONの競技サーバーを、手元からSSHで操作する道具と手順書。入口は`tk`（`status`・`deploy`・`final-check`・`reboot`）。実機の変更は、実機の上の記録（`/var/lib/tk/ops/`）に残り、別の人が後から追える。

## 文書の地図

| 読む人 | 文書 | 中身 |
|---|---|---|
| 使う人 | この README | 準備・基本の操作・結果の読み方・失敗したときの調査・成熟度 |
| 使う人 | [docs/runbook.md](docs/runbook.md) | 競技の流れ（開始から終わりまで）を時間の順に |
| 直す人 | [docs/principles.md](docs/principles.md) | 原則とPRのチェックリスト |
| 直す人 | [docs/design.md](docs/design.md) | 構成と、選んだ理由・後に回したもの |
| 直す人 | [docs/tasks.md](docs/tasks.md) | 振る舞いの正本（記録の形・段・終了コード） |
| 直す人 | `lib/`・`tasks/`・`tests/` | 実装と、直したことの確かめ方 |

1つの事実は1か所に書き、ほかはリンクする。成熟度と動作実績は、下の表だけに書く。

## 成熟度

0＝書きかけ、1＝手元（mock）で動いた、2＝練習の実機で動いた、3＝大会を変えても設定だけで動いた（[原則8](docs/principles.md)）。

| 入口 | 副作用 | 成熟度と根拠 |
|---|---|---|
| `tk status [--detail] [台...\|@app]` | 読取りだけ | 2：練習の実機（2026-10-30、`9778c81`・`0833582`） |
| `tk deploy [--plan] <commit\|branch> [台...\|@app]` | checkout・設定の配布・build・再起動。`--plan`は読取りだけ | 2：練習の実機（2026-10-30）。1台（`9778c81`）では成功・起動とbuildの失敗からの手での復旧・同時のdeploy・kill・SSHの切断、2台（`0833582`）では成功と、途中の台の失敗で残りを`skipped`にすること |
| `tk final-check [--detail] [台...\|@app]` | 読取りだけ | 2：練習の実機3台（2026-10-30、`0833582`）。再起動の後に、1台のappが起動していないことを検出した |
| `tk reboot [--plan] [台...\|@app]` | 1台ずつ再起動 | 2：練習の実機3台を順に（2026-10-30、`0833582`） |
| runbookの`init`の手順 | アプリのフォルダのGit化 | 2：練習の実機で、一時の場所に対して（2026-10-30、`0833582`の手順） |
| `scripts/`（移行前の入口） | 各scriptの説明を参照 | 2：ISUCON14の練習（2026-10-28、1人） |
| `contest-ops/`の`inspect`・`snapshot` | 読取りだけ | 2：練習の実機3台（2026-10-29） |
| `contest-ops/`の`nginx-plan`・`nginx-apply`・`nginx-restore`・`reboot` | 変える（nginxは戻せる） | 2：練習の実機（2026-10-30） |

復旧時に旧ソースをbuildし直す変更は、ローカル/mockでのみ確認（成熟度1）。この変更を含む実機試験は未実施。

試していないこと：設定のファイルを書いている途中の`deploy`のkill、3台以上への`deploy`、dockerを使わないアプリ。当日に、試していない形に当たったら、まず1台で試し、結果を1行で共有してから広げる。

## 準備

新しい大会では、[runbookの1〜2章](docs/runbook.md#2-保全とgit化)の順に進める（大会repoは、1台目のアプリのcommitを手元へcloneして作る）。ここに書くのは、そのうちの`tk`の準備（runbookの2章の5）。

**手元**：bash・Python 3.8以降・Git・SSH。**実機**：Linux・bash・Python 3.8以降・Git・systemd・パスワードなしの`sudo -n`。`tk`は、ユーザー・鍵・SSHの設定を変えない。

1. 大会repoの`tools/toolkit/`に、このrepoを固定SHAで複写し、`tools/toolkit/SOURCE.md`に元のrepoとSHAを1行書く。
2. 大会repoの直下に、`templates/`のひな形から`tk.env`（`tk.env.example`から）・`.gitignore`（`gitignore.example`から）・`README.md`を作る。`tk.env`の項目の意味は[tasks.mdの2章](docs/tasks.md#2-設定tkenv)。`tk.env`は秘密値を入れずにcommitし、チーム全員が同じものを使う。`.gitignore`には、秘密値と実機の動いているデータを足す。
3. 台の名前は、運営のEC2のNameタグと同じ文字列のSSHのaliasにする。手で書く例（`~/.ssh/config`）：

```text
Host <Nameタグ>
  HostName <公開IP>
  User ubuntu
  HostKeyAlias <インスタンスID>   # IPが変わってもhost keyの照合を保つ
```

   最初の接続でhost keyを受け入れる前に、`aws ec2 get-console-output --instance-id <ID>`のfingerprintと照らす。
4. 各台に、記録の領域と受信用repoを1回だけ作る（`APP_USER=isucon`の例）。

```bash
ssh <台> 'set -eu
sudo -n test ! -e /var/lib/tk
sudo -n test ! -e /var/lib/tk-recv.git
sudo -n install -d -m 0700 /var/lib/tk /var/lib/tk/ops
sudo -n install -m 0600 /dev/null /var/lib/tk/lock
sudo -n install -d -o isucon -g isucon -m 0750 /var/lib/tk-recv.git
sudo -n -u isucon git init --bare /var/lib/tk-recv.git
echo "OK: tk state and receiver created"'
```

`BUILD_CMD`の確かめ方と、初期構築の完了の判定は、runbookの2章の8〜10。

## 基本の操作

大会repoの直下から実行する。

```bash
tools/toolkit/tk status                              # 全台の状態
tools/toolkit/tk deploy --plan feat/x                # 配る前に、宛先と差分を見る（読取りだけ）
tools/toolkit/tk deploy feat/x                       # app役の全台へ、1台ずつ
tools/toolkit/tk deploy feat/x <台>                  # 1台だけ
tools/toolkit/tk final-check                         # 最後の確認（読取りだけ）
tools/toolkit/tk reboot --plan <台> <台>              # 再起動の順番を見る
tools/toolkit/tk reboot <台> <台>                     # 1台ずつ再起動
```

- `deploy`はcommitからだけ配る。作業ツリーの未commitの変更は配らない。feature branchは、決めたSHAをGitHubの同名のbranchへpushする。既定のbranchはpushしない。
- 最終のbenchmarkは、人がポータルから流す。`tk`はbenchmarkの台を使わない。

## 結果の読み方

最後の1行が要約で、そのままチームのDiscordの決めた場所へ貼れる（[原則7](docs/principles.md)）。

```text
tk deploy 20261030T031500Z-deploy-3fa2 sha=3bdcc40 isu1=ok@done isu2=failed@restart isu3=skipped
```

| 台の結果 | 意味 |
|---|---|
| `ok@done` | 最後まで成功 |
| `refused@<段>` | 変更を始める前に止まった（実機の稼働中のものは変わっていない） |
| `failed@<段>` | 変更を始めた後に失敗した。戻し方は下を見る（`restart`の段は、設定のreload・build・appの再起動を含む） |
| `unknown@<段>` | 結果が分からない（途中で接続が切れたなど）。`tk status`で実機を見る |
| `skipped` | 前の台で止まったので、接続していない |

終了コードは、全台`ok`＝0、全台が変更前に止まった＝3、使い方の誤り＝2、それ以外＝1（[tasks.mdの6章](docs/tasks.md#6-終了コードと1行の要約)）。

`tk status`の「一致」は、アプリのrepoのcheckoutが最後に成功したdeployと同じ、という意味だけ。配った設定やDBの実物が正しいことまでは見ていない。

`final-check`は項目ごとに`OK`・`NG`・`未確認`で、`未確認`は「確かめられなかった」でありNGとは別。サービスの項目は、自動起動が有効（enabled）なのに止まっているものをNGにする（止まっていて無効のものは、NGにしない）。**全項目がOKでも、次は確かめていない**：コンテナの中で動くnginx・MySQL（表示もしない）、`FINAL_PROFILER_PORT`が空のときのprofiler、nginxの`access_log`の継承や条件（行ごとの簡易の確認だけ）。

## 失敗したときの調査と戻し方

道具が無くても、普通のコマンドで追える。

```bash
ssh <台> sudo ls /var/lib/tk/ops/                 # 操作IDの一覧（実際の順は各記録の started_at・ended_at）
ssh <台> sudo cat /var/lib/tk/ops/<操作ID>.json    # その操作の記録（recovery を含む）
ssh <台> sudo cat /var/lib/tk/lock.json           # 最後に lock の取得を記録した操作（今も実行中とは限らない）
ssh <台> sudo -u <APP_USER> git -C <APP_DIR> log --oneline -3   # 今の checkout
tools/toolkit/tk status --detail <台>
```

- **戻す**：その操作の後に、他の人の変更（ファイル・サービスの停止など）が無いかを確かめてから、記録の`recovery`の行を上から順に実行し、いずれかの行で失敗したら止める。前のSHAへのdetached checkoutと、`BUILD_CMD`設定時は旧ソースの再buildで戻る。再buildが失敗したらアプリは再起動しない。branchの名前は戻らない。以前の版で作った記録には再buildが含まれないため、旧ソースをbuildしてから再起動する手順を補う。
  記録の`recovery`の例（形の例。実際の行は、その記録の`recovery`が正）：

  ```text
  # Check later manual changes and operations before running these commands.
  sudo -n sh -c 'if test -f /var/lib/tk/ops/<操作ID>/backup/etc/nginx/nginx.conf; then cp -p -- /var/lib/tk/ops/<操作ID>/backup/etc/nginx/nginx.conf /etc/nginx/nginx.conf; fi'
  sudo -n rm -f -- /etc/<新しく作ったファイル>
  sudo -n -u isucon git -C /home/isucon/webapp checkout --detach <prev_head>
  sudo -n systemctl reload nginx
  sudo -n -u isucon bash -lc 'cd -- /home/isucon/webapp && <BUILD_CMD>' && sudo -n systemctl restart <APP_SERVICE>
  ```

  最後の行は、旧ソースのbuildが成功したときだけappを再起動する（`BUILD_CMD`が空なら、再起動の行だけになる）。

- **戻した後**：途中で止まった操作の記録は`running`のまま残り、`status`は終了1のまま。同じcommitをもう一度`tk deploy`すると、完了の記録ができる（buildとサービスの再起動も、もう一度行われる）。
- **rebootが時間切れ**：記録の開始時の`boot_id`と、`ssh <台> cat /proc/sys/kernel/random/boot_id`を比べる。変わっていれば再起動は済んでいるが、記録は`running`のままで、`final-check`の「直近の操作」はNGのまま。記録をそろえるためだけに再起動を繰り返さず、確かめた結果をチームへ共有する。

## 対応していないこと

DDL（`migrations/`）の実行、appを動かさない台（DBの台など）への`tk deploy`（appのunitが無効だと止まる。設定は手で配る。[runbookの5](docs/runbook.md#5-複数台に分ける)）、ファイルの削除やsymlinkの配布、並行のdeploy、自動のrollback、benchmarkの実行（練習用の`bench`は未実装）、Discordへの自動の投稿。理由と今後は[design.mdの8章](docs/design.md#8-本番の後に回してよいもの)。

## 移行前の入口

`tk`へ移していない機能は、次の入口を使う。`deploy`と`final-check`は`tk`に置き換えたので、`scripts/deploy.sh`・`scripts/final-check.sh`は使わない。

| 入口 | 用途 |
|---|---|
| `tools/toolkit/scripts/install-tools.sh <台>` | alpとpt-query-digestを入れる |
| `tools/toolkit/scripts/logs.sh clear\|analyze <台> [DBの台]` | benchmarkの前にログを空にする／後に集計する |
| `tools/toolkit/scripts/profile.sh <台> [秒]` | Goアプリのpprof・fgprofを採る |
| `tools/toolkit/contest-ops/run.sh inspect\|snapshot ...` | 原本の保全（[contest-ops/INITIAL_SETUP.md](contest-ops/INITIAL_SETUP.md)） |
| `tools/toolkit/contest-ops/run.sh nginx-plan\|nginx-apply\|nginx-restore ...` | nginx.confの値の変更（[contest-ops/NGINX_TUNING.md](contest-ops/NGINX_TUNING.md)） |

`scripts/`は、複写した`tools/toolkit/scripts/`から呼ぶ。設定は、同じフォルダの`tools/toolkit/scripts/toolkit.env`を大会に合わせて書き換え、`tk.env`と同じく秘密値を入れずにcommitする（複写した時点の中身は過去の大会の例。各scriptは、自分と同じフォルダの`toolkit.env`を読む）。`logs.sh`・`profile.sh`は、実行したフォルダの`logs/`に結果を書く。

## 直す人へ

```bash
python3 -m unittest discover -s tests -v   # 手元で30秒ほどかかる
shellcheck tk lib/common.sh tasks/*.sh
```

直す前に[原則](docs/principles.md)のチェックリストを、振る舞いを変えるときは[tasks.md](docs/tasks.md)を先に直す。実機で確かめたら、上の成熟度の表を更新する。

## 練習環境

- T系のインスタンス（t2・t3・t3a・t4g）を使わない。CPUクレジットが尽きると性能が大きく絞られる。AWSの無料プランでも`c7i-flex.large`は選べた（2026-10）。
- 過去問のイメージでは、大会のドメインのTLS証明書が期限切れのことがある（ISUCON14は2025-12に失効）。サーバーの中でHTTPSを検証して呼ぶ処理は、`http://localhost:<port>`へ向け直す。
- 複数台を試すときは、同じAMI・セキュリティグループでインスタンスを増やし、同じグループからのすべての通信を許すルールを足す。新しいインスタンスのhost keyは、`aws ec2 get-console-output`のfingerprintと`ssh-keyscan`の結果を突き合わせる。
