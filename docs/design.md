# 構成の案

[原則](principles.md)に沿って、このリポジトリと大会リポジトリの形を決める案。たたき台の段階で、決めた点と、小さな実地テストで確かめる点を分けて書く。

## 0. 前提にした事実

2026-10の練習で、既存の道具を棚卸しし、実機で小さく試した結果（詳細は各自の大会リポジトリの記録）。

- 実機で最後まで通した実績があるのは、`scripts/`の`deploy.sh`・`logs.sh`・`profile.sh`・`final-check.sh`（1人の練習で、取り込み→計装→改善→2台目へのDB移設→最終確認まで）。dockerで動くアプリでも`deploy.sh`は最後まで通った。
- `contest-ops/`のうち実機で通したのは、`inspect`・`snapshot`・`nginx-plan/apply/restore`・`reboot`。`deploy`・`rollback`・`configure`は実機の実績がない。
- 実機へコードを渡す3つの経路は、どれも動いた。(1) 手元からSSHで、実機の**受信用のbare repo**へ`git push`し、アプリのrepoがそこからfetchする。(2) git bundle。(3) 読取り専用のdeploy key。(1)は、受け側の所有者の違い（ログインはubuntu、アプリのrepoはisucon）を最初に1回整える必要があった。稼働中のアプリのrepo（non-bare）へ直接pushする経路は試していない。
- 複数台へ続けて配って1台だけ止まったとき、各台の「HEAD・未commitの変更の有無」を並べるだけで、どこまで進んだかを判別できた。
- 確認系のタスク（`verify`・`final-check.sh`）の失敗は、どれも大会ごとの前提の違い（HTTPのHost、追従するbranchの指定、DBの認証）が原因だった。`verify`には、HTTPの確認に任意のHostを渡す設定がまだない。`final-check.sh`は実機で`git fetch`を行う（refが変わる）。

## 1. 推奨する方式（要約）

| 論点 | 推奨 | 一言の理由 |
|---|---|---|
| 入口 | 1つのCLI `tk <task> [台...]`。中身はタスクごとに既存の実装を呼ぶ | 使う人は実装の技術を意識しない。既存の実績を捨てない |
| 実装の技術 | bashを基本に、実績のあるAnsibleのタスクは残す | 依存を増やさず、動いたものを使う |
| deployの出所 | **必ずcommitから配る**。branchを指定しても、開始時に1度だけ完全なSHAへ解決し、全台へ同じSHAを配る | 出所は常にSHAで追える。途中でbranchが進んでも台ごとに違うものを配らない |
| 実機へ渡す経路 | 手元からSSHで、各台の受信用のbare repoへpush。アプリのrepoは、lockの中でそこからSHAを指定してfetchする。同時にGitHubへもpushする | 実機に鍵を置かない。試した経路そのもの。Gitの既定の安全装置（稼働中のbranchへのpushの拒否）を外さない |
| 状態 | `tk status`を最初に作る。checkoutの状態・直近の操作・稼働の確認・GitHubでの公開を、別の事実として並べる | 実機の状態を信頼できることが、最も重要な目標 |
| 操作の記録と排他 | 実機を変える`tk`のタスクは、実機側の同じlockを使う。操作の開始・段・終了を実機に書く | 他のPCからの`tk`の操作と衝突しない。途中で止まっても、どこで止まったかが残る |
| 戻し方 | 自動のrollbackは後回し。ただし手で戻すための記録（変更前のSHA・触った宛先・元のファイルの退避・戻せない操作）は最初から残す | 失敗したとき「何が変わったか」が分からないのが最も困る |
| 台の名前 | 1台に1つ。Nameタグ・SSHのalias・`hosts/`・設定・文書で、既存の識別子と一意に対応させる | 原則2 |
| branch | `main`＋短命の`feat/<話題>`。個人の統合branchは置かない | 原則3、一般的な形 |

## 2. 2つのリポジトリの形

### 2.1 このリポジトリ（public）

最終の形：

