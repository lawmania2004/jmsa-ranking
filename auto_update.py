#!/usr/bin/env python3
"""毎週月曜深夜にlaunchdから実行される自動差分更新スクリプト。

処理内容 (LLM・Claudeトークンは一切使わない純Pythonスクリプト):
1. 主催大会一覧 (JMSA/SCM{year}.html) から開催済み・未登録の大会を検出して
   M40/M45男子をスクレイピング・登録
2. 公認大会一覧 (Masters/mi{year}.php) も同様に処理
3. JMSA公式スケジュール (masters-swim.or.jp/schedule10.php) と突き合わせて、
   tdsystemに結果がない公認大会(PDF配布など)を「手動確認が必要」として検出
4. サマリを ntfy.sh にPOSTしてiPhoneへプッシュ通知

手動実行: python3 auto_update.py [--dry-run]
launchd:  ~/Library/LaunchAgents/com.jmsa.ranking.autoupdate.plist (月曜 00:15)
"""
import os
import re
import sys
import logging
import warnings
from datetime import date, datetime

warnings.filterwarnings("ignore")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)
sys.path.insert(0, os.path.join(BASE_DIR, "scraper"))
sys.path.insert(0, os.path.join(BASE_DIR, "db"))

from config import LOG_DIR, NTFY_TOPIC

