# タスクの共通の仕様

[構成の案](design.md)の`tk`のタスクが、そろえて守る形。まず初回の半日で作る`status`と`deploy`に要る範囲を決め、ほかのタスクは`tk`へ移すときにこの形へ合わせる。

## 0. 設計の境界

- **手で戻せることを優先する**。自動のrollbackは目指さない。変更前の状態・触った対象・失敗した段・戻す手順を記録し、人がそれを見て安全に戻せることを受入条件にする。
- **共通の部品は仕組みだけ**。`lib/`は、設定の読込み・lock・操作の記録・出力を提供する。各タスクの処理の順番や状態の遷移を制御する、汎用のワークフローエンジンにはしない。各タスクは、自分の段を自分の順に書く。
- **記録が`running`のまま残ることは許す**。異常終了で残った記録は、`status`が「中断」や「未確認」として示せばよい。残った記録を自動で掃除しない。

## 1. 入口

```text
tk help                       # タスクの一覧と、それぞれの副作用
tk <task> --help              # そのタスクの使い方・副作用・必要な設定
tk <task> [option...] [対象...]
```

- 対象は、台の名前か、`@<役割>`（例：`@app`）。省くと、タスクごとの既定（`deploy`は`@app`、`status`は全台）。
- 確認の質問を出さない。AIや人が、最後まで止まらずに実行できる（SSHは`BatchMode=yes`）。
- 実機を変えるタスクは`--plan`を持つ。`--plan`では、何をどこに変えるかを表示するだけで、実機を変えない（lockも取らない）。

## 2. 設定（`tk.env`）

大会リポジトリの直下に置く。秘密値は入れない（入れる必要がある値は、実機の既存の環境ファイルを参照する）。

| 項目 | 例 | 使うタスク |
|---|---|---|
| `TK_HOSTS` | `isu1 isu2 isu3` | すべて |
| `TK_ROLE_<役割>` | `TK_ROLE_app="isu1 isu2"` | 対象の指定 |
| `APP_DIR` | `/home/isucon/webapp` | status・deploy |
| `APP_USER` | `isucon` | status・deploy |
| `APP_SERVICE` | `isuports` | status・deploy |
| `BUILD_CMD` | `docker compose -f docker-compose-go.yml build`（空なら buildしない） | deploy |
| `READY_URL` | `http://127.0.0.1:3000/api/me` | status・deploy |
| `READY_HOST` | `admin.t.isucon.dev`（空ならHostを付けない） | status・deploy |
| `READY_CODES` | `200 401` | status・deploy |
| `READY_TIMEOUT` | `60`（秒） | deploy |
| `TK_STATE_DIR` | `/var/lib/tk`（既定） | すべて |

- 各タスクは、使う項目が空なら、実機に接続する前に終了コード2で止まる（何も変えない）。
- 台ごとに違う値は、`tk.env`の中で`<項目>_<台の名前>`と書けば、その台だけ上書きする（例：`READY_URL_isu3`）。

## 3. 操作ID・担当

- 操作ID：`<UTCの日時>-<タスク>-<16進4桁>`（例：`20261030T031500Z-deploy-3fa2`）。手元で1つ作り、全台で同じIDを使う。
- 担当：`TK_ACTOR`があればそれ、なければ`<git config user.name>@<手元のホスト名>`。

## 4. 実機側の記録

`TK_STATE_DIR`（既定`/var/lib/tk`）の下に置く。所有者はroot、groupは`APP_USER`のgroup、記録のファイルは`0640`。

```text
/var/lib/tk/
├── lock                 # flock の対象（中身は使わない）
├── lock.json            # lock を持っている操作（op_id・task・actor・started_at）
├── repo.git/            # 受信用の bare repo（deploy）
├── ops/<op_id>.json     # 操作ごとの記録
├── ops/<op_id>/backup/  # その操作で上書きしたファイルの元（実機の絶対パスのまま）
├── last.json            # 直近の操作の記録（ops/<op_id>.json と同じ中身）
└── last-deploy-ok.json  # 最後に成功した deploy の記録
```

### 4.1 操作の記録（`ops/<op_id>.json`）

