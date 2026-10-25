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