```text
isucon-toolkit/
├── README.md            # 入口。タスクの一覧・成熟度・最初の手順
├── tk                   # 唯一の入口（bash）。tk help でタスクの一覧
├── tasks/               # タスク1つにつき1ファイル（tk が呼ぶ）
├── lib/                 # 共通の部品（設定の読込み・実機側のlockと操作の記録・出力）
├── contest-ops/         # Ansible。tk から呼ぶタスク（snapshot・nginx・reboot）
├── templates/           # 大会リポジトリに複写するひな形（設定・.gitignore・README）
├── docs/
│   ├── principles.md
│   ├── design.md        # この文書
│   ├── tasks.md         # タスクの共通の仕様（次の成果物）
│   └── runbook.md       # 競技の流れ。tk のタスクを順に並べる
└── tests/
```

移行の途中は、`scripts/`と`contest-ops/`の既存の入口をそのまま残す。`tk`へ移したタスクから順に、READMEの一覧を`tk`に切り替え、元の入口を消す。同じ機能の入口が2つある期間を、READMEで明示する。

`contest-ops/`の`deploy`・`rollback`・`configure`・`verify`・`bootstrap`は、`tk`から呼ばない。消すか残すかは、作者と相談して決める。残す場合は、READMEに「tkの対象外」と書く。

### 2.2 大会リポジトリ（private、大会ごと）

```text
<大会repo>/              # = 実機のアプリのフォルダ（例：/home/isucon/webapp）のclone
├── README.md            # 大会の要点・台の役割・今の状態の見方（templates から）
├── go/ sql/ ...         # アプリ（実機から取り込んだまま）
├── server/              # 全台に配る設定。実機の絶対パスのまま（etc/nginx/... など）
├── hosts/<台の名前>/    # その台だけの設定（server/ より優先）
├── tk.env               # 大会ごとの値（パス・サービス名・台の名前と役割・確認先）
├── tools/toolkit/       # このリポジトリの複写（固定SHA、SOURCE.md付き）
└── docs/                # 大会の記録（状態・結果・知見）
```

- リポジトリの直下＝実機のアプリのフォルダとする。直下にアプリと管理用のファイルが並ぶが、実績のある形で、実機のパスとの対応が最も単純になる。
- `server/`には、アプリのフォルダの下のパスを置かない（原則4）。
- 動いているデータ（DBファイル・lock・アップロード）は、`templates/`の`.gitignore`の例に入れ、取り込みの前に列挙する。
- 結果の記録（`runs/`）は、`.gitignore`で除く。1行の要約を、チームのDiscordのチャンネルへ貼る（原則7）。

## 3. 名前

- 台の名前は、**運営が付けたEC2のNameタグをそのまま使う**。本番ではNameタグは運営のCloudFormationが決め、変えると環境の確認（運営の環境確認の仕組み）が失敗するおそれがある。SSHのalias・`hosts/`・`tk.env`の`TK_HOSTS`・文書のすべてで、Nameタグと同じ文字列を使う（ハイフンを含んでよい）。
- マニュアルが示すホスト名（例：`<アプリ>-1.t.isucon.dev`）は別の名前として残る。大会リポジトリのREADMEに、Nameタグとの対応を1か所だけ書く。
- 練習で自分でインスタンスを作るときも、本番と同じ形のNameタグを付ける。
- SSHの入口を作るscriptは、指定した名前をそのままaliasにする（接頭辞を付けない）。
- タスクの名前は、1語で何をするか分かるもの（原則5）。

## 4. タスクの一覧

