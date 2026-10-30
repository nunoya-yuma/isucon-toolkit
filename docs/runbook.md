# Runbook

競技の開始から終わりまでを、時間の順に並べた手順。`<...>`は大会ごとに置き換える。各コマンドの意味と結果の読み方は[README](../README.md)、振る舞いの詳細は[tasks.md](tasks.md)にある。

変更を加えたら、そのたびにチームのDiscordの決めた場所へ1行で書く（[原則7](principles.md)）。`tk`の最後の1行は、そのまま貼れる。

## 1. 開始直後

1. **当日マニュアルを読む**。特に、変更してはいけないファイル・サービス・ユーザー（環境確認の仕組みなど）、追試の条件、`/initialize`の時間制限。
2. **SSHの入口を作る**。aliasは運営のEC2のNameタグと同じ文字列にする（Nameタグは変えない。運営の環境確認が前提にしていることがある）。書き方の例はREADMEの準備の3。
3. **toolkitを手元に置く**。大会repoはまだ無い（2章の4でできる）ので、まずworkspaceの直下などに固定SHAでcloneしておき、2章の1の保全はそこから動かす。大会repoができたら、`tools/toolkit/`へ複写する（READMEの準備の1）。
4. **自動の更新を確かめる**。練習（2026-10-30）では、自動の更新（`unattended-upgrade`）が、競技の時間の中で3つのインスタンスのDockerのパッケージを上げた。再起動したインスタンスから新しいdaemonが動き出し、古いcomposeのプラグインと合わずに、アプリが起動しなくなった。追試は全インスタンスの再起動の後に行われるので、そのまま失格につながりうる。

```bash
systemctl list-timers --all | grep -E 'apt|unattended'
tail -n 30 /var/log/apt/history.log
docker version 2>/dev/null | grep -E 'Version|API version'
```

   止めるかどうかは、大会のルールで禁じられていないかを確かめてから、チームで決める。止めた場合も、1行で書く。
5. **言語を切り替える**（必要なら）。`disable`・`enable`まで行い、再起動の後も意図した実装が起動するようにする。

```bash
systemctl list-units --type=service --state=running | grep -i isu
sudo systemctl disable --now <初期言語のサービス>
sudo systemctl enable --now <使う言語のサービス>
```

## 2. 保全とGit化

1. **原本を保全する**（読取りだけ）：1章の3で手元に置いたtoolkitの`contest-ops/run.sh inspect`と`snapshot`（[contest-ops/INITIAL_SETUP.md](../contest-ops/INITIAL_SETUP.md)）。nginxの`sites-available`など、採るパスを漏らさない。
2. **1つ目のインスタンスのアプリのルートで、`git add`の前に`.gitignore`を書く**。使わない言語の実装、buildの成果物、`*.log`、動いているデータ（DBファイル・lock・アップロード・大きな初期データ）、秘密値を除く。運営が置いた`.gitignore`があれば残して、その下に足す（`templates/gitignore.example`を参考に）。先に大きいものを見ておく。

```bash
cd <アプリのルート>
ls -la && du -sh * | sort -h | tail -20   # 大きいもの・使わない実装を探す
cat .gitignore 2>/dev/null                # 運営のものがあれば残す
```

3. **設定を`server/`へ複写し、commitする**。設定は`server/`の下に実機の絶対パスのまま複写する（[原則4](principles.md)）。下の例は`ubuntu`でログインした場合。`isucon`でログインしているときは、`sudo -u isucon`を付けずにそのまま実行する。

```bash
cd <アプリのルート>
sudo -u isucon git init -b main
sudo -u isucon mkdir -p server/etc/nginx/sites-available server/etc/mysql/mysql.conf.d server/etc/systemd/system
sudo cp /etc/nginx/nginx.conf server/etc/nginx/
sudo cp /etc/nginx/sites-available/<site>.conf server/etc/nginx/sites-available/   # sites-enabled は symlink なので実体を取る
sudo cp /etc/mysql/mysql.conf.d/mysqld.cnf server/etc/mysql/mysql.conf.d/
sudo cp /etc/systemd/system/<使う言語のサービス>.service server/etc/systemd/system/
sudo chown -R isucon:isucon server
sudo -u isucon git add -A && sudo -u isucon git status --short   # 載るものだけが出るか
sudo -u isucon git status --short --ignored | grep '^!!'         # 除いたものが意図どおりか
sudo -u isucon git -c user.name=<name> -c user.email=<email> commit -m "chore: import initial state from server"
```

4. **そのcommitを手元へ取り込み、GitHubへpushする**（実機に鍵を置かない）。

```bash
git clone --upload-pack='sudo -n -u isucon git-upload-pack' <インスタンス>:<アプリのルート> <大会repo>
cd <大会repo>
git remote rename origin <インスタンス>
git remote add origin git@github.com:<owner>/<repo>.git
git push -u origin main
```

