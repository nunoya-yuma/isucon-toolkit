# Runbook

競技開始直後から順に実行する手順。`<...>` は大会ごとに置き換える。

## 1. 言語の切り替え

初期状態で動いている実装を止め、使う言語の実装を起動する。

```bash
# サービス名を確認する
systemctl list-units --type=service --state=running | grep -i isu

sudo systemctl disable --now <初期言語のサービス>   # 例: isu-ruby
sudo systemctl enable --now <使う言語のサービス>    # 例: isu-go
```

- `--now` だけでなく `disable` / `enable` もする。競技後の再起動試験で、意図した実装が自動起動するようにするため。
- 切り替え後、`systemctl is-active` / `is-enabled` と `curl -s -o /dev/null -w "%{http_code}\n" http://localhost/` で動作を確認する。

## 2. サーバーの状態を Git に取り込む

アプリのルート（例: private-isu は `/home/isucon/private_isu`、ISUCON14 は `/home/isucon/webapp`）をリポジトリにし、設定ファイルは `server/` 以下に絶対パスと同じ構造でコピーする。デプロイ時に `server/etc/...` を `/etc/...` へそのまま戻せるようにするため。

```bash
cd <アプリのルート>
sudo -u isucon git init -b main
sudo -u isucon git config user.name <name>
sudo -u isucon git config user.email <email>
# .gitignore: ベンチマーカー、使わない言語の実装、ビルド成果物、*.log を除外

sudo -u isucon mkdir -p server/etc/nginx/sites-available server/etc/mysql/mysql.conf.d server/etc/systemd/system server/home/isucon
sudo cp /etc/nginx/nginx.conf server/etc/nginx/
sudo cp /etc/nginx/sites-available/<site>.conf server/etc/nginx/sites-available/  # sites-enabled はシンボリックリンクなので実体を取る
sudo cp /etc/mysql/mysql.conf.d/mysqld.cnf server/etc/mysql/mysql.conf.d/
sudo cp /etc/systemd/system/<使う言語のサービス>.service server/etc/systemd/system/  # 補助のサービスも（例: ISUCON14 の isuride-matcher）
sudo cp /home/isucon/env.sh server/home/isucon/
sudo chown -R isucon:isucon server

sudo -u isucon git add -A && sudo -u isucon git status --short  # バイナリや巨大ファイルが混ざっていないか確認
sudo -u isucon git commit -m "chore: import initial state from server"
```

### `tk`を使う場合（3・4の代わり）

`tk deploy`は、実機に鍵を置かずに、手元からSSHで配る。そのため、3（deploy key）と4（`toolkit.env`）の代わりに、次を行う。**この節の手順は、まだ練習で通していない（未検証）。**

1. 上の手順で、1台目のアプリのルートにcommitを作る（動いているデータは`.gitignore`で除く）。
2. そのcommitを手元へ取り込み、GitHubへpushする（実機に鍵を置かない）。

```bash
# 手元
git clone --upload-pack='sudo -n -u isucon git-upload-pack' <台>:<アプリのルート> <大会repo>
cd <大会repo>
git remote rename origin <台>
git remote add origin git@github.com:<owner>/<repo>.git
git push -u origin main
```

3. 各台で、`tk`の記録の領域と受信用repoを作る（READMEの「実機の準備」）。
4. 2台目以降のアプリのルートを、同じcommitのcloneにする（中身が1台目と同じ前提）。

```bash
# 手元
git push --receive-pack='sudo -n -u isucon git-receive-pack' <台>:/var/lib/tk-recv.git main:refs/tk/incoming/init
# 実機
cd <アプリのルート>
sudo -u isucon git init -b main
sudo -u isucon git fetch /var/lib/tk-recv.git refs/tk/incoming/init
sudo -u isucon git reset FETCH_HEAD     # 作業中のファイルは変えずに、HEADだけをそのcommitにする
sudo -u isucon git status --short       # 何も出なければ、中身は1台目と同じ
```

`git status --short`に何か出たら、その台だけの違いがある。差分を退避してから扱いを決める（原則3）。

5. 大会repoの直下に`tk.env`を置き（`tools/toolkit/templates/tk.env.example`から）、`tk status`で全台が見えることを確かめる。

## 3. GitHub のプライベートリポジトリへ push する

サーバーには個人の鍵を置かず、そのリポジトリ専用の書き込み可能な deploy key を使う。

```bash
# 手元
gh repo create <owner>/<repo> --private

# サーバー: isucon ユーザーの鍵を作り、公開鍵を手元に取ってくる
sudo -u isucon bash -c 'mkdir -p ~/.ssh && chmod 700 ~/.ssh && ssh-keygen -q -t ed25519 -N "" -f ~/.ssh/id_ed25519 && cat ~/.ssh/id_ed25519.pub'

# 手元
gh repo deploy-key add <公開鍵ファイル> --repo <owner>/<repo> --allow-write --title "<server> (isucon)"

# サーバー
sudo -u isucon bash -c '
ssh-keyscan -t ed25519 github.com >> ~/.ssh/known_hosts
git remote add origin git@github.com:<owner>/<repo>.git
git push -u origin main'
```

