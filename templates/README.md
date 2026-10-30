# <大会の名前>（大会リポジトリ）

このリポジトリの直下は、実機のアプリのフォルダ（`<APP_DIR>`）のcloneです。操作は[`tools/toolkit/`](tools/toolkit/README.md)の`tk`で行います。

## 大会の要点

- 当日マニュアル：<場所>
- 言語：<言語>　アプリのサービス：<APP_SERVICE>
- 変更してはいけないもの（マニュアルより）：<環境確認の仕組みのファイル・サービス・ユーザーなど>
- 追試の条件：<再起動の後のbenchmark、スコアの下限など>

## 台

台の名前は、運営のEC2のNameタグと同じ文字列です（SSHのalias・`hosts/<台>/`・`tk.env`も同じ）。

| 台の名前 | マニュアルのホスト名 | 役割 |
|---|---|---|
| <Nameタグ> | <例：app-1.example> | <nginx・app／app／DB など> |

## 連絡の場所

変更は、Discordの「<場所の名前>」に1行で書きます（[原則7](tools/toolkit/docs/principles.md)）。`tk`の最後の1行は、そのまま貼れます。

## 今の状態の見方

- 実機：`tools/toolkit/tk status`
- 採用した変更の記録：`main`
- 試している変更：feature branch（`tk deploy`は、どのbranchのcommitでも配れる）

## フォルダ

| パス | 中身 |
|---|---|
| アプリのファイル（`go/`・`sql/`など） | 実機から取り込んだもの |
| `server/` | 全台に配る設定（実機の絶対パスのまま） |
| `hosts/<台>/` | その台だけの設定（`server/`より優先） |
| `tools/toolkit/` | isucon-toolkitの複写（SHAは`tools/toolkit/SOURCE.md`） |
| `tk.env` | `tk`の設定（Gitで除く。`tools/toolkit/templates/tk.env.example`から作る） |
| `runs/` | `tk`の手元の記録（Gitで除く） |

## 動いているデータ（Gitで除いたもの）

`.gitignore`で除き、Git化・`tk deploy`で消さないもの。

- <例：tenant_db/、*.db、アップロードされたファイル>

## Gitの外にある変更

commitを通さずに実機を変えたもののうち、残しているもの（[原則3](tools/toolkit/docs/principles.md)）。

| 台 | 何を | 理由 | 戻し方 |
|---|---|---|---|
| <台> | <例：/etc/systemd/system/<unit>.d/90-*.conf> | <理由> | <消して daemon-reload・restart> |
