"""
公認大会・主催大会の個別大会結果ページからデータを取得するスクレイパー。

URL構造:
- 公認大会一覧: https://tdsystem.co.jp/Masters/mi{year}.php
- プログラム一覧: https://tdsystem.co.jp/ProList.php?Y={year}&M=0&G={meet_id}&GL={year}
- 種目別結果: https://tdsystem.co.jp/Record.php?Y={year}&M=0&G={meet_id}&GL={year}&S=2&Lap=1&Cls={age}&L=1&RG=1&Page=ProList.php&P={prog_no}

年齢区分の Cls パラメータ:
- 999 = 全区分
- 18, 25, 30, ..., 90 = 各5歳区分
"""
import os
import re
import sys
import time
import logging
import requests
from datetime import datetime
from bs4 import BeautifulSoup

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)
sys.path.insert(0, os.path.join(BASE_DIR, "scraper"))
sys.path.insert(0, os.path.join(BASE_DIR, "db"))

from config import REQUEST_DELAY, LOG_DIR
from parser import parse_time_to_seconds
from database import get_connection, init_db

os.makedirs(LOG_DIR, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(os.path.join(LOG_DIR, "meet_scraper.log"), encoding="utf-8"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) JMSA-Ranking-Bot/1.0"
})

BASE = "https://tdsystem.co.jp"

DISTANCE_MAP = {
    "25m": "25", "50m": "50", "100m": "100", "200m": "200",
    "400m": "400", "800m": "800", "1500m": "1500",
}
STROKE_MAP = {
    "自由形": "FR", "背泳ぎ": "BK", "平泳ぎ": "BR",
    "バタフライ": "FLY", "個人メドレー": "IM",
}


def fetch(url, params=None):
    try:
        resp = SESSION.get(url, params=params, timeout=30)
        resp.encoding = resp.apparent_encoding
        resp.raise_for_status()
        return resp.text
    except requests.RequestException as e:
        logger.error(f"Failed to fetch {url}: {e}")
        return None


def parse_meet_list(html):
    """公認大会一覧ページから大会リストを取得"""
    soup = BeautifulSoup(html, "html.parser")
    meets = []
    current_month = None

    for elem in soup.find_all(["h1", "h2", "h3", "table"]):
        if elem.name in ("h1", "h2", "h3"):
            text = elem.get_text(strip=True)
            m = re.match(r"(\d{4})年(\d+)月", text)
            if m:
                current_month = (int(m.group(1)), int(m.group(2)))
            continue

        if elem.name == "table" and current_month:
            rows = elem.find_all("tr")
            for tr in rows:
                cells = tr.find_all(["td", "th"])
                if len(cells) < 5:
                    continue
                date_str = cells[0].get_text(strip=True)
                name = cells[1].get_text(" ", strip=True)
                venue = cells[2].get_text(" ", strip=True)
                if not date_str or "日付" in date_str:
                    continue

                btn = tr.find("button", {"name": "G"})
                meet_id = btn.get("value") if btn else None

                course = "SCM"
                vmatch = re.search(r"\((\d+)m\)", venue)
                if vmatch and vmatch.group(1) == "50":
                    course = "LCM"

                meets.append({
                    "year": current_month[0],
                    "month": current_month[1],
                    "date_str": date_str,
                    "name": name,
                    "venue": venue,
                    "meet_id": meet_id,
                    "course_type": course,
                })
    return meets


def parse_program_list(html):
    """プログラム一覧ページから種目リストを取得"""
    soup = BeautifulSoup(html, "html.parser")
    programs = []

    for tr in soup.find_all("tr"):
        cells = tr.find_all(["td", "th"])
        if len(cells) < 6:
            continue

        no_text = cells[0].get_text(strip=True)
        if not no_text.isdigit():
            continue

        gender_text = cells[1].get_text(strip=True)
        distance = cells[3].get_text(strip=True)
        stroke = cells[4].get_text(strip=True)

        if gender_text == "男子":
            gender = "M"
        elif gender_text == "女子":
            gender = "F"
        else:
            gender = "X"

        if "リレー" in stroke or "×" in distance:
            continue

        dist_code = DISTANCE_MAP.get(distance)
        stroke_code = STROKE_MAP.get(stroke)
        if not dist_code or not stroke_code:
            continue

        event = f"{dist_code}{stroke_code}"
        programs.append({
            "no": int(no_text),
            "gender": gender,
            "event": event,
            "distance": distance,
            "stroke": stroke,
        })
    return programs


