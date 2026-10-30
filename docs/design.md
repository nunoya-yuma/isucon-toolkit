# 構成の案

[原則](principles.md)に沿って、このリポジトリと大会リポジトリの形を決める案。たたき台の段階で、決めた点と、小さな実地テストで確かめる点を分けて書く。

## 0. 前提にした事実

2026-10の練習で、既存の道具を棚卸しし、実機で小さく試した結果（詳細は各自の大会リポジトリの記録）。

- 実機で最後まで通した実績があるのは、`scripts/`の`deploy.sh`・`logs.sh`・`profile.sh`・`final-check.sh`（1人の練習で、取り込み→計装→改善→2台目へのDB移設→最終確認まで）。dockerで動くアプリでも`deploy.sh`は最後まで通った。
- `contest-ops/`のうち実機で通したのは、`inspect`・`snapshot`・`nginx-plan/apply/restore`・`reboot`。`deploy`・`rollback`・`configure`は実機の実績がない。
- 実機へコードを渡す3つの経路（手元からSSHで`git push`、git bundle、読取り専用のdeploy key）は、どれも動いた。SSHでのpushは、受け側の所有者の違い（ログインはubuntu、repoはisucon）を最初に1回整える必要があった。
- 複数台へ続けて配って1台だけ止まったとき、各台の「HEAD・未commitの変更の有無」を並べるだけで、どこまで進んだかを判別できた。
- 確認系のタスク（`verify`・`final-check.sh`）の失敗は、どれも大会ごとの前提の違い（HTTPのHost、追従するbranchの指定、DBの認証）が原因だった。`verify`には、HTTPの確認に任意のHostを渡す設定がまだない。

## 1. 推奨する方式（要約）

| 論点 | 推奨 | 一言の理由 |
|---|---|---|
| 入口 | 1つのCLI `tk <task> [台...]`。中身はタスクごとに既存の実装を呼ぶ | 使う人は実装の技術を意識しない。既存の実績を捨てない |
| 実装の技術 | bashを基本に、実績のあるAnsibleのタスクだけ残す | 依存を増やさず、動いたものを使う |
| deployの出所 | **必ずcommitから配る**（branchは問わない）。手元の作業ツリーからは配らない | 速さはcommitの軽さで得て、出所は常にSHAで追える |
| 実機へ渡す経路 | 手元から各台へSSHで`git push`。同時にGitHubへもpushする | 実機に鍵を置かない。配ったcommitが必ずチームから見える |
| 状態 | `tk status`を最初に作る。各台のHEAD・branch・未commitの変更・サービス・直近の操作を1表にする | 実機の状態を信頼できることが、最も重要な目標 |
| 操作の記録と排他 | 実機を変えるタスクは、実機側でlockを取り、実機側に直近の操作を書く | 他のPCからの操作とも衝突せず、誰が何をしたかが実機に残る |
| 台の名前 | Nameタグ・SSHのalias・`hosts/`・設定・文書で同じ短い名前 | 原則2 |
| branch | `main`＋短命の`feat/<話題>`。個人の統合branchは置かない | 原則3、一般的な形 |

## 2. 2つのリポジトリの形

### 2.1 このリポジトリ（public）

```text
isucon-toolkit/
├── README.md            # 入口。タスクの一覧・成熟度・最初の手順
├── tk                   # 唯一の入口（bash）。tk help でタスクの一覧
├── tasks/               # タスク1つにつき1ファイル（tk が呼ぶ）
│   ├── status.sh
│   ├── deploy.sh
│   ├── bench.sh
│   ├── logs.sh
│   ├── profile.sh
│   ├── tools.sh
│   └── final-check.sh
├── lib/                 # タスクが共通に使う部品（設定の読込み・記録・lock・出力）
├── contest-ops/         # Ansible。tk から呼ぶタスクだけ残す（snapshot・nginx・reboot）
├── templates/           # 大会リポジトリに複写するひな形（設定・.gitignore・README）
├── docs/
│   ├── principles.md
│   ├── design.md        # この文書
│   ├── tasks.md         # タスクの共通の仕様（次の成果物）
│   └── runbook.md       # 競技の流れ。tk のタスクを順に並べる
└── tests/
```

