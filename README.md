# 買取大吉 店舗データ自動収集システム

`https://www.kaitori-daikichi.jp/store/` の店舗情報を週次でスクレイプし、緯度経度を付与して Google スプレッドシートに書き込みます。Looker Studio でそのシートを地図表示すれば、商圏分析用ダッシュボードが常に最新の状態に保たれます。

## アーキテクチャ

```
GitHub Actions (週1 cron)
  → Pythonスクレイパー (6地区ページをGET)
  → HTMLパース (店舗名/住所/電話/営業時間/詳細URL/Maps URL)
  → Google Geocoding API (新規・住所変更分のみ)
  → Google Sheets (stores シートを全件上書き)
  → Looker Studio (シートを自動同期して地図に表示)
```

## ファイル構成

```
daikichi-mapper/
├── scraper/
│   ├── __init__.py
│   ├── scraper.py        # サイトをスクレイプして店舗情報をパース
│   ├── geocoder.py       # 住所→緯度経度の変換（キャッシュつき）
│   ├── sheets_writer.py  # Google Sheetsへの書き込み
│   └── main.py           # エントリポイント
├── .github/workflows/
│   └── update.yml        # GitHub Actions の週次ジョブ
├── docs/
│   └── looker_studio_setup.md  # Looker Studio側の設定手順
├── requirements.txt
└── README.md
```

## セットアップ手順（初回のみ・所要 30〜45分）

### 1. Google Cloud プロジェクトの準備

1. [Google Cloud Console](https://console.cloud.google.com/) で新規プロジェクトを作成（例: `daikichi-mapper`）
2. 以下の API を「APIとサービス > ライブラリ」から有効化:
   - **Geocoding API**
   - **Google Sheets API**
   - **Google Drive API**
3. 「APIとサービス > 認証情報」で:
   - **APIキー**を1つ作成 → Geocoding API 用。アプリケーションの制限で「IPアドレス」を選び、GitHub Actions の出口 IP がわからないため一旦「なし」でもよい（後述）
   - **サービスアカウント**を1つ作成 → Sheets 書き込み用。作成後「キー > 鍵を追加 > JSON」でJSONをダウンロード

### 2. スプレッドシートの準備

1. [Google スプレッドシート](https://sheets.google.com/) で新規スプレッドシートを作成（例: `buy_daikichi_stores`）
2. URL の `/d/` と `/edit` の間にある文字列が **スプレッドシートID** （後で使う）
3. 共有 → 上記サービスアカウントのメールアドレス（`xxx@xxx.iam.gserviceaccount.com`）を **編集者** で追加

### 3. GitHub リポジトリの準備

1. このコード一式を GitHub に新規プライベートリポジトリとしてプッシュ
2. リポジトリの **Settings > Secrets and variables > Actions** で以下の Secret を追加:

   | Secret 名 | 値 |
   |---|---|
   | `GOOGLE_MAPS_API_KEY` | 手順1で作ったAPIキー |
   | `GOOGLE_SERVICE_ACCOUNT_JSON` | サービスアカウントJSONの **中身全部**（コピペ） |
   | `SPREADSHEET_ID` | 手順2のスプレッドシートID |

### 4. 動作確認

1. GitHub の **Actions** タブ → 「Update Daikichi Stores」→ 「Run workflow」で手動実行
2. 5〜15分待つ（初回は1900件分のジオコーディングが走るため）
3. スプレッドシートの `stores` シートに全店舗が並べばOK

### 5. Looker Studio で地図化

`docs/looker_studio_setup.md` に詳しい手順を書いていますが、要点は:

1. [Looker Studio](https://lookerstudio.google.com/) で新しいレポートを作成
2. データソースに上記スプレッドシートの `stores` シートを接続
3. グラフタイプで **Google マップ > バブルマップ** を選択
4. ディメンション: `latitude, longitude`（緯度・経度の地理型フィールドを作成）
5. これでブラウザから常に最新の店舗マップが見られる状態に

## ローカルでのテスト実行

```bash
pip install -r requirements.txt

# 環境変数を設定
export GOOGLE_MAPS_API_KEY="..."
export GOOGLE_APPLICATION_CREDENTIALS="/path/to/sa.json"

# スクレイプのみ（シートに書き込まない）
python -m scraper.main --dry-run

# 本番実行
python -m scraper.main --spreadsheet-id YOUR_SPREADSHEET_ID
```

## 運用上の注意

### サイト構造が変わったら

`scraper.py` の HTML パース部分が壊れます。具体的には:
- `_find_card_root()`: 店舗カードの親要素を探すロジック
- `_extract_field()`: 「住所」「定休日」「営業時間」ラベルから値を取り出すロジック

GitHub Actions が失敗したら、まず手元で `python -m scraper.main --dry-run` を実行してエラー箇所を特定してください。

### 利用規約とアクセス頻度

- スクレイピング先サイトの `robots.txt` と利用規約を必ず確認してください
- 本実装は **週1回・地区ページ間に1秒スリープ** とサイトに優しい設定にしています
- 商用利用や再配布の場合は、買取大吉本部に事前に相談することを強く推奨します

### コスト目安

- **GitHub Actions**: 無料枠（パブリックリポジトリは無制限、プライベートでも月2000分）で十分
- **Geocoding API**: 初回 1900件 × $5/1000 = 約 $9.5 / 以降は新規店舗のみで月数百円
- **Google Sheets / Looker Studio / マイマップ**: 無料

### 商圏分析への拡張

Looker Studio のメリットを活かして、以下のシートを追加すると分析力が一気に上がります:

- `competitors`: 競合買取店の座標を別シートに（おたからや・買取専門店なんぼや等）
- `population`: e-Statから取得した町丁字別人口（年齢別あればなお良し）
- `gold_price`: 金相場の時系列（買取需要の代理指標）

これらを Looker Studio 上で結合すれば、「店舗から半径3km圏の人口」「競合密度の高いエリア」「金相場高騰時に伸びる店舗」などの分析が可能になります。

## ライセンス

このコードのライセンスはあなたが自由に設定してください。スクレイピング対象データの権利は買取大吉本部に帰属します。