def parse_result_page(html, event, gender, age_group_label, age_filter=None, cls_value=None):
    """個別種目の結果ページから結果リストを取得.

    age_filter: "40～44歳" のような文字列。組別表示で区分カラムがある場合に使用.
    cls_value: Clsパラメータ値 (例: 40)。ドロップダウンに存在しない場合は全区分が返るため除外.
    """
    soup = BeautifulSoup(html, "html.parser")
    results = []

    # 区分ドロップダウンを確認: Cls=cls_value がオプションにない場合は全区分表示になるためスキップ
    if cls_value is not None:
        cls_select = soup.find("select", {"name": "Cls"})
        if cls_select:
            available = [opt.get("value") for opt in cls_select.find_all("option")]
            if str(cls_value) not in available:
                return []

    tables = soup.find_all("table")
    for table in tables:
        header_row = table.find("tr")
        if not header_row:
            continue
        headers = [c.get_text(strip=True) for c in header_row.find_all(["th", "td"])]
        if "氏名" not in headers:
            continue

        time_idx = next((i for i, h in enumerate(headers) if "タイム" in h), None)
        rank_idx = next((i for i, h in enumerate(headers) if "順位" in h), None)
        name_idx = next((i for i, h in enumerate(headers) if "氏名" in h), None)
        club_idx = next((i for i, h in enumerate(headers) if "チーム" in h), None)
        category_idx = next((i for i, h in enumerate(headers) if "区分" in h), None)

        if time_idx is None or name_idx is None:
            continue

        rows = table.find_all("tr")[1:]
        for row in rows:
            cells = row.find_all("td")
            if len(cells) <= time_idx:
                continue

            if category_idx is not None and age_filter:
                category_val = cells[category_idx].get_text(strip=True)
                if age_filter not in category_val:
                    continue

            rank = None
            if rank_idx is not None and len(cells) > rank_idx:
                rank_text = cells[rank_idx].get_text(strip=True)
                if rank_text.isdigit():
                    rank = int(rank_text)

            athlete_name = cells[name_idx].get_text(strip=True)
            club = cells[club_idx].get_text(strip=True) if club_idx is not None and len(cells) > club_idx else ""
            time_display = cells[time_idx].get_text(strip=True)

            if not athlete_name:
                continue

            time_seconds = parse_time_to_seconds(time_display)
            if time_seconds is None:
                continue

            athlete_name = re.sub(r'\s+', '　', athlete_name)

            results.append({
                "rank": rank,
                "athlete_name": athlete_name,
                "club": club,
                "time_display": time_display,
                "time_seconds": time_seconds,
                "event": event,
                "gender": gender,
                "age_group": age_group_label,
            })
    return results