- 今の`scripts/`の中身は`tasks/`へ移し、名前をタスクの名前にそろえる。`scripts/`は残さない（同じ機能を2か所に置かない）。
- `contest-ops/`の`deploy`・`rollback`・`configure`・`verify`・`bootstrap`は、`tk`から呼ばない。消すか残すかは、作者と相談して決める［要議論］。残す場合は、READMEに「tkの対象外」と書く。

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
- `server/`には、アプリのフォルダの下のパスを置かない（原則4）。アプリのフォルダの中のファイルは、直下のファイルが正。
- 動いているデータ（DBファイル・lock・アップロード）は、`templates/`の`.gitignore`の例に入れ、取り込みの前に列挙する。
- 結果の記録（`runs/`）は、`.gitignore`で除く。1行の要約を、チームの共通の場所へ出す（原則7）。

## 3. 名前

- 台の名前は、大会に依存しない短い名前にする。案：`isu1`・`isu2`・`isu3`・`bench`。EC2のNameタグ・SSHのalias・`hosts/`・`tk.env`の役割の指定・文書のすべてで同じにする［要議論：名前そのもの］。
- SSHの入口を作るscriptは、指定した名前をそのままaliasにする（接頭辞を付けない）。
- タスクの名前は、1語で何をするか分かるもの（原則5）。

## 4. タスクの一覧

| タスク | 何をする | 実機を変えるか | 実装 | 成熟度（今） | 半日で |
|---|---|---|---|---|---|
| `status` | 各台のHEAD・branch・未commitの変更・サービス・待受・直近の操作を1表に。届かない台・読めない項目は「未確認」と表示する | 読取りだけ | 新規（試作あり） | 1→2 | **作る** |
| `snapshot` | 原本の保全（指定のパスを手元へ）と台の情報の記録 | 読取りだけ | contest-ops `snapshot`・`inspect` | 2 | 包む |
| `init` | 実機のアプリのフォルダを、大会repoのcloneに切り替える（元は残す） | 変える | 新規（試作あり） | 1 | 作る |
| `deploy` | 指定のcommitを、指定の台へ。push→checkout→設定の配布→build→再起動→準備ができるまで待って確認 | 変える | `scripts/deploy.sh`を改修 | 2 | **改修** |
| `bench` | benchmarkを1回実行し、結果をjsonと1行に | benchmarkの初期化で変える | 新規（試作あり） | 1 | 作る |
| `logs` | ログを区切る（clear）・集計する（analyze） | clearは変える | `scripts/logs.sh` | 2 | 移す |
| `profile` | pprofを採る | 読取りだけ | `scripts/profile.sh` | 2 | 移す |
| `tools` | 解析の道具を入れる | 変える | `scripts/install-tools.sh` | 2 | 移す |
| `nginx` | nginx.confの値をplan・apply・restore | 変える（戻せる） | contest-ops `nginx-*` | 2 | 包む |
| `reboot` | 台を1台ずつ再起動 | 変える | contest-ops `reboot` | 2 | 包む |
| `final-check` | 最終のbenchmarkの準備ができているか | 読取りだけ | `scripts/final-check.sh`を改修（前提を設定で渡す） | 2（前提の調整が要る） | 改修 |

「包む」は、中身を変えずに`tk`から呼べるようにすること。

## 5. deployの流れ（推奨の詳細）

```text
tk deploy <commit または branch> [台...]   # 台を省くと tk.env の app の役割の全台
```

1. 手元：指定がcommitであることを確かめる（作業ツリーの未commitの変更は配らない。必要なら先に`feat/`か使い捨てのbranchへcommitする）。
2. 手元：そのbranchをGitHubへpushする（チームから見えるようにする）。
3. 台ごとに順に：
   1. 実機側でlockを取る（取れなければ、誰が持っているかを表示して止まる）。
   2. 実機に未commitの変更があれば止まる（消さない）。
   3. 手元からSSHで、実機のリポジトリへpushする。
   4. checkout→`server/`・`hosts/<台>/`の差分だけを配る→必要なreload・再起動→build→アプリの再起動。
   5. 準備ができるまで待って確認する（今の「1秒後に1回」をやめる）。
   6. 実機側に直近の操作（時刻・誰・commit・結果）を書き、lockを外す。