| タスク | 何をする | 実機を変えるか | 実装 | 成熟度（今） | 初回の半日 |
|---|---|---|---|---|---|
| `status` | 各台について、checkoutの状態・直近の操作・稼働の確認・GitHubでの公開を、別の事実として1表に（5.4） | 読取りだけ | 新規（試作あり） | 1 | **作る** |
| `deploy` | 指定のcommitを、指定の台へ（5章） | 変える | `scripts/deploy.sh`を改修 | 2 | **改修（単一の台から）** |
| `snapshot` | 原本の保全と台の情報の記録 | 読取りだけ | contest-ops `snapshot`・`inspect` | 2 | 既存の入口のまま |
| `init` | 実機のアプリのフォルダを大会repoのcloneにし、記録の領域と受信用repoを作る | 変える | 作らない。runbookの手順で行う | — | 作らない |
| `bench` | **練習専用**。benchmarkの台でbenchmarkを1回実行し、結果をjsonと1行に | benchmarkの初期化で変える | 新規（試作あり） | 1 | 後で |
| `logs` | ログを区切る（clear）・集計する（analyze） | clearは変える | `scripts/logs.sh` | 2 | 既存の入口のまま |
| `profile` | pprofを採る | 読取りだけ | `scripts/profile.sh` | 2 | 既存の入口のまま |
| `tools` | 解析の道具を入れる | 変える | `scripts/install-tools.sh` | 2 | 既存の入口のまま |
| `nginx` | nginx.confの値をplan・apply・restore | 変える（戻せる） | contest-ops `nginx-*` | 2 | 既存の入口のまま |
| `reboot` | 台を1台ずつ再起動し、戻るのを待つ（tasks.mdの14章） | 変える | 新規（`contest-ops`の`reboot`は包まない） | 0 | 2回目 |
| `final-check` | 最終のbenchmarkの準備ができているか（tasks.mdの13章） | 読取りだけ | `scripts/final-check.sh`を元に新規 | 0 | 2回目 |

`contest-ops`の`reboot`は、事前の検査と事後の確認でdeploy用の設定を求めるので、包まずに、`tk reboot`を小さく作る（2回目の範囲）。

## 4.1 benchmarkの扱い

本番では、benchmarkはポータルから人が流す。benchmarkの台は手の内にない。そのため、`tk`のどのタスクも、benchmarkの台への接続を前提にしない（`bench`は練習専用）。人がbenchmarkを流す前後は、次の区切りで`tk`を使う。

```text
tk status → tk logs clear → （人がポータルでbenchmark） → tk logs analyze → tk status
```

SSHの入口を作るscriptも、benchmarkの台を任意にする。

## 5. deployの詳細

段・記録・置き場所の詳細は、[タスクの共通の仕様](tasks.md)が正。この章と食い違うときは、tasks.mdに従う。

```text
tk deploy <commit または branch> [台...]   # 台を省くと tk.env の app の役割の全台
```

### 5.1 開始時に固定すること（操作のmanifest）

1. 手元：入力（branchまたはSHA）を、1度だけ完全なSHAへ解決する。以後、branchを見直さない。
2. 手元：操作ID・担当・入力・解決したSHA・対象の台・開始時刻を、操作のmanifestとして手元に保存する。
3. 手元：GitHubで、そのSHAがどこかのbranchから辿れるようにする。branchを指定したときはそのbranchをpushする。SHAだけを指定したときは、そのSHAを含むbranchがGitHubに無ければ止まる（先にbranchへcommitしてpushする）。pushや確認に失敗したら、manifestに「GitHubでの公開：未確認」と書き、警告を出して続ける。
4. 作業ツリーの未commitの変更は配らない。速い変更（PRの前に試す）は、使い捨てのbranchへcommitして、同じ`tk deploy`で配る。正規の手順と例外を分けない。

### 5.2 実機へ渡す（lockの外）

各台に、受信用のbare repo（tasks.mdの3章）を置く。最初の1回だけ作る（`init`の一部、半日の間はrunbookの手順）。

5. 手元からSSHで、受信用のbare repoの`refs/tk/incoming/<操作ID>`へ、解決したSHAをpushする。稼働中のアプリのrepoへは直接pushしない（Gitの`receive.denyCurrentBranch`の既定の拒否を外さない）。

この段は実機の稼働中のものを変えないので、lockの外で行う。

### 5.3 台ごとの切替（lockの中）