5. **`tk`を用意する**：READMEの「準備」の1〜4（toolkitの複写・ひな形・インスタンスの名前・記録の領域と受信用repo）。
6. **2つ目以降のインスタンスのアプリのルートを、同じcommitのcloneにする**。アプリのファイルと動いているデータは変えず、1つ目のインスタンスで足した管理用のファイル（`.gitignore`・`server/`など）だけを補う。

```bash
# 手元
git push --receive-pack='sudo -n -u isucon git-receive-pack' <インスタンス>:/var/lib/tk-recv.git main:refs/tk/incoming/init
```

```bash
# 実機（このまとまりを1回で実行する。既に .git があれば何も変えずに止まる）
cd <アプリのルート> && if sudo -u isucon test -e .git; then
  echo "NG: 既に .git があります。元の HEAD・branch・index を保全してから、別に扱ってください" >&2
else (
  set -e   # 途中で失敗したら、このまとまりの残りを実行しない（今のshellは閉じない）
  sudo -u isucon git init -b main
  sudo -u isucon git fetch /var/lib/tk-recv.git refs/tk/incoming/init
  sudo -u isucon git reset FETCH_HEAD     # 作業中のファイルは変えずに、HEADだけをそのcommitにする
  echo "--- このインスタンスに無いファイル（管理用のファイルだけであることを確かめる）"
  sudo -u isucon git ls-files --deleted
)
  rc=$?   # || を付けると中の set -e が効かなくなるので、終了コードを後で見る
  if [ "$rc" -ne 0 ]; then echo "NG: init の途中で失敗しました（rc=$rc）。上の出力を確かめてください" >&2; fi
fi
```

```bash
# 実機：上の一覧が管理用のファイルだけなら、無いファイルだけを補う（既存のファイルは上書きしない）
cd <アプリのルート>
sudo -u isucon git ls-files -z --deleted | sudo -u isucon xargs -0 -r git checkout --
sudo -u isucon git status --short       # 何も出なければ、中身は1つ目のインスタンスと同じ
```

   `git ls-files --deleted`にアプリのファイルが含まれていたら、補う前に止める。`git status --short`に`M`が出たら、そのインスタンスだけの違いがある。`??`が出たら、動いているデータかもしれない（`.gitignore`へ足すかを決める）。どちらも、差分を退避してから扱いを決める（[原則3](principles.md)）。
7. **`tk status`で全インスタンスが見えることを確かめる**。まだ`tk deploy`をしていないので、各インスタンスの「最後のdeploy」は「記録なし」でよい。
8. **`BUILD_CMD`を確かめる**：app役の1つのインスタンスに、わざとコンパイルを失敗させたcommit（使い捨てのbranch）を`tk deploy`し、`failed@restart`になることを見る。記録の`recovery`で戻し、同じ元のcommitをもう一度`tk deploy`して記録をそろえる。dockerのアプリでは、`docker compose build`がコンパイルしない作りがある（起動時に`go run`するなど）。その場合は、buildで失敗せず`ready`まで進むので、`BUILD_CMD`にコンパイルの手順を足す。
9. **app役の全インスタンスに、成功したdeployの記録を作る**：初期のcommit（`main`）を`tk deploy main`でapp役の全インスタンスへ配る。8で試したインスタンス以外は、ここで初めて記録ができる。
10. **初期構築の完了の判定**：`tk status`で、全インスタンスが見え、未commitの変更が無く、app役のインスタンスが「一致」・稼働になっている。Discordに1行で書く。

## 3. 計装

計装は、まだ`tk`へ移していないので、`tools/toolkit/scripts/`を使う。設定は`tools/toolkit/scripts/toolkit.env`（READMEの「移行前の入口」）。

```bash
tools/toolkit/scripts/install-tools.sh <インスタンス>   # alp と pt-query-digest
```

設定は`server/`の下を直し、app役のインスタンスへは`tk deploy`で配る。DBのインスタンス（appを動かさないインスタンス）へは、5章の方法で配る。

- nginx：`log_format`にalpのLTSVを足し、`access_log ... ltsv;`にする。
- MySQL：`slow_query_log = 1`、`slow_query_log_file`、`long_query_time = 0`。
- Goのprofile：標準のpprofとfgprofを`localhost:6060`で出す。環境変数（例：`ISUCON_PPROF=1`）で有効にし、最後に消すだけで止められるようにする。アプリが`http.DefaultServeMux`で待ち受けている場合は、`/debug/`が外に出ないよう別のmuxを使う。

```go
if os.Getenv("ISUCON_PPROF") == "1" {
	http.DefaultServeMux.Handle("/debug/fgprof", fgprof.Handler())
	go func() { log.Println(http.ListenAndServe("localhost:6060", nil)) }()
}
```

