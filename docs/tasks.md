# タスクの共通の仕様

[構成の案](design.md)の`tk`のタスクが、そろえて守る形。まず初回の半日で作る`status`と`deploy`に要る範囲を決め、ほかのタスクは`tk`へ移すときにこの形へ合わせる。

## 0. 設計の境界

- **手で戻せることを優先する**。自動のrollbackは目指さない。変更前の状態・触る対象・失敗した段・戻す手順を記録し、人がそれを見て安全に戻せることを受入条件にする。
- **共通の部品は仕組みだけ**。`lib/`は、設定の読込み・lock・操作の記録・出力を提供する。各タスクの処理の順番や状態の遷移を制御する、汎用のワークフローエンジンにはしない。各タスクは、自分の段を自分の順に書く。
- **記録が`running`のまま残ることは許す**。異常終了で残った記録は、`status`が「中断」や「未確認」として示せばよい。残った記録を自動で掃除しない。
- **観測したことだけを言う**。SSHの切断でプロセスが終わった、lockが外れた、といったことを仮定しない。lockやプロセスは実際に観測し、観測できなければ「未確認」とする。

## 1. 入口

```text
tk help                       # タスクの一覧と、それぞれの副作用
tk <task> --help              # そのタスクの使い方・副作用・必要な設定
tk <task> [option...] [対象...]
```

- 対象は、台の名前か、`@<役割>`（例：`@app`）。省くと、タスクごとの既定（`deploy`は`@app`、`status`は全台）。
- 確認の質問を出さない。AIや人が、最後まで止まらずに実行できる（SSHは`BatchMode=yes`、実機では`sudo -n`）。
- 実機を変えるタスクは`--plan`を持つ。`--plan`は、実機の読取りだけで、何をどこに変えるかを表示する（実機へpushせず、lockも取らず、記録も書かない）。

## 2. 設定（`tk.env`）

大会リポジトリの直下に置く。秘密値は入れない。

| 項目 | 必須 | 空のときの意味 | 使うタスク |
|---|---|---|---|
| `TK_HOSTS` | 必須 | — | すべて |
| `TK_ROLE_app` | 必須 | — | status・deploy |
| `TK_ROLE_<他の役割>` | 任意 | その役割なし | 対象の指定 |
| `APP_DIR` | 必須 | — | status・deploy |
| `APP_USER` | 必須 | — | status・deploy |
| `APP_SERVICE` | 必須 | — | status・deploy |
| `BUILD_CMD` | 任意 | buildしない | deploy |
| `READY_URL` | 必須 | — | status・deploy |
| `READY_HOST` | 任意 | Hostのheaderを付けない | status・deploy |
| `READY_CODES` | 任意 | `200` | status・deploy |
| `READY_TIMEOUT` | 任意 | `60`（秒） | deploy |
| `TK_STATE_DIR` | 任意 | `/var/lib/tk` | すべて |
| `TK_RECV_REPO` | 任意 | `/var/lib/tk-recv.git` | deploy |

- 「必須」が空なら、実機に接続する前に終了コード2で止まる（何も変えない）。
- 台の名前は、shellの識別子として使える形に限る（`[a-z][a-z0-9_]*`。ハイフンは使えない）。
- 台ごとの上書きは、初回は`READY_URL`・`READY_HOST`・`READY_CODES`だけ。`<項目>__<台の名前>`（下線2つ）と書く（例：`READY_URL__isu3`）。
- 稼働の確認（`READY_*`）は、`TK_ROLE_app`の台だけで行う。他の台では「対象外」とする。

## 3. 操作ID・担当

- 操作ID：`<UTCの日時>-<タスク>-<16進4桁>`（例：`20261030T031500Z-deploy-3fa2`）。手元で1つ作り、全台で同じIDを使う。
- 担当：`TK_ACTOR`があればそれ、なければ`<git config user.name>@<手元のホスト名>`。

## 4. 実機側の状態の領域

### 4.1 置き場所・所有者・実行する人