| 項目 | 意味 |
|---|---|
| `op_id`・`task`・`actor` | 3章 |
| `sha` | 配るcommit（deployのとき） |
| `boot_id` | 開始時の`/proc/sys/kernel/random/boot_id` |
| `started_at`・`updated_at`・`ended_at` | UTC。`ended_at`は終了時だけ |
| `step` | 今の段（または最後に入った段） |
| `status` | `running`・`ok`・`failed` |
| `failed_step` | 失敗した段（失敗のとき） |
| `prev_head` | 変更前のアプリのrepoのHEAD（deploy） |
| `changed` | 実際に触った宛先の一覧（`{path, action: replaced|created|deleted}`） |
| `backup_dir` | 上書きしたファイルの退避先 |
| `irreversible` | 戻せない操作の一覧（例：`migrations/001.sql`） |
| `recovery` | 手で戻す手順（コマンドの行の並び） |

- 書くときは、同じフォルダに一時ファイルを書いてから`mv`する（atomic）。
- 開始時に`status=running`で書き、段に入るたびに`step`と`updated_at`を書き換え、終了時に結果を書く。`last.json`も同時に同じ中身へ置き換える。
- JSONの読み書きは、実機の`python3`で行う（`lib/`の小さな補助を実機へ送る）。`python3`が無ければ、実機を変える前に終了コード3で止まる。

### 4.2 lock

- 実機を変える`tk`のタスクは、すべて同じ`lock`を使う（deploy・init・logs clear・tools・nginx・rebootなど）。読取りだけのタスクは取らない。
- 取り方：実機へのSSHの接続の中で`flock -n`する。接続が切れればlockも外れる。取れた直後に`lock.json`を書く。
- 取れなければ、`lock.json`を読んで「誰が・どの操作で・いつから」を表示し、終了コード3で止まる。
- `tk`を通らない操作（手でのSSH、他の道具）は排他できない。

## 5. 手元の記録と出力

- 手元：大会リポジトリの`runs/<op_id>.json`（`.gitignore`で除く）に、操作のmanifest（入力・解決したSHA・対象・開始時刻・GitHubでの公開の確認）と、台ごとの結果（終了コード・最後の段・実機の記録の写し）を書く。
- 画面：台ごとの結果の表を出し、**最後の1行**に決まった形の要約を出す。

```text
tk deploy 20261030T031500Z-deploy-3fa2 failed sha=3bdcc40 ok=isu1 failed=isu2@build skipped=- github=confirmed
```

  形：`tk <task> <op_id> <ok|failed|partial> [sha=<短いSHA>] ok=<台,...> failed=<台@段,...> skipped=<台,...> [github=<confirmed|unconfirmed>]`。該当なしは`-`。この1行を、そのままチームの共通の場所へ貼れるようにする（原則7）。
- エラーは標準エラーに`NG: <理由>`の形で出す。

## 6. 終了コード

| コード | 意味 | 実機 |
|---|---|---|
| 0 | 全台で成功 | 変わった（読取りのタスクは変わらない） |
| 1 | 変更を始めた後に失敗 | 一部が変わっている。記録の`recovery`を見る |
| 2 | 使い方・設定の誤り | 接続していない。何も変わらない |
| 3 | 前提を満たさない（lockが取れない・未commitの変更・SHAの不一致・`python3`が無い） | 何も変わらない |
| 4 | 複数台のうち一部だけ成功 | 台ごとの結果を見る |

## 7. `status`

読取りだけ。lockを取らない。各台を並行に調べ、1台あたりの上限は10秒。

| 列 | 中身 | 出所 |
|---|---|---|
| 台 | 名前 | `TK_HOSTS` |
| checkout | 短いHEAD・branch・未commitの変更の有無 | アプリのrepo |
| 直近の操作 | 操作ID・タスク・段・状態 | `last.json` |
| 最後のdeploy | 成功したSHA | `last-deploy-ok.json` |
| 稼働 | サービスの状態・`READY_URL`の応答 | systemd・HTTP |
| GitHub | checkoutのSHAがチームのrepoで辿れるか（確認済み・未確認・無し） | 手元のGit |
| 判定 | 下の表 | |

