# ISUCON 共通デプロイ基盤

ローカルの変更を SSH で転送し、新しいディレクトリでビルドして、既存の systemd サービスを
再起動する Ansible と実行スクリプトです。大会固有のパス・ビルド方法・サービス名は設定で指定します。
既存の `provisioning/ansible` とは独立しており、その playbook やロールを読み込みません。

競技開始時の状態確認・元ファイルの保存・調査ツール導入は
[初動手順と採用したアイデア](INITIAL_SETUP.md) を参照してください。
isuginx を参考にした nginx 設定の選定・適用方針は
[nginx チューニングの手順](NGINX_TUNING.md) にまとめています。
`nginx-plan`・`nginx-apply`・`nginx-restore` で、選択した設定の検証・適用・復元ができます。

## 含まれるもの

```text
contest-ops/
├── run.sh                 # 実行入口。どの作業ディレクトリからでも実行可能
├── ansible.cfg
├── inventory/             # SSH 接続先・1台構成と3台構成の例
├── config/                # 大会別設定の例。Go と ISUCON14
├── playbooks/
│   ├── validate.yml       # 接続せず構文・変数を確認
│   ├── inspect.yml        # サービス・待受ポート・マシン情報を記録
│   ├── snapshot.yml       # 明示した元ソース・設定をローカルに保存
│   ├── bootstrap.yml      # 選択した調査ツールとログ保持設定を導入
│   ├── nginx.yml          # nginx の差分確認・検証・適用・復元
│   ├── deploy.yml         # 転送・ビルド・切替・再起動・HTTP 確認
│   ├── verify.yml         # サービスと HTTP、任意の TCP 疎通を確認
│   ├── rollback.yml       # 直前のアプリリリースへ切替
│   ├── configure.yml      # 明示的に指定した設定ファイル・コマンドを適用
│   └── reboot.yml         # 各ホストを順番に再起動して verify を実行
├── roles/
│   ├── ops_defaults/      # 共通の既定値
│   ├── application/       # 配置・ビルド・起動・HTTP 確認
│   ├── initial/           # 初動調査・元ファイルの保存・任意の準備
│   ├── nginx_tuning/      # nginx 操作と非公開の成果物回収
│   └── configuration/     # 任意の設定テンプレートとコマンド
├── scripts/nginx_tune.py   # Python 標準ライブラリだけで動く nginx 設定編集
└── tests/                 # ローカルで配置・ビルド失敗・復旧を検証
```

DB・nginx・監視サービスの自動インストールや自動チューニングは含めません。
それぞれの製品や大会の構成が異なるため、必要な設定だけ `configure` で明示的に適用します。
マッチャーなどの補助サービス、ベンチバイナリ、DB 初期化、データ移行も通常デプロイには含めません。

## 前提

- 実行元: Linux、Bash、Python 3、Ansible、tar、flock、realpath。
- 対象: Linux、Python 3、tar、systemd、アプリのビルドに必要な実行環境。
- アプリの systemd サービス、実行ユーザー、DB、必要なデータ・証明書などが既に存在すること。
- SSH 接続と sudo が使用できること。SSH ホスト鍵は事前に確認して known_hosts に登録すること。
- `validate` はサーバーに接続しません。接続・ビルド・起動の成否は `deploy` / `verify` で確認します。

## 最初の準備

リポジトリのルートから実行します。`.local` は Git の管理対象外です。

```bash
cd provisioning/contest-ops
mkdir -p .local
cp inventory/single.example.yml .local/hosts.yml
cp config/go.example.yml .local/contest.yml
```

3台構成なら最初のコピー元を `inventory/three.example.yml` に変更します。

### SSH とホストの役割

`.local/hosts.yml` を編集します。

| 変数 | 内容 |
| --- | --- |
| `ansible_host` | SSH 接続先 IP |
| `ansible_user` | SSH ユーザー |
| `ansible_ssh_private_key_file` | 実行元にある秘密鍵の絶対パス。`run.sh -k` でも指定可能 |
| `ansible_port` | SSH ポート。省略時は 22 |
| `ops_private_ip` | サーバー間通信用 IP。任意のテンプレートから参照するための値 |