| パス | 所有者・mode | 中身 | 読み書きする人 |
|---|---|---|---|
| `$TK_STATE_DIR/` | root:root `0700` | 下記 | `sudo -n`（root） |
| `ops/<op_id>.json` | root `0600` | 操作の記録（**正**） | root |
| `ops/<op_id>/backup/` | root `0700` | 変更前のファイル（実機の絶対パスのまま） | root |
| `last` | root `0600` | 直近の操作の`op_id`（1行） | root |
| `last-deploy-ok` | root `0600` | 最後に成功したdeployの`op_id`（1行） | root |
| `lock` | root `0600` | flockの対象（中身は使わない） | root |
| `lock.json` | root `0600` | lockを持っている操作（`op_id`・task・actor・`pid`・`boot_id`・started_at） | root |
| `$TK_RECV_REPO`（`$TK_STATE_DIR`の外） | `APP_USER`:`APP_USER`の group、`0750` | 受信用のbare repo | `sudo -n -u $APP_USER` |

- 実機の操作は、すべてログインユーザーから`sudo -n`で行う。ログインユーザーやgroupの設定は変えない（大会のルールで、isucon以外のユーザーの変更が問題になることがあるため）。
- 受信用のbare repoは、root専用の記録の領域（`$TK_STATE_DIR`、`0700`）の外に置く。`APP_USER`が親のフォルダを辿れないと、受け取りもfetchもできないため。記録とbackupは、引き続きroot専用にする。
- 受信用のbare repoへのpushは、`git push --receive-pack='sudo -n -u <APP_USER> git-receive-pack' <台>:<TK_RECV_REPO> ...`で、`APP_USER`として受け取る。アプリのrepoは、`APP_USER`としてそこからfetchする。
- 状態の領域とbare repoは、`init`（半日の間はrunbookの手順）が作る。`deploy`は、実機に何かを書く前に、`check`の段（7章）で、それらがあること・`sudo -n`が通ること・`python3`・`flock`・`lslocks`があることを、shellだけで確かめる。欠けていれば`refused`で止まり、実機には何も書かない（結果は手元の記録だけに残る）。

### 4.2 操作の記録（`ops/<op_id>.json`）

| 項目 | 意味 |
|---|---|
| `op_id`・`task`・`actor` | 3章 |
| `sha` | 配るcommit（deployのとき） |
| `boot_id`・`pid` | 開始時の`/proc/sys/kernel/random/boot_id`と、記録を書いているプロセス |
| `started_at`・`updated_at`・`ended_at` | UTC。`ended_at`は終了時だけ |
| `step` | 今の段（または最後に入った段） |
| `status` | `running`・`ok`・`failed` |
| `failed_step` | 失敗した段 |
| `prev_head` | 変更前のアプリのrepoのHEAD（deploy） |
| `items` | **変更する予定の宛先**の一覧（4.3） |
| `migrations` | 適用する予定の`migrations/*.sql`と、その状態（`planned`・`applying`・`applied`・`failed`）。異常終了で`applying`が残ったものは、部分的に適用された可能性がある |
| `recovery` | 手で戻す手順（コマンドの行の並び）。変更を始める前に書く |

### 4.3 変更する予定の宛先（`items`）

変更を始める前に、全件を書く。

| 項目 | 意味 |
|---|---|
| `path` | 実機の絶対パス |
| `source` | 対象のcommitの中の元（`server/...`か`hosts/<台>/...`） |
| `before` | 変更前：`exists`・`type`・`mode`・`owner`・`sha256` |
| `backup` | 退避先（変更前に存在したときだけ） |
| `action` | `replace`（上書き）・`create`（新規） |
| `state` | `planned`→`applied`。書き換えの直前に`applying`にする |

- `deploy`はファイルを消さない（`server/`から消えたファイルも、実機には残す）。消す操作は初回の範囲に入れない。
- 異常終了で`state=applying`が残った宛先は、「書き換えたかどうか未確認」として扱う。

### 4.4 書き込みの順番と、正の記録

