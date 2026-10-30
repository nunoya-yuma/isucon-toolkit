# タスクの共通の仕様

[構成の案](design.md)の`tk`のタスクが、そろえて守る形。初回の半日で作る`status`と`deploy`に要る範囲だけを決める。ほかのタスクは、`tk`へ移すときにこの形へ合わせる。

## 0. 設計の境界

- **シンプルさを最優先にする**。チームの作業方法を頑健にすることより、作業方法の違う各メンバーが、互いの変更を把握しやすく、戻しやすいことを優先する。仕組みや記録を足す前に、理解と改変の負担に見合うかを考える。
- **道具が無くても追える**。実機の記録は、`sudo ls`・`sudo cat`・`git log`で読める形にする（10章）。
- **手で戻せることを優先する**。自動のrollbackは目指さない。
- **共通の部品は仕組みだけ**。`lib/`は、設定の読込み・lock・記録・出力を提供する。処理の順番を制御する汎用のワークフローエンジンにはしない。
- **分からないことは「未確認」と言う**。プロセスやlockの状態を推定しない。記録が`running`のまま残っても、そのまま表示すればよい。

## 1. 入口

```text
tk help                       # タスクの一覧と、それぞれの副作用
tk <task> --help              # そのタスクの使い方・副作用・必要な設定
tk <task> [option...] [対象...]
```

- 対象は、台の名前か`@app`（`TK_ROLE_app`の台）。省くと、`deploy`は`@app`、`status`は全台。
- 確認の質問を出さない（SSHは`BatchMode=yes`、実機では`sudo -n`）。
- 実機を変えるタスクは`--plan`を持つ。`--plan`は、実機を読むだけで、何をどこに変えるかを表示する（pushもlockも記録もしない）。

## 2. 設定（`tk.env`）

| 項目 | 必須 | 空のとき |
|---|---|---|
| `TK_HOSTS` | 必須 | — |
| `TK_ROLE_app` | 必須 | — |
| `APP_DIR`・`APP_USER`・`APP_SERVICE` | 必須 | — |
| `BUILD_CMD` | 任意 | buildしない |
| `READY_URL` | 必須 | — |
| `READY_HOST` | 任意 | Hostのheaderを付けない |
| `READY_CODES` | 任意 | `200` |
| `READY_TIMEOUT` | 任意 | `60`（秒） |

- 必須が空なら、接続する前に終了コード2で止まる。
- 台の名前は、EC2のNameタグと同じ文字列（ハイフンを含んでよい。[構成の案](design.md)の3章）。空白は使えない。初回は、台ごとの値の上書きを作らない。
- 稼働の確認は、`TK_ROLE_app`の台だけで行う。

## 3. 実機の上の置き場所

| パス | 所有者・mode | 中身 |
|---|---|---|
| `/var/lib/tk/` | root `0700` | 記録の領域 |
| `/var/lib/tk/ops/<op_id>.json` | root `0600` | 操作の記録（10行ほどのjson） |
| `/var/lib/tk/ops/<op_id>/backup/` | root `0700` | 上書きする前のファイル（実機の絶対パスのまま） |
| `/var/lib/tk/lock` | root | flockの対象 |
| `/var/lib/tk/lock.json` | root | 最後にlockの取得を記録した操作（`op_id`・`actor`・`started_at`）。lockが外れた後も残るので、今も実行中という意味ではない |
| `/var/lib/tk-recv.git/` | `APP_USER` `0750` | 受信用のbare repo（記録の領域の外。`APP_USER`が辿れるように） |

- 実機の操作は、ログインユーザーから`sudo -n`で行う。ログインユーザーやgroupは変えない。
- 受信用のbare repoへは、`git push --receive-pack='sudo -n -u <APP_USER> git-receive-pack'`で、`APP_USER`として受け取る。アプリのrepoは、`APP_USER`としてそこからfetchする。
- これらは`init`（半日の間はrunbookの手順）が作る。`deploy`は作らない。

## 4. 操作IDと記録

- 操作ID：`<UTCの日時>-<タスク>-<16進4桁>`（例：`20261030T031500Z-deploy-3fa2`）。全台で同じIDを使う。名前の順は**手元で操作を作った順の目安**で、実機で行われた順とは限らない（lockを待った操作が後から行われることや、PCの時計のずれがある）。
- 担当：`TK_ACTOR`、なければ`<git config user.name>@<手元のホスト名>`。
- 記録（`ops/<op_id>.json`）の項目：

