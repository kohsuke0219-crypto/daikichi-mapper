# daikichi-mapper の決まりごと

買取店商圏マップ（docs/index.html を GitHub Pages で公開）と、物件ボード用の撮影・物件写真の取得、店舗データの週次更新（scraper/、GitHub Actions）をまとめたリポジトリ。
このリポジトリは **Cowork（チャット）** と **Claude Code（PC）** の2人で触る。作業を始める前に必ずこのファイルを読むこと。

## 分担

### Cowork（チャット。クラウドからこのリポジトリを直接直す）が直してよいもの
- 地図画面（docs/index.html）の小さな修正：文言・色・表示の切替・ボタンなど、データの作り直しがいらないもの
- 説明文（README.md・CLAUDE.md・docs/*.md など）、.gitignore
- 店舗データ収集（scraper/）の小さな設定直し（チェーン名の追加など）
- コードを読んで原因を調べる／Claude Code の報告を読む
- 物件ボード（Artifact）のデータ修正・判定のやり直し・探索条件の変更（リポジトリの外）

### Claude Code（PC）に回すもの
- 地図データの作り直し（docs/data/）、analysis/ のスクリプトの改修・実行
- 商圏マップの撮影（analysis/board_screenshot.py）・物件写真の取得（analysis/board_photos.py）
- PC にしかない元データ（analysis/geo_data/ の zip・parquet など）を使う処理
- 複数ファイルにまたがる変更、新しいライブラリの追加
- **迷ったら Claude Code に回す**

## 共通の決まり
- push は master ブランチだけ。コミットの前に必ず `git pull` で最新を取り込む（Cowork と Claude Code が同じ master を触るため）
- Claude Code に指示を出している間、そのファイルを Cowork は触らない
- docs/data/ の地図用データは手で直さず、スクリプトで作り直す
- 画像・秘密の鍵（APIキー、サービスアカウントの JSON、.env）はコミットしない
- ログイン・アカウント操作・フォーム送信・お金の操作・ファイル削除はしない
- mervari シグナル（trig_01PGwBXUYiC4iU7LeyDBhtgC）は発火しない
- オーナーへの報告は日本語・平易・結論から（専門用語を使わない）

## Claude Code への頼み方（連絡帳）
- Google ドライブ「物件ボード連絡帳」（PC では G:\マイドライブ\物件ボード連絡帳）に `指示-YYYYMMDD-HHMM.md` を置く → PC の見張り役（board_watcher.ps1）が Claude Code を起動 → Claude Code が同じ番号の `報告-YYYYMMDD-HHMM.md` を置く
- 物件メール巡回のチャットが 16:4x・18:4x 前後に撮影の指示を置くので、それ以外の指示は時刻を重ねない
- Cowork は指示を出す前に、中身をオーナーに見せて確認を取る
- 指示の最後には上の「共通の決まり」（画像・ログイン等・master・mervari）を必ず書く