- 正は`ops/<op_id>.json`だけ。`last`と`last-deploy-ok`は、その`op_id`を指す1行のファイル。
- 各ファイルは、同じフォルダに一時ファイルを書いてから`mv`する（1ファイルずつatomic。複数のファイルをまとめてatomicにはしない）。
- 順番：
  1. 開始：`ops/<op_id>.json`を`running`で書く→`last`を新しい`op_id`へ。
  2. 段の変化：`ops/<op_id>.json`だけを書き換える。
  3. 終了：`ops/<op_id>.json`を`ok`・`failed`で書く→（deployが`ok`なら）`last-deploy-ok`を新しい`op_id`へ。
- 読むとき：`last`・`last-deploy-ok`が指す`ops/<op_id>.json`が無い・壊れている場合は「未確認」とする。`last`が古い`op_id`を指したまま、より新しい`running`の記録が`ops/`にある場合（1と2の間で止まった）も、`ops/`の最新を見て判定する。
- JSONの読み書きは、実機の`python3`で行う（`lib/`の小さな補助を、実行のたびに実機へ送る）。

### 4.5 lock

- 実機を変える`tk`のタスクは、すべて同じ`lock`を使う（deploy・init・logs clear・tools・nginx・rebootなど）。
- 取り方：`flock -n`で取り、取れた直後に`lock.json`を書く。取れなければ、`lock.json`を読んで「誰が・どの操作で・いつから」を表示し、終了コード3で止まる。
- 読取りだけのタスク（`status`など）は、lockを取らない。lockが取られているかは、`lslocks`（util-linux）で、`lock`のパスを持つプロセスを**観測**して確かめる。観測したプロセスの`pid`と`lock.json`の`pid`・`op_id`を照合する。
- SSHの切断でlockが外れるとは仮定しない。外れたかどうかは、上の観測で確かめる。
- `tk`を通らない操作（手でのSSH、他の道具）は排他できない。

## 5. 結果・出力・終了コード

### 5.1 台ごとの結果

| 結果 | 意味 | 実機の稼働中のもの |
|---|---|---|
| `ok` | 最後の段まで成功 | 変わった |
| `refused` | 変更を始める前に止まった（lock・preflight・SHAの不一致など） | 変わっていない |
| `failed` | 変更を始めた後に失敗した | 一部が変わっている。記録の`recovery`を見る |
| `unknown` | 実機の結果を取得できない（変更の途中でSSHが切れたなど） | 分からない。`tk status`で確かめる |

「稼働中のもの」は、アプリのrepoのcheckout・配った設定・サービス・DBを指す。受信用のbare repoのrefとobject、状態の領域の記録、`lock.json`は、`refused`でも変わることがある。

### 5.2 全体の終了コード（実機を変えるタスク）

上から順に、最初に当てはまるもの。

| コード | 条件 |
|---|---|
| 2 | 使い方・設定の誤り（接続していない） |
| 0 | 全台が`ok` |
| 4 | `ok`の台と、それ以外の台がある |
| 3 | 全台が`refused` |
| 1 | `ok`の台が無く、`failed`か`unknown`の台がある |

### 5.3 読取りだけのタスクの終了コード

| コード | 条件 |
|---|---|
| 0 | すべての台で問題なし（`status`では、判定がすべて「問題なし」の値） |
| 1 | 要確認の台がある（`status`では、不一致・記録なし・中断・未確認など） |
| 2 | 使い方・設定の誤り |

### 5.4 手元の記録と1行の要約

- 手元：大会リポジトリの`runs/<op_id>.json`（`.gitignore`で除く）に、操作のmanifest（入力・解決したSHA・対象・開始時刻・GitHubでの公開の確認）と、台ごとの結果（5.1・最後に観測した段・実機の記録の写し）を書く。`unknown`の台は、`unknown`のまま書く。
- 画面：台ごとの結果の表を出し、**最後の1行**に決まった形の要約を出す。

```text
tk deploy 20261030T031500Z-deploy-3fa2 partial sha=3bdcc40 ok=isu1 refused=- failed=isu2@build unknown=- github=confirmed
```

  形：`tk <task> <op_id> <ok|partial|refused|failed> [sha=<短いSHA>] ok=<台,...> refused=<台@段,...> failed=<台@段,...> unknown=<台@段,...> [github=<confirmed|unconfirmed>]`。全体の語は5.2のコードに対応する（0＝ok、4＝partial、3＝refused、1＝failed）。該当なしは`-`。この1行を、そのままチームの共通の場所へ貼れるようにする（原則7）。