def insert_meet_results(meet_info, results):
    """大会情報と結果をDBに保存（差分更新: 既存ならスキップ）"""
    conn = get_connection()
    now = datetime.now().isoformat()

    date_iso = meet_info.get("date_iso") or f"{meet_info['year']}-01-01"

    cursor = conn.execute(
        "SELECT id FROM meetings WHERE name = ? AND date = ? AND course_type = ?",
        (meet_info["name"], date_iso, meet_info["course_type"])
    )
    row = cursor.fetchone()
    if row:
        meeting_id = row["id"]
        # 既存大会: 同じ性別・年齢区分のレコードのみ差し替え（他区分は保持）
        if results:
            gender_val = results[0]["gender"]
            age_group_val = results[0]["age_group"]
            conn.execute(
                "DELETE FROM results WHERE meeting_id = ? AND gender = ? AND age_group = ?",
                (meeting_id, gender_val, age_group_val)
            )
            logger.info(f"Meeting exists (id={meeting_id}); replacing only {gender_val}/{age_group_val} records.")
        conn.execute("UPDATE meetings SET scraped_at = ? WHERE id = ?", (now, meeting_id))
    else:
        cursor = conn.execute(
            "INSERT INTO meetings (name, date, type, course_type, scraped_at) VALUES (?, ?, ?, ?, ?)",
            (meet_info["name"], date_iso, meet_info.get("type", "公認"),
             meet_info["course_type"], now)
        )
        meeting_id = cursor.lastrowid

    for r in results:
        conn.execute(
            """INSERT INTO results
               (meeting_id, athlete_name, club, age_group, gender, event,
                course_type, time_seconds, time_display, rank, venue, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (meeting_id, r["athlete_name"], r["club"], r["age_group"],
             r["gender"], r["event"], meet_info["course_type"],
             r["time_seconds"], r["time_display"], r.get("rank"),
             meet_info.get("venue"), now)
        )

    conn.commit()
    conn.close()
    return len(results)


def parse_meet_date(year, date_str):
    """'1月17日(土)〜18日(日)' → '2026-01-17' のような ISO 日付に変換"""
    m = re.search(r"(\d+)月\s*(\d+)日", date_str)
    if m:
        month = int(m.group(1))
        day = int(m.group(2))
        return f"{year:04d}-{month:02d}-{day:02d}"
    return f"{year}-01-01"


def parse_jmsa_meet_list(html):
    """主催大会一覧ページ (SCM2026.html等) から大会リストを取得"""
    soup = BeautifulSoup(html, "html.parser")
    meets = []

    for form in soup.find_all("form"):
        hidden_m = form.find("input", {"name": "M"})
        month = int(hidden_m["value"]) if hidden_m else 0

        for tr in form.find_all("tr"):
            cells = tr.find_all(["td", "th"])
            if len(cells) < 3:
                continue

            btn = tr.find("button", {"name": "G"})
            if not btn:
                continue
            meet_id = btn.get("value")
            if not meet_id:
                continue

            date_str = cells[0].get_text(strip=True)
            venue_name = cells[1].get_text(" ", strip=True)
            facility = cells[2].get_text(" ", strip=True) if len(cells) > 2 else ""

            if not date_str or not venue_name:
                continue

            course = "LCM" if "50m" in facility.lower() else "SCM"

            meets.append({
                "meet_id": str(meet_id),
                "month": month,
                "date_str": date_str,
                "name": venue_name,
                "venue": facility,
                "course_type": course,
            })
    return meets


def _age_text_filter(age_filter):
    """区分カラム照合用テキスト。18歳区分のみ18～24歳の7年バンド"""
    if age_filter == 18:
        return "18～24歳"
    return f"{age_filter}～{age_filter + 4}歳"


def _scrape_combo(year, meet_id, gl_value, programs, gender_filter, age_filter):
    """取得済みの種目リストに対して、1性別×1年齢区分の全種目を取得"""
    targets = [p for p in programs if p["gender"] == gender_filter]
    age_label = f"{'M' if gender_filter == 'M' else 'W'}{age_filter}"
    results_all = []
    for prog in targets:
        time.sleep(REQUEST_DELAY)
        params = {
            "Y": year, "M": 0, "G": meet_id, "GL": gl_value,
            "S": 2, "Lap": 1, "Cls": age_filter, "L": 1, "RG": 1,
            "Page": "ProList.php", "P": prog["no"],
        }
        result_html = fetch(f"{BASE}/Record.php", params=params)
        if not result_html:
            continue
        results = parse_result_page(
            result_html, prog["event"], gender_filter, age_label,
            _age_text_filter(age_filter), cls_value=age_filter,
        )
        results_all.extend(results)
    return results_all


def _run_scrape(year, meet_id, gender_filter, age_filter, target, gl_value):
    """共通スクレイプ処理: ProList/Record.phpを叩いて結果を保存"""
    time.sleep(REQUEST_DELAY)
    prog_html = fetch(f"{BASE}/ProList.php", params={"Y": year, "M": 0, "G": meet_id, "GL": gl_value})
    if not prog_html:
        return 0
    programs = parse_program_list(prog_html)
    logger.info(f"Found {len([p for p in programs if p['gender'] == gender_filter])} {gender_filter} events to scrape")

    all_results = _scrape_combo(year, meet_id, gl_value, programs, gender_filter, age_filter)

    if programs:
        # 結果0件でも種目一覧が取得できた大会は登録する
        # (未登録のままだと自動差分更新が毎回同じ大会を再スクレイプするため)
        count = insert_meet_results(target, all_results)
        logger.info(f"Saved {count} records for {target['name']}")
    else:
        logger.warning("No programs found; meeting not registered")

    return len(all_results)


def _resolve_target(year, meet_id, source, course_type=None):
    """一覧ページから対象大会のmeet_info(target)とgl_valueを解決する。

    source: "公認" (mi{year}.php) または "主催" (JMSA/SCM{year}.html)
    戻り値: (target, gl_value)。見つからなければ (None, None)
    """
    if source == "主催":
        html = fetch(f"{BASE}/JMSA/SCM{year}.html")
        if not html:
            return None, None
        meets = parse_jmsa_meet_list(html)
        target = next((m for m in meets if m["meet_id"] == str(meet_id)), None)
        if not target:
            logger.error(f"Meet G={meet_id} not found in JMSA SCM{year}.html")
            return None, None
        target["year"] = year
        month = target.get("month", 1)
        day_m = re.search(r"(\d+)日", target.get("date_str", ""))
        if day_m:
            target["date_iso"] = f"{year:04d}-{month:02d}-{int(day_m.group(1)):02d}"
        else:
            target["date_iso"] = f"{year}-{month:02d}-01"
        target["type"] = "主催"
        gl_value = 1
    else:
        html = fetch(f"{BASE}/Masters/mi{year}.php")
        if not html:
            return None, None
        meets = parse_meet_list(html)
        target = next((m for m in meets if m["meet_id"] == str(meet_id)), None)
        if not target:
            logger.error(f"Meet G={meet_id} not found in {year}")
            return None, None
        target["date_iso"] = parse_meet_date(year, target["date_str"])
        target["type"] = "公認"
        gl_value = year

    if course_type:
        target["course_type"] = course_type
    logger.info(f"Target meet: {target['name']} ({target['date_iso']}) {target['course_type']}")
    return target, gl_value


def scrape_meet(year, meet_id, gender_filter="M", age_filter=40, course_type=None):
    """公認大会 (mi{year}.php) から指定大会の結果を取得"""
    init_db()
    target, gl_value = _resolve_target(year, meet_id, "公認", course_type)
    if not target:
        return 0
    return _run_scrape(year, meet_id, gender_filter, age_filter, target, gl_value)


def scrape_jmsa_meet(year, meet_id, gender_filter="M", age_filter=40, course_type=None):
    """主催大会 (JMSA/SCM{year}.html等) から指定大会の結果を取得"""
    init_db()
    target, gl_value = _resolve_target(year, meet_id, "主催", course_type)
    if not target:
        return 0
    return _run_scrape(year, meet_id, gender_filter, age_filter, target, gl_value)


def scrape_meet_all(year, meet_id, source, genders=("M", "F"), ages=None):
    """1大会の全性別×全年齢区分を一括取得。

    種目一覧(ProList)の取得は1回だけ行い、性別×区分ごとにRecord.phpを叩く。
    区分ごとに insert_meet_results を呼ぶため差分更新(他区分保持)が効く。
    戻り値: {(gender, age): 件数} の辞書。大会が見つからない場合は None
    """
    from config import AGE_GROUPS
    init_db()
    if ages is None:
        ages = AGE_GROUPS

    target, gl_value = _resolve_target(year, meet_id, source)
    if not target:
        return None

    time.sleep(REQUEST_DELAY)
    prog_html = fetch(f"{BASE}/ProList.php", params={"Y": year, "M": 0, "G": meet_id, "GL": gl_value})
    if not prog_html:
        return None
    programs = parse_program_list(prog_html)
    if not programs:
        logger.warning(f"No programs for G={meet_id}; skip")
        return {}

    counts = {}
    for gender in genders:
        for age in ages:
            results = _scrape_combo(year, meet_id, gl_value, programs, gender, age)
            insert_meet_results(target, results)
            counts[(gender, age)] = len(results)
            logger.info(f"G={meet_id} {gender}{age}: {len(results)} records")
    return counts


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, default=2026)
    ap.add_argument("--meet-id", type=int, required=True)
    ap.add_argument("--gender", default="M")
    ap.add_argument("--age", type=int, default=40)
    ap.add_argument("--course", default=None)
    args = ap.parse_args()

    scrape_meet(args.year, args.meet_id, args.gender, args.age, args.course)