判定（上から順に、最初に当てはまるもの）。直近の操作が`failed`であることは「直近の操作」の列で示し、判定には使わない（手で戻した後に「一致」へ戻れるようにするため）：

| 判定 | 条件 |
|---|---|
| 未確認 | 台に届かない・読めない項目がある |
| 実行中 | `last.json`が`running`で、lockが取られている |
| 中断（再起動） | `last.json`が`running`で、`boot_id`が今と違う |
| 中断 | `last.json`が`running`で、lockが空いている（`flock -n`で確かめてすぐ外す） |
| 不一致 | checkoutのSHAと`last-deploy-ok.json`のSHAが違う・未commitの変更がある（buildの失敗で新しいcheckoutのまま止まった場合も、これに当たる） |
| 一致 | 上のどれでもない |

## 8. `deploy`

段の名前（`step`）は、次の順。各段は[構成の案](design.md)の5章に対応する。

| 段 | すること | 失敗したとき |
|---|---|---|
| `resolve` | 手元：入力を完全なSHAへ解決し、manifestを作る | 終了2・3。実機は変わらない |
| `publish` | 手元：GitHubで辿れるようにpushし、確かめる | 失敗なら`github=unconfirmed`で続ける |
| `send` | 手元：受信用のbare repoへSSHでpush（lockの外） | 終了3。稼働中のものは変わらない |
| `lock` | 実機：lockを取り、記録を`running`で書く | 終了3 |
| `preflight` | 実機：未commitの変更が無いこと・`prev_head`の記録 | 終了3。変わらない |
| `fetch` | 実機：bare repoからSHAをfetchし、manifestのSHAと照合 | 終了3。変わらない |
| `plan` | 実機：配る設定の宛先と差分の一覧を作る | 終了3。変わらない |
| `backup` | 実機：上書きするファイルを`backup_dir`へ退避 | 終了1 |
| `checkout` | 実機：アプリのrepoをそのSHAへ | 終了1 |
| `config` | 実機：`server/`・`hosts/<台>/`の差分を配る | 終了1 |
| `reload` | 実機：設定が変わったサービスのreload・再起動 | 終了1 |
| `migrate` | 実機：`migrations/*.sql`の適用（`irreversible`に記録） | 終了1 |
| `build` | 実機：`BUILD_CMD` | 終了1 |
| `restart` | 実機：`APP_SERVICE`の再起動 | 終了1 |
| `ready` | 実機：`READY_URL`が`READY_CODES`を返すまで、`READY_TIMEOUT`秒まで待つ | 終了1 |
| `done` | 実機：記録を`ok`にし、`last-deploy-ok.json`を書き、lockを外す | — |

失敗したとき、記録の`recovery`には、少なくとも次を書く。

- アプリのrepoを`prev_head`へ戻すコマンド
- `changed`のうち`replaced`のものを`backup_dir`から戻すコマンド、`created`のものを消すコマンド
- reloadしたサービスの再reload・アプリの再起動のコマンド
- `irreversible`の一覧と、「これは上の手順では戻らない」の一文

`tk status`の対象の台の詳しい表示（`tk status <台> --detail`）で、この`recovery`をそのまま表示する。

## 9. 副作用の宣言

各タスクの先頭のコメントと`--help`に、次の1行を書く。`tk help`とREADMEのタスクの表は、これを集めて作る。

```text
# 副作用: <読取りだけ | 実機を変える：何を | 戻せない：何を>
```

## 10. 初回の半日の受入条件との対応

| 受入条件（design.md 7章） | この仕様で見る所 |
|---|---|
| 1台に配り、`status`が正しく出る | 7章の「一致」、8章の`done` |
| buildの失敗で、記録が段を示し、`status`が「不一致」、手で戻せる | 4.1の`failed_step`・`recovery`、7章の「不一致」、8章の`build` |
| 同時の`deploy`の片方がlockで止まり、相手を示す | 4.2、6章の終了3 |

注：buildの失敗の直後は、checkoutが新しいSHAで`last-deploy-ok.json`と違うので「不一致」になる。手で戻した後は、checkoutと`last-deploy-ok.json`が一致すれば「一致」に戻る（直近の操作の列には`failed`が残る）。
