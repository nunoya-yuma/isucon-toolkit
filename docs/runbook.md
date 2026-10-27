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

アプリのルート（例: `/home/isucon/private_isu`）をリポジトリにし、設定ファイルは `server/` 以下に絶対パスと同じ構造でコピーする。デプロイ時に `server/etc/...` を `/etc/...` へそのまま戻せるようにするため。

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
sudo cp /etc/systemd/system/<使う言語のサービス>.service server/etc/systemd/system/
sudo cp /home/isucon/env.sh server/home/isucon/
sudo chown -R isucon:isucon server

sudo -u isucon git add -A && sudo -u isucon git status --short  # バイナリや巨大ファイルが混ざっていないか確認
sudo -u isucon git commit -m "chore: import initial state from server"
```

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

`scripts/deploy.sh` を大会リポジトリのルートにコピーし、先頭の per-contest settings を書き換える。以降は「手元で編集 → push → `./deploy.sh <ssh-host> [branch]`」で反映する。

- サーバー上に未コミットの変更があると中断する（サーバーで直接いじった変更を消さないため）。
- `server/` 以下は中身が変わったファイルだけ配置し、変わった種類に応じて `daemon-reload` / mysql 再起動 / nginx reload（`nginx -t` 付き）をする。
- アプリは毎回ビルドして再起動し、最後に `GET /` のステータスを表示する。
- 途中で失敗すると、設定ファイルは配置済みのまま reload されないことがある。直して再度デプロイすれば差分として検出される。
- リポジトリ直下の `sql/*.sql` を毎回 `DB_NAME` に流す。インデックス追加の再実行で出る `Duplicate key name` は適用済みとみなして無視し、それ以外のエラーで中断する。

### スキーマ変更（インデックス追加など）の置き場所

最初に `/initialize` の実装を読んで決める。

- 行の削除・更新だけでテーブルを作り直さない（例: private-isu）→ `sql/` に置き、deploy で流す。
- スキーマの SQL（`DROP TABLE` / `CREATE TABLE`）を流し直す → 手で足したインデックスはベンチのたびに消えるので、そのスキーマファイル自体に書き足す。

## 5. 計測の準備

```bash
./install-tools.sh <ssh-host>   # alp と pt-query-digest
```

`server/` の設定を編集してデプロイする。

- nginx: `nginx.conf` に alp の README にある LTSV の `log_format` を追加し、`access_log ... ltsv;` にする。
- MySQL: `mysqld.cnf` で `slow_query_log = 1`、`slow_query_log_file`、`long_query_time = 0`（全クエリを記録）。

以降は毎回この流れで計測する。`logs.sh` の `ALP_MATCHING` は大会の URI に合わせて書き換える。

```bash
./logs.sh clear <ssh-host>
# ベンチマーク実行
./logs.sh analyze <ssh-host>
```

最終ベンチマークの前にはログ出力を止め、プロファイラも外す（ログの書き込みやプロファイラの処理でスコアが下がるため）。

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

// main() の先頭
http.DefaultServeMux.Handle("/debug/fgprof", fgprof.Handler())
go func() { log.Println(http.ListenAndServe("localhost:6060", nil)) }()
```

- アプリ本体が `http.DefaultServeMux` で待ち受けている場合は、`/debug/` が nginx 経由で外に出てしまう。その場合はアプリ用に別の mux を使う。
- ベンチマークを開始した直後に `./profile.sh <ssh-host> [seconds]` を実行する（2 種類を同時に取り、`logs/<timestamp>/` に保存する）。
- 手元で `go tool pprof -http=: logs/<timestamp>/fgprof.pprof` を実行し、ブラウザで見る。手元にも Go が必要（sudo なしなら go.dev/dl の tarball を `~/.local` に展開して PATH に足す）。Graph 表示には graphviz も要るが、Flame Graph は不要。
- 行単位の表示（Source）は、プロファイル中のサーバー上のパスを手元のリポジトリに読み替える: 大会リポジトリのルートで `go tool pprof -http=: -trim_path=<アプリのルート> -source_path=. <file>`。手元をプロファイルを取ったときと同じコミットにしておかないと行がずれる。
- fgprof は待機しているだけの goroutine（プロファイラ自身や接続待ちなど）も数えるので、合計は 100% を大きく超える。`main.` のハンドラ以下に絞って（起動時に `-focus='^main\.'`、またはブラウザの検索欄に `^main\.` を入れて REFINE → Focus）、`database/sql` の待ちがどこから来ているかを見る。
