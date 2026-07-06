# jmsa-ranking — マスターズ水泳ランキング（非公式）

tdsystem.co.jp等から試合結果をスクレイピングし、SQLiteに蓄積、GitHub Pagesで静的公開するランキングサイト。基本構成はREADME.md参照（ただしREADMEのcron記述は古い。実際はlaunchd、下記参照）。

## アーキテクチャの要点

- **データの流れ**: scraper/ → db/ranking.db (SQLite) → generate_static.py → docs/data/*.json → git push → GitHub Pages公開
- **公開サイト**: https://lawmania2004.github.io/jmsa-ranking/ （リポジトリ: lawmania2004/jmsa-ranking、docs/フォルダ方式・公開リポジトリ）
- `docs/index.html` と `docs/static/*` は**手書き**。generate_static.py は `docs/data/*.json` と `meta.json`・`records.json` だけを再生成する（index.htmlを生成物と勘違いして消さない）
- `web/app.py`（FastAPI）はローカル確認・管理用。本番はあくまで静的サイト（管理画面は公開サイトに存在しない）

## 自動更新（重要）

- `auto_update.py` が launchd（`com.jmsa.ranking.autoupdate.plist`、**毎週日曜 22:00**）で実行される。予定時刻にMacがスリープ/電源オフなら、次に起動した時に1回だけ遅延実行される（launchd仕様）
- LLM・Claudeトークンを一切使わない純Pythonスクリプト。**この方針を維持する（トークン消費ゼロがユーザーの要件）**
- 処理: 主催大会+公認大会の差分スクレイピング（`scrape_meet_all` で**全性別×全年齢区分**）→ 日本記録PDFの新版チェック → 公式スケジュール突合でPDF配布のみの大会を「手動確認要」として検出 → generate_static.py → `git push origin HEAD:main` → ntfyでiPhone通知（コミットメッセージ「自動更新 YYYY-MM-DD」）
- ログ: `logs/`。手動テスト: `python3 auto_update.py --dry-run`

## 主な機能

- **日本記録**: `scraper/japan_records.py` が協会PDF（1/1・7/1更新、`record_10nihonkiroku.php`）を解析し `japan_records` テーブルへ。ランキングで記録超え=日本新／同タイム=日本タイのバッジを表示
- **選手名検索**: その選手のその年度・区分の全種目サマリ（順位/人数・タイム・大会）を一覧表示
- **マイ選手ハイライト**: 公開サイトはブラウザのlocalStorage（ヘッダーの★マイ選手設定）、ローカル版は `.my_name` から読む

## 触るときの注意

- スクレイピングは**全性別・全年齢区分**を収集済み（backfill完了）。全量は数時間かかる。差分更新(auto_update.py)と混同しない
- **秘匿情報はgit管理外**: `.ntfy_topic`（ntfyトピック名）と `.my_name`（ユーザー氏名）は `.gitignore` 済み。config.pyはこれらのファイルから読む。公開リポジトリに氏名・トピックを載せない。コミットはnoreplyメール
- **PDF配布のみの大会は自動取得できず手動登録**（奈良/東北/ひのくに/湘南平塚など）。手動データが混ざるので、DB再構築系の操作は要注意（安易に `db/database.py` で初期化しない）
- 選手名の姓名分割は姓辞書ベースの後処理をしている（姓名5文字以上はスペースなしで維持）。名前処理を変える際は既存データとの整合に注意
- `scraper/meet_scraper.py` の `fetch` はリトライ付き（長時間実行中の接続リセット対策）
- GitHub操作は `~/bin/gh`（フルパス、認証済み）を使う。週次pushは `credential.helper store` 依存なので変更しない