| 項目 | 意味 |
|---|---|
| `op_id`・`task`・`actor` | 上 |
| `sha` | 配るcommit |
| `prev_head` | 変更前のアプリのrepoのHEAD |
| `started_at`・`ended_at` | UTC。実機の時計で、lockを取った時と終わった時に書く |
| `step` | 今の段（最後に入った段） |
| `status` | `running`・`ok`・`failed` |
| `files` | 上書き・新規作成する予定のファイルの一覧（`path`と`replace`か`create`） |
| `recovery` | 手で戻すコマンドの行の並び |

- 記録は、一時ファイルを書いてから`mv`する。正はこのファイルだけで、別の索引のファイルは作らない。
- `files`と`recovery`は、**変更を始める前に**書く。
- 「直近の操作」は、実機で書いた`started_at`が最新のもの。「最後に成功したdeploy」は、`task=deploy`・`status=ok`のうち`ended_at`が最新のもの。同じ時刻などで決められなければ、候補をそのまま表示する。

## 5. lock

- 実機を変える`tk`のタスクは、同じ`lock`を`flock -n`で取る。取れたら`lock.json`を書く。取れなければ、「最後にlockの取得を記録した操作」として`lock.json`の中身を表示して止まる。
- `status`はlockを取らず、推定もしない。直近の操作が`running`なら、「running」と、最後にlockの取得を記録した操作をそのまま表示する（実行中か中断かは、人が判断する）。
- `tk`を通らない操作は排他できない。

## 6. 終了コードと1行の要約

| コード | 実機を変えるタスク | 読取りだけのタスク |
|---|---|---|
| 0 | 全台で成功 | 全台で問題なし |
| 1 | それ以外（変更後に失敗した台・結果が分からない台・前に止まった台のどれかがあり、全台が「変更前に止まった」ではない） | 要確認の台がある |
| 2 | 使い方・設定の誤り（接続していない） | 同左 |
| 3 | 全台で、変更を始める前に止まった（稼働中のものは変わっていない） | — |

最後の1行に、台ごとの結果を出す。そのままチームの共通の場所へ貼れる形にする（原則7）。

```text
tk deploy 20261030T031500Z-deploy-3fa2 sha=3bdcc40 contest-1=ok contest-2=failed@build
```

台ごとの結果は、`ok`・`refused@<段>`（変更前に止まった）・`failed@<段>`（変更後に失敗）・`unknown@<段>`（途中で接続が切れた）。手元の`runs/<op_id>.json`（`.gitignore`で除く）にも同じものを残す。

## 7. `status`

読取りだけ。各台を並行に調べ、1台あたり10秒まで。届かない台・読めない項目は「未確認」。

| 列 | 中身 |
|---|---|
| checkout | 短いHEAD・branch・未commitの変更の有無 |
| 最後のdeploy | 成功したSHA。無ければ「記録なし」 |
| 一致 | checkoutのSHAが最後のdeployのSHAと同じで、未commitの変更が無ければ「一致」、違えば「不一致」 |
| 直近の操作 | 操作ID・タスク・段・状態（`running`なら、最後にlockの取得を記録した操作も） |
| 稼働 | `APP_SERVICE`の状態と`READY_URL`の応答（`TK_ROLE_app`の台だけ） |

GitHubで辿れるかは、初回の`status`では見ない（`deploy`の`publish`の段で、実行時に知らせる）。

「一致」は、アプリのrepoのcheckoutの一致だけを意味する。配った設定やDBの実物は照合しない。

## 8. `deploy`