- エラーは標準エラーに`NG: <理由>`の形で出す。

## 6. `status`

読取りだけ。lockを取らない。各台を並行に調べ、1台あたりの上限は10秒。

### 6.1 列

| 列 | 中身 | 出所 |
|---|---|---|
| 台 | 名前 | `TK_HOSTS` |
| checkout | 短いHEAD・branch・未commitの変更の有無 | アプリのrepo |
| 直近の操作 | 操作ID・タスク・段・状態 | `last`が指す記録（4.4） |
| 最後のdeploy | 成功したSHA | `last-deploy-ok`が指す記録 |
| 稼働 | サービスの状態・`READY_URL`の応答（`TK_ROLE_app`の台だけ） | systemd・HTTP |
| GitHub | checkoutのSHAがチームのrepoで辿れるか（確認済み・未確認・無し） | 手元のGit |
| 設定の実物 | 初回は常に「未照合」 | — |

### 6.2 判定（3つを別に出す）

**操作の判定**（上から順に、最初に当てはまるもの）

| 値 | 条件 |
|---|---|
| 未確認 | 記録やlockを読めない・読む間に`last`が変わり、10秒以内の読み直しでも定まらない |
| 実行中 | 直近の記録が`running`で、lockを持つプロセスが観測でき、その`op_id`が記録と同じ |
| 中断（別の操作が実行中） | 直近の記録が`running`で、lockを持つプロセスの`op_id`が違う |
| 中断（再起動） | 直近の記録が`running`で、lockを持つプロセスが無く、`boot_id`が今と違う |
| 中断 | 直近の記録が`running`で、lockを持つプロセスが無く、`boot_id`が同じ |
| なし | 上のどれでもない（直近の操作が`failed`でも、ここは「なし」。`failed`は「直近の操作」の列で示す） |

**checkoutの判定**

| 値 | 条件 |
|---|---|
| 未確認 | アプリのrepoを読めない |
| 記録なし | `last-deploy-ok`が無い（初めてのdeployの前） |
| 不一致 | checkoutのSHAが最後に成功したdeployのSHAと違う、または未commitの変更がある |
| checkout一致 | 上のどれでもない |

**稼働の判定**（`TK_ROLE_app`の台だけ。他は「対象外」）

| 値 | 条件 |
|---|---|
| 未確認 | systemdやHTTPの確認が時間内に終わらない |
| 停止 | `APP_SERVICE`がactiveでない |
| 応答NG | `READY_URL`が`READY_CODES`以外を返す・応答しない |
| 稼働 | 上のどれでもない |

「問題なし」は、操作＝なし・checkout＝checkout一致・稼働＝稼働か対象外。「checkout一致」は、アプリのrepoのcheckoutが一致しているという意味だけで、配った設定やDBの実物までは照合していない（「設定の実物」の列は「未照合」）。

## 7. `deploy`

段の名前（`step`）は、次の順。各段は[構成の案](design.md)の5章に対応する。