6. 実機側でlockを取る（SSHの接続の中で`flock`。接続が切れればlockも外れる）。取れなければ、lockを持っている操作の記録（誰・操作ID・段）を表示して止まる。
7. 実機の操作の記録に、操作ID・担当・SHA・開始時刻・段＝開始・状態＝runningを書く（atomicに書き換える）。
8. 前提を確かめる：アプリのrepoに未commitの変更があれば止まる（消さない）。変更前のHEADを記録する。
9. アプリのrepoが、受信用のbare repoから、そのSHAをfetchし、取得したSHAがmanifestのSHAと同じか確かめる。違えば止まる。
10. 配る設定の宛先の一覧と差分を作る（plan）。上書きするファイルの元を、`/var/lib/tk/ops/<操作ID>/backup/`へ退避する。
11. checkout→設定の配布→必要なreload・再起動→build→アプリの再起動。段ごとに操作の記録の「段」を書き換える。`migrations/`は、初回のdeployでは実行しない（tasks.mdの8章）。
12. 準備ができるまで待って確認する（今の「1秒後に1回」をやめる）。
13. 操作の記録に、終了時刻・状態（ok・failed）・失敗した段・手で戻す手順（変更前のHEAD、退避したファイル、戻せない操作）を書き、lockを外す。

### 5.4 結果と状態

14. 手元：全台の結果を1表で出す（成功・失敗した段・未実施）。

`tk status`は、次を別の事実として表示する。

| 事実 | 出所 |
|---|---|
| checkoutの状態 | アプリのrepoのHEAD・branch・未commitの変更 |
| 直近の操作 | 実機の操作の記録（操作ID・段・状態・最後に成功したdeployのSHA） |
| 稼働の確認 | サービスの状態・準備の確認の応答（確かめられたときだけ） |
| GitHubでの公開 | 確認済み・未確認 |

checkoutのSHAと、最後に成功したdeployのSHAが違えば「不一致」と表示する（例：buildに失敗して、古いプロセスが動いている）。操作の記録が`running`のまま、実機の起動のID（boot ID）が変わっていれば「中断（再起動）」と表示する。届かない台・読めない項目は「未確認」と表示する。

### 5.5 lockの範囲と限界

- 同じ実機のlockを使うのは、`tk`の、実機を変えるタスクすべて（`deploy`・`init`・`logs clear`・`tools`・`nginx`・`reboot`など）。
- `tk`を通らない操作（手でのSSH、他の道具）は排他できない。`status`の「未commitの変更」や「不一致」で、後から気づけるだけである。
- `final-check`は、実機での`git fetch`をやめ、HEADを「最後に成功したdeployのSHA」と照合する形に直して、読取りだけにする。

## 6. 代替案とトレードオフ

| 論点 | 代替案 | 利点 | 欠点 |
|---|---|---|---|
| deployの出所 | 手元の作業ツリーを送る（contest-opsの方式） | commitの手間がない | 出所が残らない。他の人が状態を信頼できない。最も重要な目標と衝突する |
| 実機へ渡す経路 | 実機がGitHubからfetch（deploy key） | 受信用のrepoが要らない。実績がある | 実機に秘密鍵を置く |
| 実機へ渡す経路 | git bundle | 鍵が要らない | 配るたびに作って送る手間 |
| 実機へ渡す経路 | 稼働中のアプリのrepoへ直接push（`updateInstead`など） | 受信用のrepoが要らない | Gitの安全装置を緩める。試していない |
| 複数台 | Ansibleで並行に | 速い | 実績がない。依存が増える |
| 直下の構成 | アプリを`webapp/`などに分ける | 直下が整理される | 実機のパスとの対応が1段複雑になる。実績がない |
| 実装 | 全部bashに書き直す | 依存が最小 | 実績のあるAnsibleのタスクを作り直す手間 |

### 6.1 複数台とAnsible（設計選択の背景）

複数台への`deploy`も、Ansibleではなく、手元の`tk`が各台へSSHで同じ処理（`lib/remote.py`）を1台ずつ流す形にした（2026-10-30）。

- Ansibleの強みは、複数台を並行に処理できること、台ごとの結果が最後に一覧で出ること、inventoryの組で対象を選べること。
- 今回は「1台ずつ配り、`ok`でなければ止める」と決めたので、並行の強みは使わない（Ansibleでも`serial: 1`と`any_errors_fatal`で同じ動きになる）。台ごとの結果は、`tk`の最後の1行の要約で足りる。
- `tk`の単一台の`deploy`は実機で成熟度2になっている。`contest-ops`の`deploy`は実機の実績がなく、手元の作業ツリーを送る方式で、commitからだけ配る原則と合わない。Ansibleを全員の手元に入れる負担（9章のH5）も、まだ確かめていない。