`toolkit.env`の`ALP_MATCHING`は、アプリのルーティングから、IDを含むパスを拾って書く。

## 4. 改善の繰り返し

1. feature branchで直し、commitする。
2. `tk deploy --plan <branch>`で宛先と差分を見る→`tk deploy <branch>`。
3. `tools/toolkit/scripts/logs.sh clear <インスタンス> [DBのインスタンス]`→（人がポータルでbenchmark）→`tools/toolkit/scripts/logs.sh analyze <インスタンス> [DBのインスタンス]`。profileは、benchmarkの開始の直後に`tools/toolkit/scripts/profile.sh <インスタンス> [秒]`。
4. 結果をDiscordに1行で書く。採用するものは、PRでmainへ入れる（[原則3](principles.md)）。

**スキーマの変更（索引など）の置き場所**は、最初に`/initialize`の実装を読んで決める。`tk deploy`は`migrations/`を流さない。

- テーブルを作り直さない（行の削除・更新だけ）大会：DDLを手で流し、1行で書き、SQLをcommitしておく。
- スキーマのSQL（`DROP TABLE`・`CREATE TABLE`）を流し直す大会：手で足した索引はbenchmarkのたびに消えるので、そのスキーマのファイル自体に書き足して`tk deploy`で配る。

## 5. 複数のインスタンスに分ける

benchmarkが負荷をかけるのは1つのインスタンスだけのことが多い。まずDBを別のインスタンスに移す。インスタンスごとに違う設定は`hosts/<インスタンスの名前>/`に置く（`server/`より優先）。

順番を間違えるとアプリが止まる。

1. DBのインスタンスの`mysqld.cnf`で、`bind-address`を内部のIPで待ち受けるようにする。アプリのMySQLのユーザーの接続元が`'%'`かを確かめる。
2. `systemctl list-dependencies --reverse mysql.service`で、mysqlに依存するunitを洗い出し、アプリのインスタンスで動かすものから`Requires=mysql.service`を外す。
3. アプリのインスタンスの`hosts/<インスタンス>/`で、DBの接続先を、DBのインスタンスの内部のIPにする。`EnvironmentFile`は行末のコメントを値に含めるので、コメントは別の行に書く。
4. DBのインスタンスでアプリを止める（`sudo systemctl disable --now <アプリのサービス>`）。appを止めたインスタンスには`tk deploy`が使えない（appのunitが無効だと止まる）ので、DBのインスタンスの設定は、commitしてから手で配り、1行で書く。

```bash
# 手元：Gitから一時ファイルへ書き出せたときだけ、退避→配置→再起動へ進む（どこかで失敗したら、そこで止まる）
f=$(mktemp) && git show <commit>:hosts/<DBのインスタンス>/etc/mysql/mysql.conf.d/mysqld.cnf > "$f" && test -s "$f" \
  && scp "$f" <DBのインスタンス>:/tmp/mysqld.cnf.new \
  && ssh <DBのインスタンス> 'set -e
       sudo cp -p /etc/mysql/mysql.conf.d/mysqld.cnf /etc/mysql/mysql.conf.d/mysqld.cnf.bak-$(date +%H%M%S)
       sudo install -m 0644 -o root -g root /tmp/mysqld.cnf.new /etc/mysql/mysql.conf.d/mysqld.cnf
       sudo systemctl restart mysql' \
  && echo "OK: placed and restarted" || echo "NG: stopped; check the output above" >&2
```
5. アプリのインスタンスへ`tk deploy`し、応答を確かめてから、アプリのインスタンスのmysqlを止める（`sudo systemctl disable --now mysql`）。
6. 全インスタンスを再起動して、構成が戻ることを確かめる（`tk reboot`→`tk final-check`）。追試では再起動されるため。

インスタンスの間の通信は内部のIPで行う。通らなければセキュリティグループを確かめる（`nc -zv <内部のIP> 3306`）。

## 6. 最後

追試では、全インスタンスを再起動してからbenchmarkを流し、再起動の後もデータが読めるかを確かめる。最後に流したbenchmarkが最終のスコアになる。

1. ログとprofilerを止めて配る（nginxは`access_log off;`、MySQLは`slow_query_log = 0`、profilerの環境変数を消す）。app役のインスタンスは`tk deploy`、DBのインスタンスは5章の手で配る方法で。
2. `tk final-check`→`tk reboot <インスタンス>...`→`tk final-check`。再起動の後にアプリが戻らなければ、そのunitのjournalを見る（練習では、自動の更新で上がったパッケージの版の不一致が原因だった。1の4）。
3. 運営の環境確認の仕組みが通ることを確かめる（当日マニュアルの方法で）。その仕組みのファイルには触らない。
4. 人がポータルで最終のbenchmarkを流し、PASSしてスコアが落ちていないことを確かめる。