| 段 | すること | 失敗したとき |
|---|---|---|
| `resolve` | 手元：入力を完全なSHAへ解決し、manifestを作る | 終了2・3 |
| `publish` | 手元：GitHubで辿れるようにpushし、確かめる | `github=unconfirmed`で続ける |
| `check` | 実機：shellだけで、`sudo -n`・`python3`・`flock`・`lslocks`・状態の領域・受信用のbare repoがあるかを確かめる。実機には書かない | `refused`（手元だけに記録） |
| `send` | 手元：受信用のbare repoへpush（lockの外） | `refused` |
| `lock` | 実機：lockを取り、記録を`running`で書く（4.4の1） | `refused` |
| `preflight` | 実機：未commitの変更が無いこと（lockの中で改めて）、`prev_head`の記録 | `refused` |
| `fetch` | 実機：bare repoからSHAをfetchし、manifestのSHAと照合 | `refused` |
| `plan` | 手元で**対象のSHAのtree**から、`server/`と`hosts/<台>/`の宛先・中身のhash・優先を解決した一覧を作り、実機でその現物と比べて`items`を作る。fetchしたcommitの中身のhashが一覧と同じかも確かめる。`migrations/`の予定と`recovery`を書く | `refused` |
| `backup` | 実機：`items`のうち変更前に存在するものを`backup`へ退避 | `failed` |
| `checkout` | 実機：アプリのrepoをそのSHAへ | `failed` |
| `config` | 実機：`items`を1件ずつ、`applying`→書き換え→`applied`の順に | `failed` |
| `reload` | 実機：設定が変わったサービスのreload・再起動 | `failed` |
| `migrate` | 実機：`migrations`を1件ずつ、`applying`→適用→`applied`。失敗は「部分的に適用された可能性」を残す | `failed` |
| `build` | 実機：`BUILD_CMD`（空ならとばす） | `failed` |
| `restart` | 実機：`APP_SERVICE`の再起動 | `failed` |
| `ready` | 実機：`READY_URL`が`READY_CODES`を返すまで、`READY_TIMEOUT`秒まで待つ | `failed` |
| `done` | 実機：記録を`ok`にし（4.4の3）、lockを外す | — |

- `plan`は、現在の作業ツリーの`server/`を見ない。必ず対象のSHAの中身（`git ls-tree`・`git show <SHA>:<path>`）から作り、`config`も同じ`items`を使う。
- `--plan`のときは、`resolve`・`check`の後、`send`をせず、手元で作った一覧を実機の現物と比べて表示するだけにする（実機は読取りだけ）。本実行では、lockを取った後に`plan`をやり直す（`--plan`の後に実物が変わることがあるため）。
- `recovery`には、変更を始める前に、少なくとも次を書く。
  - アプリのrepoを`prev_head`へ戻すコマンド
  - `items`のうち`replace`を`backup`から戻すコマンド、`create`を消すコマンド（`state`が`applied`・`applying`のものが対象）
  - reloadしたサービスの再reload・アプリの再起動のコマンド
  - `migrations`の一覧と、「`applied`・`applying`のものは上の手順では戻らない」の一文
- `tk status <台> --detail`で、その台の直近の操作の`items`・`migrations`・`recovery`を表示する。

## 8. 副作用の宣言

各タスクの先頭のコメントと`--help`に、次の1行を書く。`tk help`とREADMEのタスクの表は、これを集めて作る。

```text
# 副作用: <読取りだけ | 実機を変える：何を | 戻せない：何を>
```

## 9. 初回の半日の受入条件と試験

| 受入条件（design.md 7章） | この仕様で見る所 |
|---|---|
| 1台に配り、`status`が正しく出る | 6.2の「なし・checkout一致・稼働」、7章の`done` |
| buildの失敗で、記録が段を示し、`status`が「不一致」、手で戻せる | 4.2・4.3、6.2の「不一致」、7章の`build`と`recovery` |
| 同時の`deploy`の片方がlockで止まり、相手を示す | 4.5、5.1の`refused` |
| （追加）ログインユーザーと`APP_USER`が違う台で、受け取り（receive-pack）とfetchの両方が通る | 4.1 |

注：buildの失敗の直後は、checkoutが新しいSHAで、最後に成功したdeployと違うので「不一致」になる。手で戻した後は「checkout一致」に戻る（直近の操作の列には`failed`が残る）。

試験の最小の場合：

1. 初めて（記録なし）：`status`が「記録なし」を出し、`deploy`が成功して「checkout一致」になる。
2. 同じSHAを配り直して`ready`で失敗：checkoutは一致のまま、稼働の判定が「応答NG」、直近の操作が`failed`。
3. `config`の途中で止める（プロセスをkill）：`status`が「中断」、`items`に`applying`が残り、`recovery`が使える。
4. 別の操作のlockがある：`deploy`が`refused`で、相手の`op_id`を表示する。`status`が「中断（別の操作が実行中）」か「実行中」を正しく出す。
5. 変更の途中でSSHを切る：手元の結果が`unknown`、`status`で実機の状態を確かめられる。
