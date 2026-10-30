# isuginx の採用判断と nginx 設定の適用

参照した [mazrean/isuginx](https://github.com/mazrean/isuginx) の commit は
`25a4925a8aff7599e209f4b7617f27d2647929a6`。
本基盤では、現行版をサーバー上で無条件に実行する処理は追加していません。
設定項目を参考にし、対象 nginx とアプリに適した変更だけを明示的なテンプレートで適用します。

## ソースから確認した動作

`main.go` は既存の設定を include 付きで解析し、設定変更後にファイルへ書き戻します。
対象項目を個別選択するオプション、dry-run、`nginx -t`、reload、失敗時の復元処理はありません。
`-file` と `-access-log` で設定ファイルとログ出力先を指定できます。

| 変更 | この基盤での判断 |
| --- | --- |
| `worker_rlimit_nofile=4096`、`worker_connections=1024` | 固定値をそのまま採用しない。既存値、systemd の FD 制限、必要な同時接続数から決める |
| `sendfile`、`tcp_nopush`、`tcp_nodelay` | 既存値を確認して採用候補とする。既に有効なら変更不要 |
| `keepalive_timeout`、`keepalive_requests` | ベンチで効果とメモリ使用量を比較する候補 |
| `open_file_cache` | 静的ファイルの更新・初期化時の挙動を確認して採用する候補 |
| `proxy_buffers`、`proxy_buffer_size` | レスポンスサイズと接続数に応じて判断。固定値の一括適用はしない |
| kataribe 用のログ形式・出力先 | 既存の LTSV / alp 計測と切り離して選択。計測形式を勝手に置き換えない |
| `http2_max_requests`、`http2_recv_timeout` | 新規採用しない。nginx 1.19.7 以降では obsolete |
| `proxy_cache_path`、`proxy_temp_path` とディレクトリ作成 | 必要な場合だけ大会別設定に追加。既存の同名キャッシュ領域やパスを確認する |
| TLS プロトコル変更 | 性能設定と分離し、既存の証明書・TLS 要件を維持する |

HTTP/2 の旧ディレクティブの代替は、それぞれ `keepalive_requests` と `client_header_timeout`。
根拠: [nginx 公式 HTTP/2 ドキュメント](https://nginx.org/en/docs/http/ngx_http_v2_module.html)。
`proxy_cache_path` の指定だけではレスポンスキャッシュは有効になりません。
根拠: [nginx 公式 proxy モジュール](https://nginx.org/en/docs/http/ngx_http_proxy_module.html#proxy_cache)。

## 改善したスクリプト

[`scripts/nginx_tune.py`](scripts/nginx_tune.py) と Ansible の `nginx_tuning` ロールを追加しています。
Python 標準ライブラリだけを使い、isuginx のインストールは不要です。

- root・events・http の直下にある、選択したディレクティブだけを更新する。
- コメント・server/location・TLS・ログ設定・include 文と include 先のファイルを保持する。
- 元ファイルと `nginx -T` による有効設定、候補ファイル、差分、チェックサムを保存する。
- 元ファイルと同じディレクトリで候補を生成し、対象サーバーの nginx で `-t -c` を実行する。
- 検証成功後に設定を切り替え、reload と任意の HTTP 確認を実行する。
- reload・HTTP 確認の失敗時は元ファイルを戻し、再検証・reload を試みる。
- 変更がなければ reload しない。nginx 操作用のリモートロックも取得する。
- メイン設定の symlink と、通常の所有者・グループ・パーミッションを保持する。

`configure` とは別の専用処理で、アプリの `deploy` や `rollback` には影響しません。

## 準備

`provisioning/contest-ops` を作業ディレクトリにします。

```bash
mkdir -p .local
cp config/nginx.example.yml .local/nginx.yml
# .local/nginx.yml の変更項目を選択する
```

inventory は既存のインスタンス1つ・3つの構成のものを使います。対象は `proxy` グループだけです。
接続確認は他の操作と同様に行い、proxy ホストには Python 3 と nginx、reload の権限が必要です。

```yaml
ops_nginx_directives:
  http:
    sendfile: 'on'
    tcp_nopush: 'on'
    tcp_nodelay: 'on'
    keepalive_requests: '10000'
```

値は必ず文字列にします。既定では変更項目は空です。
接続数や FD 上限は、既存値と必要量を調べてから明示してください。
`server_tokens`、`open_file_cache`、`proxy_buffers`、`proxy_buffer_size` なども選択できます。
TLS・ログ形式・proxy cache・旧 HTTP/2 ディレクティブは変更対象にできません。

## 差分確認と適用

```bash
# 差分を保存して nginx -t を実行。実設定の切替・reload は行わない
./run.sh nginx-plan -i .local/hosts.yml -c .local/nginx.yml

# 保存された nginx-changes.diff と nginx-candidate.conf を確認してから適用
./run.sh nginx-apply -i .local/hosts.yml -c .local/nginx.yml
```

各操作で元設定を保存するため、事前の `snapshot` は必須ではありません。
`snapshot` は nginx の include 先も含む初動の一式保存に引き続き利用できます。
`plan` もサーバーに接続し、一時候補とバックアップを作成します。接続不要の dry-run ではありません。
`apply` はその実行時点の元設定から再生成するため、plan 後に設定が変わった場合は再度 plan してください。

保存先は以下です。実行終了時に run ID と保存先を表示します。

```text
サーバー: /var/lib/contest-ops/nginx/<run ID>/
実行元:   .local/artifacts/<run ID>/<ホスト名>/nginx-*
```

保存内容は `original.conf`、`candidate.conf`、`effective-before.txt`、`changes.diff`、`manifest.json`。
実行元では `nginx-` がファイル名の先頭に付き、`nginx-result.json` にエラーと復旧結果も保存します。
設定には秘密情報を含むことがあるため、ファイルは `0600`、新規バックアップディレクトリは `0700` で作成します。
保存した内容や diff は既定のコンソール出力に含めません。

## 任意の HTTP 確認

nginx の reload 後に確認したい URL があればコマンドを指定します。
確認コマンドが失敗した場合も、設定を元に戻して reload します。

```yaml
ops_nginx_health_argv:
  - curl
  - --fail
  - --silent
  - --show-error
  - --resolve
  - example.isucon.test:443:127.0.0.1
  - https://example.isucon.test/
```

URL とドメインは対象大会に合わせます。`/api/initialize` はヘルスチェックに使用しません。

## 適用前の設定へ戻す

成功した `nginx-apply` の run ID を指定します。

```bash
./run.sh nginx-restore -i .local/hosts.yml -c .local/nginx.yml \
  -e ops_nginx_restore_id=20261029T000000Z-example
```

復元候補にも `nginx -t` を実行し、復元後に reload と設定した HTTP 確認を実行します。
適用後にメイン設定が別途変更されていた場合は、チェックサムが一致しないため上書きを拒否します。
復元は同じホストのバックアップを使用します。複数 proxy のうち一部だけ変更した場合は、
そのホストだけの inventory を指定してください。

## 設定と制限

| 変数 | 既定値・用途 |
| --- | --- |
| `ops_nginx_config_path` | `/etc/nginx/nginx.conf` |
| `ops_nginx_backup_root` | `/var/lib/contest-ops/nginx` |
| `ops_nginx_argv` | `[nginx]`。nginx コマンドと必要な共通引数 |
| `ops_nginx_reload_argv` | `[systemctl, reload, nginx]` |
| `ops_nginx_health_argv` | 空。指定した場合だけ実行 |
| `ops_nginx_directives` | 空。選択したコンテキスト・ディレクティブと値 |
| `ops_nginx_restore_id` | 復元元の成功した apply の run ID |

main ファイルに明示された root・events・http の直下だけを編集します。
events/http を別ファイルで定義する構成や、選択項目が同じコンテキストで重複する構成は、
自動で展開・整理しません。既存の include による重複などは nginx 自身の検証で拒否されます。

復元対象はメイン設定だけです。include 先・証明書・DB・アプリは書き換えません。
複数 proxy は順番に処理し、全ホストをまとめた一括トランザクションにはなりません。
設定を復元できても nginx の再 reload が失敗した場合はエラーとして記録します。
SSH 切断・強制終了・電源断など、処理自体が中断された場合の自動復元は保証しません。

効果と動作整合性は、HTTPS・静的ファイル・API の確認とポータルでのベンチ比較で評価します。
ローカルテストでは nginx コマンドを模したテスト用プロセスを使い、差分生成、所有権・symlink の保持、
構文検証・reload・HTTP 確認の失敗時の復旧、復元時の競合拒否、Ansible 経由の成果物回収を検証しています。
対象サーバーの実 nginx による適用・性能検証は別途必要です。