| グループ | 1台構成 | 3台構成 |
| --- | --- | --- |
| `app` | server1 | server1, server2 |
| `proxy` | server1 | server1 |
| `db` | server1 | server3 |

同じサーバーには同じホスト名を使い、複数グループに所属させます。
`deploy` / `rollback` は `app` だけを更新します。`configure` / `verify` / `reboot` は全役割が対象です。
`ops_private_ip` を書くだけでは DB 接続先や nginx の転送先は変更されません。

### 大会別のアプリ設定

`.local/contest.yml` を編集します。Go に限らず、任意の `argv` でビルドできます。

```yaml
ops_source_dir: "{{ ops_project_root }}/webapp/go"
ops_owner: isucon
ops_group: isucon
ops_service_name: myapp
ops_working_directory: .
ops_build_commands:
  - argv: [/usr/local/go/bin/go, build, -o, app, .]
ops_exec_start: "{{ ops_release_root }}/current/app"
ops_environment_files: [/home/isucon/env.sh]
ops_health_url: http://127.0.0.1:8080/health
ops_health_status_codes: [200]
```

`ops_source_dir` 以下を、未コミット・未追跡ファイルも含めて転送します。
`ops_archive_excludes` で `.git`・依存パッケージ・生成物などを除外できます。
ビルドはシェルを介さず `argv` を実行します。パイプなどが必要ならビルドスクリプトをソースに置き、
`argv: [bash, ./build.sh]` のように指定してください。

Python の例では以下のように、各リリースに依存関係を用意できます。

```yaml
ops_build_commands:
  - argv: [python3, -m, venv, .venv]
  - argv: [.venv/bin/pip, install, -r, requirements.txt]
ops_exec_start: "{{ ops_release_root }}/current/.venv/bin/gunicorn --bind 0.0.0.0:8080 app:app"
```

`ops_exec_start` は systemd の構文です。引数の引用符や `%` の扱いも systemd に従います。
DB 接続設定はアプリ側の環境変数や既存の環境ファイルで指定します。
リリースに保持される相対パスを前提とするアプリでは、必要な SQL・静的ファイルも転送対象に含めます。
アップロードされたファイルや DB などの可変データは、リリースディレクトリの外で管理してください。

## コマンド

```bash
# 構文・入力を検証。サーバーへは接続しない
./run.sh validate -i .local/hosts.yml -c .local/contest.yml

# ローカル変更をデプロイ
./run.sh deploy -i .local/hosts.yml -c .local/contest.yml -k /absolute/path/to/key

# 起動状態と HTTP 応答を確認
./run.sh verify -i .local/hosts.yml -c .local/contest.yml

# 直前のアプリリリースへ戻す
./run.sh rollback -i .local/hosts.yml -c .local/contest.yml

# 指定した設定ファイル・コマンドだけを適用
./run.sh configure -i .local/hosts.yml -c .local/contest.yml

# 全対象ホストを1台ずつ再起動してから verify
./run.sh reboot -i .local/hosts.yml -c .local/contest.yml
```

`-k` と `-u` は inventory の秘密鍵・ユーザーを上書きします。
sudo にパスワードが必要なら `--ask-become-pass` を追加します。
別のリポジトリでは `--project-root /path/to/project` を指定します。
`-e @/absolute/path/to/overrides.yml` で追加設定も指定できます。
設定の優先順位は、ロールの既定値 → inventory → 大会設定ファイル → `-e` の順です。
実行元の一時ファイルは `.local/tmp`、操作の排他ロックは `.local/operation.lock` に置きます。
ロックの対象は、このチェックアウトから起動した操作です。別 PC からの操作までは排他しません。

## デプロイとロールバックの動作

1. ソースをローカルで tar にまとめる。
2. 全 Webapp に別々の新規ディレクトリを作成して転送・ビルドする。
3. 全 Webapp のビルド成功後、各ホストの `current` リンクを新リリースに変更する。
4. 既存 systemd サービスの drop-in を配置し、再起動・自動起動の有効化・動作確認を行う。

既定の配置先は以下です。

```text
/home/isucon/contest-releases/
├── releases/release-*/     # 展開されたソースとビルド結果
├── current -> releases/release-.../
└── previous -> releases/release-.../
```

