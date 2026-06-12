# JMSA ランキングシステム

日本マスターズ水泳協会（JMSA）の公式サイトから試合結果を自動取得し、年齢区分・性別・種目・コース種別でフィルタリングできるランキングWebアプリです。

## セットアップ

```bash
pip install -r requirements.txt
```

## 使い方

### 1. データベース初期化

```bash
python3 db/database.py
```

### 2. スクレイピング（データ取得）

全種目・全年齢区分を取得（数時間かかります）:
```bash
python3 scraper/scraper.py
```

特定の種目・年齢区分のみ:
```bash
python3 scraper/scraper.py --event 50FR --age 30
```

オプション:
- `--year 2025` : 年度指定（デフォルト: 2025）
- `--course SCM` : コース種別（SCM: 短水路 / LCM: 長水路）
- `--event 50FR` : 種目指定
- `--age 30` : 年齢区分指定

### 3. Webアプリ起動

```bash
python3 web/app.py
```

ブラウザで http://localhost:8000 にアクセス

### 4. 管理ページ

http://localhost:8000/admin から手動スクレイピングの実行、取得済み大会の確認ができます。

## cronの設定

毎週日曜日 21:00 に自動実行:
```
0 21 * * 0 /usr/bin/python3 /path/to/jmsa-ranking/cron_update.py >> /path/to/jmsa-ranking/logs/cron.log 2>&1
```

## ディレクトリ構成

```
jmsa-ranking/
├── scraper/
│   ├── scraper.py        # スクレイピング本体
│   └── parser.py         # HTML解析・データ整形
├── db/
│   ├── database.py       # DB接続・CRUD
│   └── ranking.db        # SQLiteファイル
├── web/
│   ├── app.py            # FastAPIアプリ
│   ├── templates/        # HTMLテンプレート
│   └── static/           # CSS / JS
├── logs/
├── config.py             # 設定ファイル
├── cron_update.py        # 週次自動実行スクリプト
└── README.md
```

## データソース

- 総合ランキング: `https://tdsystem.co.jp/RecordSCM.php` (GETパラメータで種目・年齢区分を指定)
- 大会一覧: `https://tdsystem.co.jp/JMSA/SCM{year}.html`
