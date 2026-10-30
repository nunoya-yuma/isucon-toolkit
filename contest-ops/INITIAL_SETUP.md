# 初動手順と採用したアイデア

[mazrean/isucon-ansible-public](https://github.com/mazrean/isucon-ansible-public) の構成を参考に、
大会ごとに流用できる初動処理を追加しました。参照時の commit は
`174cf4dfaa6f9b482d6901e43b710902c5b9f5c9` です。
処理は共通基盤に合わせて独自に実装しています。

## 採用したもの

| 参照先のアイデア | この基盤での対応 |
| --- | --- |
| `roles/repo` にあるアプリ・nginx・MySQL 設定の取り込み | `snapshot`。ホスト別に元ソース・設定をローカルへ保存。外部への自動 push や元ファイルの上書きは行わない |
| `roles/tools` にある調査ツールの準備 | `bootstrap`。指定したパッケージだけを `state: present` で導入 |
| `roles/common` にある journald の容量制限 | `bootstrap`。明示した場合だけ専用 drop-in で設定 |
| ホストごとの変数で構成を定義 | inventory にホスト・役割ごとの採取元・導入ツールを指定 |

変更前後を比較できるよう、サービス一覧・待受ポート・CPU・メモリ・ディスクの状態を保存する
`inspect` も追加しています。

以下は共通の初動処理には採用していません。

- カーネルパラメーターや GRUB の一括変更、CPU の mitigations 無効化、自動再起動。
- MySQL の doublewrite 無効化や fsync 頻度変更などの耐久性・性能設定。
- 既存 Go の削除・再インストール、グローバルな Git のユーザー設定。
- ファイルの権限を一律に `666` / `777` にする変更。
- ソースの自動改変、リモート Git リポジトリへの自動 commit / push。
- Fluent Bit・Loki・Pyroscope など監視基盤一式の自動導入。

これらは必要性、バージョン、競技ルール、計測への影響を大会ごとに判断します。

## 1. 接続先を用意する

以下は `provisioning/contest-ops` を作業ディレクトリとして実行します。

```bash
mkdir -p .local
cp inventory/three.example.yml .local/hosts.yml
# .local/hosts.yml の SSH 接続先・ユーザー・鍵を編集
```

インスタンス1つの構成ならコピー元を `inventory/single.example.yml` に変更します。
初動用コマンドは `app`・`proxy`・`db` のいずれかに所属する全ホストが対象で、
同じ名前で複数グループに登録したホストには1回ずつ実行します。

初動処理は `-c config/initial.example.yml` で実行できます。
アプリのソースパスやサービス名はまだ決まっていなくても構いません。

## 2. 変更前の状態を記録する

```bash
./run.sh inspect -i .local/hosts.yml -c config/initial.example.yml
```

以下を `.local/artifacts/<UTC日時とランダムID>/<ホスト名>/baseline.json` に保存します。

- OS、CPU 数、メモリ量。
- サービス一覧と起動状態。
- カーネル情報、TCP 待受ポート、ディスク空き容量、メモリ、プロセス名。

対象の設定変更やサービス再起動は行いません。SSH・Ansible の実行に必要な一時ファイルは作成します。
環境変数やプロセスの引数はレポートに含めません。
任意の観測コマンドが存在しない場合は、その失敗もレポートに保存して残りを継続します。
SSH 接続・facts 取得・レポート保存などの失敗は通常のエラーになります。

## 3. 元ソース・設定を保存する

inventory の各ホストに、存在するファイル・ディレクトリを明示します。
以下はインスタンス3つの構成の各ホスト設定に追加する例です。

```yaml
# all.hosts.server1 に追加する項目（nginx + Webapp）
ops_snapshot_paths:
  - /home/isucon/webapp
  - /etc/nginx/nginx.conf
  - /etc/nginx/conf.d
  - /etc/nginx/sites-available
ops_snapshot_excludes:
  - node_modules
  - .git

# all.hosts.server3 に追加する項目（DB）
# ops_snapshot_paths:
#   - /etc/mysql/my.cnf
#   - /etc/mysql/mysql.conf.d
```

```bash
./run.sh snapshot -i .local/hosts.yml -c config/initial.example.yml
```

保存先は `.local/artifacts/<UTC日時とランダムID>/<ホスト名>/original.tar.gz`。
元ファイルは変更せず、サーバー上の一時アーカイブは処理後に削除します。
対象パスが空のホストは採取をスキップし、指定されたパスが存在しない場合は失敗します。
再実行するたびに別の保存先を使います。

アーカイブと状態レポートは `0600`、ホスト別の保存ディレクトリは `0700` で作成します。
設定にはパスワードなどが含まれ得るため、`.local` は Git の管理対象外にしています。
アーカイブは指定パスを `/` からの相対パスとして保持します。

この処理は **DB のバックアップではありません**。稼働中の DB データディレクトリを指定しないでください。
ソースも書き換えと並行して採取しない運用にします。復元は自動化していません。

## 4. 必要な調査ツールだけを導入する

inventory の `all.vars` または各ホストに以下を追加します。

```yaml
ops_bootstrap_packages:
  - git
  - htop
  - jq
  - unzip
ops_journald_max_use: 200M
```

DB ホストだけに `percona-toolkit` を追加するなど、役割に合わせて指定できます。
パッケージ配列はホスト側の指定で置き換わるため、そのホストに必要なものを列挙してください。

```bash
./run.sh bootstrap -i .local/hosts.yml -c config/initial.example.yml
```

- パッケージは Debian / Ubuntu の apt を利用してインストールします。最新バージョンへの一括更新は行いません。
- `ops_journald_max_use` は永続ジャーナルの `SystemMaxUse`。設定変更時だけ journald を再起動します。
- ログ保持設定は `/etc/systemd/journald.conf.d/90-contest-ops.conf` に配置します。
- 既定ではパッケージ配列も容量設定も空で、対象ホストの設定を変更しません。
- `envcheck`・運営用ユーザー・鍵・DB データは、この処理の変更対象にしません。

## 5. アプリのデプロイへ進む

状態記録と元ファイルの保存後に、[README](README.md) の大会別設定・デプロイへ進みます。
既に大会別設定ファイルを用意している場合は、初動コマンドでもそのファイルを `-c` に指定できます。
`-k`・`-u`・`--ask-become-pass`・`-e` は他のコマンドと同様に使用できます。

初動の結果はサーバーの調査・復旧に使う資料です。公式ベンチや再起動後のデータ保持確認は別途行います。