ベースの systemd unit は上書きせず、`90-contest-ops.conf` という drop-in で
作業ディレクトリと起動コマンドを指定します。既存の実行ユーザーや他の drop-in も確認してください。
`ops_service_requires` を省略すると依存関係は維持し、`[]` にすると既存の `Requires` を解除します。

ビルド失敗時は実行中のリリースを変更しません。起動・HTTP 確認が失敗した場合の自動復旧はせず、
原因を確認して `rollback` を実行します。各ホストの切替は同時・不可分ではありません。
再デプロイの前に復旧してください。再デプロイすると `previous` の対象が更新されます。

`rollback` は `current` と `previous` を入れ替え、**現在指定している設定ファイル**を使ってサービスを再起動します。
この基盤で2回以上デプロイした後に使用できます。初回導入前の既存アプリへの復元は対象外です。
DB、外部の設定ファイル、環境変数、依存パッケージのシステム全体への変更は戻しません。
旧リリース・ビルド失敗時のディレクトリ・失敗時のローカルアーカイブは自動削除しません。
無停止更新、複数アプリ間のキャッシュ同期、DB スキーマ互換性も自動では保証しません。

## nginx・DB・監視などの任意設定

共通基盤は製品固有の設定を持ちません。ホスト別・グループ別の inventory 変数に
`ops_config_files` と `ops_config_commands` を定義し、`configure` で適用します。
パスは絶対パスで指定します。以下は nginx ホストに指定する例です。

```yaml
ops_config_files:
  - src: /absolute/path/to/contest/nginx.conf.j2
    dest: /etc/nginx/conf.d/contest-app.conf
    mode: '0644'
ops_config_commands:
  - argv: [nginx, -t]
    changed: false
  - argv: [systemctl, reload, nginx]
ops_verify_services: [nginx]
ops_verify_ports:
  - host: 192.168.0.12
    port: 8080
```

DB の権限付与や監視エージェントの設定も同じ仕組みで指定できます。
秘密情報を含むテンプレート・コマンドには `secret: true`、ファイルには適切な `mode` を指定します。
任意のテンプレートから `groups['app']` や `hostvars[host].ops_private_ip` を参照できます。
全ファイルを配置した後にコマンドを順番に実行します。設定反映失敗時の自動復元はありません。
nginx の設定全体の検証など、必要な確認コマンドを reload より前に指定してください。

## ISUCON14 への適用

`config/isucon14.example.yml` は Go と SQL を同じリリースに配置する設定例です。
各 app ホストの `env.sh` の DB 接続先、DB の待受・権限、nginx の転送先、マッチャーの配置を
別途設定してください。この基盤は不要サービスの自動停止やマッチャーの起動は行いません。
同問題の現在のアプリにはプロセス内キャッシュがあるため、Webapp を2台起動しても、
状態同期への対応前に単純な負荷分散を有効にしないでください。

既存の `provisioning/ansible` が作る systemd drop-in と混用しないでください。
このリポジトリで変更した ISUCON14 の初期化スクリプトは `ISUCON_ENV_FILE` の指定に対応しています。
別の環境ファイルを使う場合は `ops_environment` に同変数を指定し、初期化にも同じ DB 接続先を使わせます。

## ルールと再起動確認

この基盤は運営用ユーザー・鍵・環境チェックを作成し直さず、DB 初期化も実施しません。
`configure` は任意の設定を変更できるため、対象大会で保護されているファイルやサービスを指定しないでください。
大会ごとのマニュアルを確認し、再起動後の自動起動・実データ保持・公式ベンチによる整合性を検証します。
`reboot` の自動確認はサービス・HTTP・設定した TCP 疎通までで、データ保持の自動検証は含みません。

## ローカルテスト

```bash
python3 -m unittest discover -s tests -v
```

実サーバーに接続せず、SSH 設定例の検証と、一時ディレクトリ上のソース転送・ビルド・
削除ファイルの扱い・ビルド失敗時の現行維持・ロールバック・設定テンプレートとコマンドの適用を検証します。
テスト時だけローカル接続・sudo なし・systemd 操作なしに切り替えます。
初動処理についても、元ファイルと除外設定の保存、保存先の権限、状態レポート、
設定しない場合の bootstrap が無変更であることを検証します。