| 段 | すること | 失敗したとき |
|---|---|---|
| `resolve` | 手元：入力を完全なSHAへ解決する。全台に同じSHAを配る | 終了2・3 |
| `publish` | 手元：GitHubで辿れるようにpushする | 警告して続ける |
| `check` | 実機：shellだけで、`sudo -n`・`python3`・`flock`・記録の領域・受信用repoがあるかを確かめる。何も書かない | `refused` |
| `send` | 手元：受信用repoへpush | `refused` |
| `lock` | 実機：lockを取り、記録を`running`で書く | `refused` |
| `prepare` | 実機：未commitの変更が無いこと、SHAをfetchして照合、`prev_head`を記録。対象のSHAの中身から、配るファイルの一覧と、reload・再起動するサービスの一覧を作り、`files`と`recovery`を書く | `refused` |
| `backup` | 実機：上書きするファイルを`backup/`へ退避する。1件ずつ一時名へ複写し、複写が成功したときだけ正式な名前へrenameする（途中で止まった部分的なファイルを、戻す元にしないため）。**全件の退避が成功するまで、次の段へ進まない** | `failed`（実機の稼働中のものは、まだ変わっていない） |
| `apply` | 実機：checkout→`server/`・`hosts/<台>/`のファイルを配る | `failed` |
| `restart` | 実機：設定が変わったサービスのreload→build→`APP_SERVICE`の再起動 | `failed` |
| `ready` | 実機：`READY_URL`が`READY_CODES`を返すまで待つ | `failed` |
| `done` | 実機：記録を`ok`にし、lockを外す | — |

- 配るファイルの一覧は、現在の作業ツリーではなく、対象のSHAの中身から作る。`--plan`は、手元で一覧を作り、実機の現物との差を表示するだけにする。
- **`recovery`は、どこで止まっても全行をそのまま実行して安全な形**にする。中身は、`backup/`に戻す元があるファイルだけを戻す・新規に作る予定だったファイルを消す・アプリのrepoを`prev_head`へ戻す・この操作がreload・再起動するはずだったサービスだけを再起動する、の4つ。まだ変えていないファイルに対して実行しても害がないので、どこまで進んだかを記録しなくてよい。
- ただし`recovery`は、その操作の後に他の人が加えた変更（ファイルの修正・新規作成・意図してサービスを止めたこと）を守らない。実行する前に、その操作の後の変更が無いかを人が確かめる（`status`と`ops/`の一覧で、後の操作が無いか・未commitの変更が無いかを見る）。
- **`migrations/`は初回の`deploy`では実行しない**。再実行してよいかを保証できないため。DDLは、必要になったときに別のタスクにする。
- **Git管理外の実機の設定（`/etc/nginx`など）が手で変えられていても、初回は上書きを防がない**。防ぐ代わりに、必ず`backup/`へ退避し、`--plan`と実行時の表示で差分を見せる。手での変更を残したいときは、先にその変更をcommitしてから配る（原則3）。

## 9. 副作用の宣言

各タスクの先頭のコメントと`--help`に、次の1行を書く。`tk help`とREADMEの表は、これを集めて作る。

```text
# 副作用: <読取りだけ | 実機を変える：何を | 戻せない：何を>
```

## 10. 道具を使わずに調べる・戻す

`tk`が壊れていても、使い方を知らない人でも、普通のコマンドで追えるようにする。

```bash
ssh <台> sudo ls /var/lib/tk/ops/                 # 操作IDの一覧（実際に行われた順は、各記録の started_at・ended_at を見る）
ssh <台> sudo cat /var/lib/tk/ops/<op_id>.json    # その操作の記録（recovery を含む）
ssh <台> sudo cat /var/lib/tk/lock.json           # 最後に lock の取得を記録した操作（今も実行中とは限らない）
ssh <台> sudo -u <APP_USER> git -C <APP_DIR> log --oneline -3   # 今のcheckout
```

戻すときは、その操作の後に他の変更が無いかを確かめてから、記録の`recovery`の行を、上から順に実行する。

## 11. 初回の半日の受入条件と試験

| 受入条件（design.md 7章） | 試験 |
|---|---|
| 1台に配り、`status`が正しく出る | 記録なしの台に`deploy`し、`status`が「一致」「稼働」を出す |
| buildの失敗で、記録が段を示し、`status`が「不一致」、手で戻せる | buildをわざと失敗させ、`recovery`を実行して「一致」に戻る |
| 同時の`deploy`の片方がlockで止まり、相手を示す | 2つの手元から同時に`deploy` |
| ログインユーザーと`APP_USER`が違う台で、受け取りとfetchが通る | 上の試験を、その条件の台で行う |

加えて、途中で止めた場合（`apply`の途中でkill、SSHの切断）に、`status`が`running`を表示し、`recovery`をそのまま実行して戻せることを確かめる。