## 4. デプロイスクリプトを用意する

`scripts/` の中身を大会リポジトリのルートにコピーし、`toolkit.env` を書き換える。以降は「手元で編集 → push → `./deploy.sh <ssh-host> [branch]`」で反映する。

- サーバー上に未コミットの変更があると中断する（サーバーで直接いじった変更を消さないため）。
- `server/` 以下は中身が変わったファイルだけ配置し、変わった種類に応じて `daemon-reload` / mysql 再起動 / nginx reload（`nginx -t` 付き）をする。ユニットファイルか、`EnvironmentFile` で読み込んでいるファイル（`env.sh` など）が変わったユニットは、動いていれば再起動する。
- アプリは毎回ビルドして再起動し、最後に `HEALTH_URL` のステータスを表示する。`http://localhost/` は nginx の default_server に当たってアプリに届かないことがある（ISUCON14）ので、nginx がアプリへ振り分ける URL にする。
- 途中で失敗すると、設定ファイルは配置済みのまま reload されないことがある。直して再度デプロイすれば差分として検出される。
- リポジトリ直下の `migrations/*.sql` を毎回 `DB_NAME` に流す。大会側の `sql/`（テーブルを作り直すスキーマを含むことがある）と混ざらないよう、別の名前にしている。インデックス追加の再実行で出る `Duplicate key name` は適用済みとみなして無視し、それ以外のエラーで中断する。

### スキーマ変更（インデックス追加など）の置き場所

最初に `/initialize` の実装を読んで決める。

- 行の削除・更新だけでテーブルを作り直さない（例: private-isu）→ `migrations/` に置き、deploy で流す。
- スキーマの SQL（`DROP TABLE` / `CREATE TABLE`）を流し直す（例: ISUCON14 の `sql/init.sh`）→ 手で足したインデックスはベンチのたびに消えるので、そのスキーマファイル自体に書き足す。

## 5. 計測の準備

```bash
./install-tools.sh <ssh-host>   # alp と pt-query-digest
```

`server/` の設定を編集してデプロイする。

- nginx: `nginx.conf` に alp の README にある LTSV の `log_format` を追加し、`access_log ... ltsv;` にする。
- MySQL: `mysqld.cnf` で `slow_query_log = 1`、`slow_query_log_file`、`long_query_time = 0`（全クエリを記録）。

以降は毎回この流れで計測する。`toolkit.env` の `ALP_MATCHING` は大会の URI に合わせて書き換える（アプリのルーティング定義から ID を含むパスを拾う）。

```bash
./logs.sh clear <ssh-host>
# ベンチマーク実行
./logs.sh analyze <ssh-host>
```