**大事な点：実機の変更は、どの道具からでも`tk`の記録とlockを通す。** `tk`は、結果を実機の上の記録（`/var/lib/tk/ops/`）に残し、同じlockで排他する。そのため、後から別の人が`tk status`や`sudo cat`で、誰が何をしたかを追える。`tk`を通らない道具（Ansibleのplaybookなど）で実機を変え続けると、その変更は記録にもlockにも現れず、別の人が引き継げなくなる。2026-10の練習でも、この形で混乱した。

並行のdeployや、役割ごとの構成の変更などでAnsibleを使う必要が出たときは、次の形にする。

- Ansibleは「運ぶ役」にとどめ、実機での処理は`tk`の`lib/remote.py`（またはそれと同じ記録とlockを使う処理）を呼ぶ。
- Ansibleで新しいタスクを作るときも、実機の`/var/lib/tk/lock`を取り、`/var/lib/tk/ops/<op_id>.json`に同じ形の記録を書く。記録とlockの形は、tasks.mdの3〜5章が正。
- そうできない道具で実機を変えたときは、原則7の1行で知らせ、次の区切りまでにcommitして`tk deploy`で配り直す（原則3）。

## 7. 初回の半日で作る範囲と受入条件

**作る**

1. `tk`の入口と`lib/`（設定の読込み・実機側のlockと操作の記録・1行の出力）
2. `status`（5.4の表）
3. 単一の台への`deploy`（5.1〜5.3。受信用のbare repoの準備はrunbookの手順）
4. README（`tk`のタスクと、まだ既存の入口のタスクの一覧・成熟度・最初の手順）

**受入条件**（ここまで動けば止めてよい）

- 1台に、使い捨てのbranchのcommitを`tk deploy`で配り、`tk status`でcheckout・直近の操作・稼働の確認が正しく出る。
- buildをわざと失敗させたとき、操作の記録が失敗した段を示し、`status`が「不一致」を出し、記録の手順で手で戻せる。
- 2つの手元から同時に`tk deploy`したとき、片方がlockで止まり、相手の操作IDを表示する。

**作らない（既存の入口のまま）**：`snapshot`・`logs`・`profile`・`tools`・`nginx`。

**2回目（初回の受入条件を満たした後）**：複数台への`deploy`・`final-check`・`reboot`（tasks.mdの12〜14章）。`init`はタスクにせず、runbookの手順で行う。`bench`は練習専用で、後で。

## 8. 本番の後に回してよいもの

- 配った設定（`server/`）と実機の実物の差の照合（`status`の拡張）
- 複数台への並行のdeploy
- 自動のrollback（手で戻すための記録は最初から残す）
- 実機の全体のprovision（パッケージ・カーネルの設定など）
- Discordのチャンネルへの自動の投稿（webhookなど）

## 9. 小さな実地テストで確かめる仮説

| 仮説 | 確かめ方 |
|---|---|
| H1 2台のPCから、同じ台の受信用のbare repoへpushしても、所有者・groupの調整は最初の1回で足りる | 2つの手元から、同じ台へ順に`tk deploy` |
| H2 実機側のlockで、2つのPCからの同時の`tk deploy`の片方が止まる | 2つの手元から同時に`tk deploy`（受入条件と同じ） |
| H3 `tk status`が、3台で10秒以内に返る | 3台で実行して時間を測る |
| H4 準備ができるまで待つ確認で、deployの成否の表示が正しくなる | dockerのアプリで`tk deploy`し、表示とappの応答を比べる |
| H5 チームの各自の手元に、Ansibleを入れる負担が問題にならない | 各メンバーに、`contest-ops`の`validate`を手元で通してもらう |
| H6 dockerのアプリで、buildの重複をなくせる | unitの`--build`に任せる設定と、buildの指定を残す設定で`tk deploy`し、時間と結果を比べる |
| H7 build失敗の後、記録の手順だけで手で戻せる | 受入条件の2つ目 |

## 10. 未決の論点

- `contest-ops/`の使わないタスクを消すか残すか（2.1）
- 原則8の基準が、早い共有を妨げないか（`status`と`deploy`を作る過程で確かめる）