os.makedirs(LOG_DIR, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(os.path.join(LOG_DIR, "auto_update.log"), encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)

# 新規大会は全性別×全年齢区分(config.AGE_GROUPS)を取得する


def jmsa_date_iso(year, meet):
    """parse_jmsa_meet_list の戻り値から登録時と同じ date_iso を計算"""
    month = meet.get("month", 1)
    m = re.search(r"(\d+)日", meet.get("date_str", ""))
    if m:
        return f"{year:04d}-{month:02d}-{int(m.group(1)):02d}"
    return f"{year}-{month:02d}-01"


def find_new_meets(year, today_iso):
    """両一覧ページから開催済み・未登録の大会を検出"""
    from meet_scraper import fetch, parse_jmsa_meet_list, parse_meet_list, parse_meet_date, BASE
    from database import get_connection

    conn = get_connection()
    known = {
        (r["name"], r["date"], r["course_type"])
        for r in conn.execute("SELECT name, date, course_type FROM meetings").fetchall()
    }
    conn.close()

    new_meets = []  # (source, meet_id, name, date_iso)

    html = fetch(f"{BASE}/JMSA/SCM{year}.html")
    if html:
        for m in parse_jmsa_meet_list(html):
            date_iso = jmsa_date_iso(year, m)
            if date_iso <= today_iso and (m["name"], date_iso, m["course_type"]) not in known:
                new_meets.append(("主催", int(m["meet_id"]), m["name"], date_iso))
    else:
        logger.error("主催大会一覧の取得に失敗")

    html = fetch(f"{BASE}/Masters/mi{year}.php")
    if html:
        for m in parse_meet_list(html):
            if not m.get("meet_id"):
                continue
            date_iso = parse_meet_date(year, m["date_str"])
            if date_iso <= today_iso and (m["name"], date_iso, m["course_type"]) not in known:
                new_meets.append(("公認", int(m["meet_id"]), m["name"], date_iso))
    else:
        logger.error("公認大会一覧の取得に失敗")

    return new_meets


def check_official_schedule(year, today_iso):
    """JMSA公式スケジュールと突き合わせ、未集計の公認大会を検出(手動確認用)"""
    import requests
    from database import get_connection

    try:
        resp = requests.get(
            "https://www.masters-swim.or.jp/schedule10.php",
            headers={"User-Agent": "Mozilla/5.0"}, timeout=30,
        )
        resp.encoding = resp.apparent_encoding
        html = resp.text
    except requests.RequestException as e:
        logger.error(f"公式スケジュール取得失敗: {e}")
        return []

    # 大会ごとに <table class="list_sc"> があり、theadのh3がタイトル、
    # 行に「開催日」「長・短水路区別」などが入っている
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    meets = []
    for table in soup.find_all("table", class_="list_sc"):
        h3 = table.find("h3")
        title = h3.get_text(strip=True) if h3 else ""
        rows = {}
        for tr in table.find_all("tr"):
            cells = [td.get_text(" ", strip=True) for td in tr.find_all("td")]
            if len(cells) >= 2:
                rows[cells[0]] = cells[1]
        date_text = rows.get("開催日", "")
        dm = re.search(
            r"(\d{4})年(\d+)月(\d+)日[^\d]*(?:[～〜]\s*(?:(\d+)月)?(\d+)日)?", date_text
        )
        if not dm or not title:
            continue
        y, mo, d = int(dm.group(1)), int(dm.group(2)), int(dm.group(3))
        start = f"{y:04d}-{mo:02d}-{d:02d}"
        if dm.group(5):
            emo = int(dm.group(4)) if dm.group(4) else mo
            end = f"{y:04d}-{emo:02d}-{int(dm.group(5)):02d}"
        else:
            end = start
        course = "LCM" if "長水路" in rows.get("長・短水路区別", "") else "SCM"
        if y == year and start <= today_iso:
            meets.append({"title": title, "start": start, "end": end, "course": course})

    conn = get_connection()
    db_meets = [
        dict(r) for r in conn.execute(
            "SELECT id, name, date, course_type FROM meetings WHERE type = '公認'"
        ).fetchall()
    ]
    conn.close()

    # 貪欲マッチング: 各スケジュール大会に日付範囲+コースが合うDB大会を1つずつ割り当てる
    claimed = set()
    unmatched = []
    for sm in meets:
        hit = None
        for dbm in db_meets:
            if dbm["id"] in claimed:
                continue
            if dbm["course_type"] == sm["course"] and sm["start"] <= dbm["date"] <= sm["end"]:
                hit = dbm["id"]
                break
        if hit is not None:
            claimed.add(hit)
        else:
            unmatched.append(sm)
    return unmatched


def notify(title, message):
    if not NTFY_TOPIC:
        return
    import requests
    try:
        requests.post(
            f"https://ntfy.sh/{NTFY_TOPIC}",
            data=message.encode("utf-8"),
            headers={"Title": title, "Tags": "swimmer"},
            timeout=15,
        )
        logger.info("ntfy通知を送信しました")
    except requests.RequestException as e:
        logger.error(f"ntfy通知の送信に失敗: {e}")


def main():
    dry_run = "--dry-run" in sys.argv
    today = date.today()
    today_iso = today.isoformat()
    year = today.year
    logger.info(f"=== 自動更新開始 ({today_iso}, dry_run={dry_run}) ===")

    new_meets = find_new_meets(year, today_iso)
    logger.info(f"未登録の開催済み大会: {len(new_meets)}件")

    lines = []
    total = 0
    if dry_run:
        for src, gid, name, d in new_meets:
            lines.append(f"[{src}] G={gid} {name} ({d})")
    else:
        from meet_scraper import scrape_meet_all
        for src, gid, name, d in new_meets:
            try:
                counts = scrape_meet_all(year, gid, src)
            except Exception as e:
                logger.error(f"{src} G={gid} 失敗: {e}")
                lines.append(f"[{src}] {name} ({d}) エラー: {e}")
                continue
            if counts is None:
                lines.append(f"[{src}] {name} ({d}) 大会情報取得失敗")
                continue
            sub = sum(counts.values())
            m_total = sum(v for (g, _), v in counts.items() if g == "M")
            f_total = sum(v for (g, _), v in counts.items() if g == "F")
            total += sub
            lines.append(f"[{src}] {name} ({d}) 計{sub} (男{m_total}/女{f_total})")

    # 日本記録の更新チェック (1/1・7/1に新版PDFが出たら自動反映。同版ならスキップ)
    if not dry_run:
        try:
            from japan_records import update_japan_records
            rec_result = update_japan_records()
            for course, r in rec_result.items():
                if r:
                    lines.append(f"日本記録更新 ({course}): {r[0]}現在 {r[1]}件")
        except Exception as e:
            logger.error(f"日本記録チェック失敗: {e}")

    unmatched = check_official_schedule(year, today_iso)
    # 未集計大会をJSONに保存(ローカルWeb・公開サイトの※注意書きに使う)
    import json
    pending_path = os.path.join(BASE_DIR, "db", "pending_meets.json")
    with open(pending_path, "w", encoding="utf-8") as f:
        json.dump(unmatched, f, ensure_ascii=False, indent=1)
    if unmatched:
        lines.append("--- 手動確認が必要な公認大会 (tdsystem外) ---")
        for sm in unmatched:
            lines.append(f"・{sm['title']} ({sm['start']} {sm['course']})")

    if not lines:
        summary = "新規大会なし。データは最新です。"
    else:
        summary = "\n".join(lines)
        if total:
            summary += f"\n合計 {total}件 登録"
    logger.info(summary)

    if not dry_run:
        publish_static()
        notify(f"JMSAランキング自動更新 ({today_iso})", summary)
    logger.info("=== 自動更新終了 ===")


def publish_static():
    """静的サイトデータを再生成してGitHub Pagesへpush"""
    import subprocess
    try:
        subprocess.run(
            [sys.executable, os.path.join(BASE_DIR, "generate_static.py")],
            check=True, capture_output=True, cwd=BASE_DIR,
        )
        # 変更があればコミットしてpush (存在するパスのみ対象)
        paths = ["docs/"]
        if os.path.exists(os.path.join(BASE_DIR, "db", "pending_meets.json")):
            paths.append("db/pending_meets.json")
        diff = subprocess.run(
            ["git", "status", "--porcelain"] + paths,
            capture_output=True, text=True, cwd=BASE_DIR,
        )
        if not diff.stdout.strip():
            logger.info("静的サイトに変更なし(pushスキップ)")
            return
        subprocess.run(["git", "add"] + paths, check=True, cwd=BASE_DIR)
        subprocess.run(
            ["git", "commit", "-m", f"自動更新 {datetime.now().strftime('%Y-%m-%d')}"],
            check=True, capture_output=True, cwd=BASE_DIR,
        )
        subprocess.run(["git", "push"], check=True, capture_output=True, cwd=BASE_DIR)
        logger.info("静的サイトをpushしました")
    except subprocess.CalledProcessError as e:
        logger.error(f"静的サイト公開に失敗: {e}\n{getattr(e, 'stderr', '')}")


if __name__ == "__main__":
    main()