最終ベンチマークの前にはログ出力を止め、プロファイラも外す（[7. 最終ベンチマークの前](#7-最終ベンチマークの前)）。

### Go アプリのプロファイル

標準の pprof（CPU を使っている処理）と fgprof（DB 待ちなどを含む実時間）を `localhost:6060` で公開する。

```bash
# 依存を追加する。手元に Go がなければサーバーで実行し、go.mod / go.sum をコミット・push してからデプロイする
sudo -u isucon bash -c 'source /home/isucon/env.sh && cd <ビルドディレクトリ> && go get github.com/felixge/fgprof@latest'
```

```go
import (
	_ "net/http/pprof"

	"github.com/felixge/fgprof"
)

// main() の先頭。env.sh の ISUCON_PPROF=1 で有効にし、最終ベンチマークの前は消すだけで止められるようにする
if os.Getenv("ISUCON_PPROF") == "1" {
	http.DefaultServeMux.Handle("/debug/fgprof", fgprof.Handler())
	go func() { log.Println(http.ListenAndServe("localhost:6060", nil)) }()
}
```

- アプリ本体が `http.DefaultServeMux` で待ち受けている場合は、`/debug/` が nginx 経由で外に出てしまう。その場合はアプリ用に別の mux を使う。
- ベンチマークを開始した直後に `./profile.sh <ssh-host> [seconds]` を実行する（2 種類を同時に取り、`logs/<timestamp>/` に保存する）。
- 手元で `go tool pprof -http=: logs/<timestamp>/fgprof.pprof` を実行し、ブラウザで見る。手元にも Go が必要（sudo なしなら go.dev/dl の tarball を `~/.local` に展開して PATH に足す）。Graph 表示には graphviz も要るが、Flame Graph は不要。
- 行単位の表示（Source）は、プロファイル中のサーバー上のパスを手元のリポジトリに読み替える: 大会リポジトリのルートで `go tool pprof -http=: -trim_path=<アプリのルート> -source_path=. <file>`。手元をプロファイルを取ったときと同じコミットにしておかないと行がずれる。
- fgprof は待機しているだけの goroutine（プロファイラ自身や接続待ちなど）も数えるので、合計は 100% を大きく超える。`main.` のハンドラ以下に絞って（起動時に `-focus='^main\.'`、またはブラウザの検索欄に `^main\.` を入れて REFINE → Focus）、`database/sql` の待ちがどこから来ているかを見る。

## 6. 複数台に分ける

ベンチマーカーが負荷をかけるのは 1 台だけのことが多い（例: ISUCON14 はポータルで選んだ 1 台の 443 番）。まずは DB を別のサーバーに移す。以下は 1 台目に nginx とアプリ、2 台目に MySQL を置く例。

### 2 台目以降に大会リポジトリを入れる

サーバーごとに deploy key を作る（秘密鍵をサーバー間でコピーしないため）。アプリのルートには初期状態のファイルがあるので、`clone` ではなく取り込んだ状態に上書きする。

```bash
# サーバー: 鍵を作り、公開鍵を手元に取ってくる（手順 3 と同じ）
sudo -u isucon bash -c 'mkdir -p ~/.ssh && chmod 700 ~/.ssh && ssh-keygen -q -t ed25519 -N "" -f ~/.ssh/id_ed25519 && cat ~/.ssh/id_ed25519.pub'

# 手元
gh repo deploy-key add <公開鍵ファイル> --repo <owner>/<repo> --allow-write --title "<server> (isucon)"

# サーバー
sudo -u isucon bash -c '
cd <アプリのルート>
ssh-keyscan -t ed25519 github.com >> ~/.ssh/known_hosts
git init -b main && git config user.name <name> && git config user.email <email>
git remote add origin git@github.com:<owner>/<repo>.git
git fetch origin && git reset --hard origin/main && git branch -u origin/main'
```

```bash
./install-tools.sh <ssh-host>   # DB のサーバーにも pt-query-digest を入れる
```

### サーバーごとの設定

`server/` は全サーバー共通で、`hosts/<ssh-host>/` に同じ構造で置いたファイルがそのサーバーでだけ優先される（例: アプリのサーバーの `hosts/<ssh-host>/home/isucon/env.sh` で DB の接続先を変える）。deploy.sh は 1 台ずつ実行する。

```bash
for h in <db-host> <app-host>; do ./deploy.sh "$h"; done
```

自動起動を無効にしたサービスは、deploy.sh が再起動しない（アプリのビルド・再起動、mysql の再起動、`migrations/` の適用を飛ばす）。役割の切り替えは `systemctl disable --now` で行う。

### DB を移す手順

順番を間違えるとアプリが止まる。

1. `server/` の `mysqld.cnf` で `bind-address = 0.0.0.0` にする。アプリが使う MySQL ユーザーの接続元が `'%'` か確認する（ISUCON14 は初期状態で `'isucon'@'%'`）。
2. `systemctl list-dependencies --reverse mysql.service` で mysql に依存しているユニットを洗い出し、アプリのサーバーで動かすものから `Requires=mysql.service` を外す（ISUCON14 はアプリと payment_mock にある）。残すと、mysql を止めたときにそのユニットも止まり、再起動時にはそのユニットが mysql を起動してしまう。
3. アプリのサーバーの `hosts/<app-host>/home/isucon/env.sh` で、DB の接続先を DB のサーバーのプライベート IP にする。`EnvironmentFile` は行末のコメントを値に含めてしまうので、コメントは別の行に書く。
4. DB のサーバーでアプリを止めてからデプロイする: `sudo systemctl disable --now <アプリのサービス> <補助のサービス>` → `./deploy.sh <db-host>`。
5. アプリのサーバーをデプロイし、動作確認の URL が通ってから mysql を止める: `./deploy.sh <app-host>` → `sudo systemctl disable --now mysql`。
   最後にサーバーを再起動し、mysql が止まったまま、アプリが動いていることを確かめる（追試で再起動されるため）。
6. 計測は `./logs.sh clear <app-host> <db-host>` / `./logs.sh analyze <app-host> <db-host>` で、nginx のログとスロークエリログを別々のサーバーから集める。

サーバー間の通信は、プライベート IP で行う。通らなければセキュリティグループを確認する（同じグループからの通信を許可するルールがあれば通る）。`nc -zv <DB のプライベート IP> 3306` で確かめる。

## 7. 最終ベンチマークの前

競技終了後の追試では、全サーバーを再起動してからベンチマークを流し、書き込んだデータが再起動後も読めるかを確かめる（ISUCON14 では最終スコアの 75% 以下が続くと失格）。最後に流したベンチマークが最終スコアになるので、片付けと確認を済ませてから流す。

1. ログ出力とプロファイラを止めてデプロイする（ログの書き込みやプロファイラの処理でスコアが下がるため）。
   - nginx: `access_log off;`
   - MySQL: `slow_query_log = 0`
   - プロファイラ: `env.sh` の `ISUCON_PPROF=1` を消す
2. `./final-check.sh <host>...` で全サーバーを確かめる。サーバーごとに、未コミットの変更がないこと、push 済みの最新がデプロイ済みであること、自動起動が有効なサービスが動いていて失敗したユニットがないこと、ログとプロファイラが止まっていること、アプリが応答することを見る。
3. 全サーバーを再起動し（`sudo systemctl reboot`）、`./final-check.sh <host>...` をもう一度通す。
4. 再起動後にベンチマークを流し、pass してスコアが落ちていないことを確かめる。これを最終スコアにする。