4. 手元：全台の結果を1表で出す（どの台が成功・失敗・未実施か）。

速い変更（PRの前に試す）も、同じ`tk deploy`で、使い捨てのbranchのcommitを配るだけにする。正規の手順と例外を分けない。mainに入れるかどうかは、後でPRで決める。

補足：

- 実機側のlockは、SSHの接続の中で`flock`を取る形にする。接続が切れればlockも外れるので、残ったlockの掃除が要らない。
- GitHubへのpushに失敗した場合（ネットワークの障害など）は、警告を出して実機への配布は続ける。`status`で「GitHubに無いcommit」と分かるようにする。

## 6. 代替案とトレードオフ

| 論点 | 代替案 | 利点 | 欠点 |
|---|---|---|---|
| deployの出所 | 手元の作業ツリーを送る（contest-opsの方式） | commitの手間がない | 出所が残らない。他の人が状態を信頼できない。最も重要な目標と衝突する |
| 実機へ渡す経路 | 実機がGitHubからfetch（deploy key） | 手元が要らない。実績がある | 実機に秘密鍵を置く。配る前に必ずGitHubへのpushが要る点は推奨案と同じ |
| 実機へ渡す経路 | git bundle | 鍵が要らない | 配るたびに作って送る手間 |
| 複数台 | Ansibleで並行に | 速い | 実績がない（contest-opsのdeployは未検証）。依存が増える |
| 直下の構成 | アプリを`webapp/`などに分ける | 直下が整理される | 実機のパスとの対応が1段複雑になる。実績がない |
| 実装 | 全部bashに書き直す | 依存が最小 | 実績のあるAnsibleのタスク（nginxの自動の戻しなど）を作り直す手間 |

## 7. 半日で作る最小の構成

1. `tk`の入口と`lib/`（設定の読込み・記録・実機側のlock・1行の出力）
2. `status`
3. `deploy`の改修（commitだけを配る・SSHでpush・実機側のlockと記録・準備ができるまで待つ・全台の結果の表）
4. `bench`
5. 既存の`logs`・`profile`・`tools`を`tasks/`へ移す
6. `snapshot`・`nginx`・`reboot`を包む
7. README（タスクの一覧と成熟度・最初の手順）と、大会repoのひな形（`templates/`）

## 8. 本番の後に回してよいもの

- 配った設定（`server/`）と実機の実物の差の照合（`status`の拡張）
- 複数台への並行のdeploy
- 自動のrollback（今は前のcommitを配り直す）
- 実機の全体のprovision（パッケージ・カーネルの設定など）
- チームの共通の場所（チャットなど）への自動の投稿

## 9. 小さな実地テストで確かめる仮説

| 仮説 | 確かめ方 |
|---|---|
| H1 2台のPCから同じ台へ、SSHのpushで配っても、所有者の調整は最初の1回で足りる | 2つの手元から、同じ台へ順にpushして配る |
| H2 実機側のlockで、2つのPCからの同時のdeployの片方が止まる | 2つの手元から同時に`tk deploy` |
| H3 `tk status`が、3台で10秒以内に返る | 3台で実行して時間を測る |
| H4 準備ができるまで待つ確認で、deployの成否の表示が正しくなる | dockerのアプリで`tk deploy`し、表示とappの応答を比べる |
| H5 チームの各自の手元に、Ansibleを入れる負担が問題にならない | 各メンバーに、`contest-ops`の`validate`を手元で通してもらう |
| H6 dockerのアプリで、buildの重複をなくせる（unitの`--build`に任せる、またはbuildの指定を空にする） | 両方の設定で`tk deploy`し、時間と結果を比べる |

## 10. 未決の論点

- 台の名前そのもの（3章）
- `contest-ops/`の使わないタスクを消すか残すか（2.1）
- チームの共通の場所をどこにするか（原則7。大会ごとに決める）
- 原則8の基準が、早い共有を妨げないか（`status`と`deploy`を作る過程で確かめる）
