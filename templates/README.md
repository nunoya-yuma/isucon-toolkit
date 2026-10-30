# <大会の名前>（大会リポジトリ）

このリポジトリの直下は、実機のアプリのフォルダ（`<APP_DIR>`）のcloneです。このrepoで用意する操作の入口は、[`tools/toolkit/`](tools/toolkit/README.md)の`tk`です。他の方法で実機を変えたときも、下の連絡の場所に1行で書きます。

## 大会の要点

- 当日マニュアル：<場所>
- 言語：<言語>　アプリのサービス：<APP_SERVICE>
- 変更してはいけないもの（マニュアルより）：<環境確認の仕組みのファイル・サービス・ユーザーなど>
- 追試の条件：<再起動の後のbenchmark、スコアの下限など>

## インスタンス

インスタンスの名前は、運営のEC2のNameタグと同じ文字列です（SSHのalias・`hosts/<インスタンス>/`・`tk.env`も同じ）。

| インスタンスの名前 | マニュアルのホスト名 | 役割 |
|---|---|---|
| <Nameタグ> | <例：app-1.example> | <nginx・app／app／DB など> |

## 連絡の場所

変更は、Discordの「<場所の名前>」に1行で書きます（[原則7](tools/toolkit/docs/principles.md)）。`tk`の最後の1行は、そのまま貼れます。

## このrepoの扱い

- feature branch・PR・固定SHAといった慎重な規則は、実機に配るもの（アプリ・設定・`server/`・`hosts/`）を守るためのもの。
- 実機で使われない`docs/`の下の`.md`は、mainへ直接pushしてよい。`docs/`には`.md`だけを置く。
- 実機から複写したファイルに、秘密鍵・有効なAPI key・外部サービスのtokenがあれば、commitの前に止めてチームで確かめる。主催者の既定のDBのpasswordのように、後で公開されると分かっている値は、private repoに限ってcommitしてよい。

## 今の状態の見方

- 実機：`tools/toolkit/tk status`
- 採用した変更の記録：`main`
- 試している変更：feature branch（`tk deploy`は、どのbranchのcommitでも配れる）

## フォルダ

| パス | 中身 |
|---|---|
| アプリのファイル（`go/`・`sql/`など） | 実機から取り込んだもの |
| `server/` | 全インスタンスに配る設定（実機の絶対パスのまま） |
| `hosts/<インスタンス>/` | そのインスタンスだけの設定（`server/`より優先） |
| `tools/toolkit/` | isucon-toolkitの複写（元のrepoとSHAは、複写のときに書く`tools/toolkit/SOURCE.md`） |
| `tk.env` | `tk`の設定（秘密値を入れずにcommitする。`tools/toolkit/templates/tk.env.example`から作る） |
| `runs/` | `tk`の手元の記録（Gitで除く） |

## Gitで除いたもの

最初の`git add -A`の前に、`.gitignore`へ入れる（`tools/toolkit/templates/gitignore.example`から）。

- 秘密値と秘密鍵：<例：.env、env.sh、秘密鍵のファイル。アプリが要る公開鍵は除かない>
- 動いているデータ（Git化・`tk deploy`で消さないもの）：<例：tenant_db/、*.db、アップロードされたファイル>

## Gitの外にある変更

commitを通さずに実機を変えたもののうち、残しているもの（[原則3](tools/toolkit/docs/principles.md)）。

| インスタンス | 何を | 理由 | 戻し方 |
|---|---|---|---|
| <インスタンス> | <例：/etc/systemd/system/<unit>.d/90-*.conf> | <理由> | <消して daemon-reload・restart> |
