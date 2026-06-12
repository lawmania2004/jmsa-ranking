import requests
import time
import logging
import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)
sys.path.insert(0, os.path.join(BASE_DIR, "scraper"))
sys.path.insert(0, os.path.join(BASE_DIR, "db"))

from config import (
    BASE_URL, RANKING_PAGE_SCM, AGE_GROUPS,
    EVENT_CODES_SCM, EVENT_CODES_LCM, REQUEST_DELAY, LOG_DIR
)
from parser import parse_ranking_page
from database import init_db, insert_ranking_results

os.makedirs(LOG_DIR, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(os.path.join(LOG_DIR, "scraper.log"), encoding="utf-8"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) JMSA-Ranking-Bot/1.0"
})


def fetch_ranking_page(year, course_type, event_code, age_group):
    if course_type == "SCM":
        page = RANKING_PAGE_SCM.format(year=year)
    else:
        page = f"JMSA/LCMRanking{year}.html"

    params = {
        "Y": str(year),
        "Page": page,
        "Cls": str(age_group),
        "P": event_code,
    }
    url = f"{BASE_URL}/RecordSCM.php"

    try:
        resp = SESSION.get(url, params=params, timeout=30)
        resp.encoding = resp.apparent_encoding
        resp.raise_for_status()
        return resp.text
    except requests.RequestException as e:
        logger.error(f"Failed to fetch {url} with params {params}: {e}")
        return None


def scrape_rankings(year=2025, course_type="SCM", events=None, age_groups=None):
    init_db()

    if course_type == "SCM":
        event_codes = EVENT_CODES_SCM
    else:
        event_codes = EVENT_CODES_LCM

    if events:
        event_codes = {k: v for k, v in event_codes.items() if k in events}

    if age_groups is None:
        age_groups = AGE_GROUPS

    all_results = []
    total_events = len(event_codes) * 2 * len(age_groups)
    processed = 0

    for event_name, gender_codes in event_codes.items():
        for gender, code in gender_codes.items():
            gender_label = "男子" if gender == "M" else "女子"
            age_prefix = "M" if gender == "M" else "W"

            for age in age_groups:
                processed += 1
                age_group = f"{age_prefix}{age}"
                logger.info(
                    f"[{processed}/{total_events}] "
                    f"Fetching {course_type} {gender_label} {event_name} {age_group}"
                )

                html = fetch_ranking_page(year, course_type, code, age)
                if html is None:
                    continue

                results = parse_ranking_page(
                    html, event_name, gender, age_group, course_type
                )
                all_results.extend(results)
                logger.info(f"  -> {len(results)} records found")

                time.sleep(REQUEST_DELAY)

    if all_results:
        count = insert_ranking_results(all_results, course_type, year)
        logger.info(f"Total: {count} records saved to database")
    else:
        logger.warning("No results found")

    return len(all_results)


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="JMSA Ranking Scraper")
    ap.add_argument("--year", type=int, default=2025)
    ap.add_argument("--course", choices=["SCM", "LCM"], default="SCM")
    ap.add_argument("--event", type=str, help="Single event, e.g. 50FR")
    ap.add_argument("--age", type=int, help="Single age group, e.g. 30")
    args = ap.parse_args()

    events = [args.event] if args.event else None
    age_groups = [args.age] if args.age else None

    scrape_rankings(
        year=args.year,
        course_type=args.course,
        events=events,
        age_groups=age_groups,
    )
