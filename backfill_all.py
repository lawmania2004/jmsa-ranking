#!/usr/bin/env python3
"""今年の全大会(tdsystem掲載分)を全性別×全年齢区分でバックフィルする一回限りのスクリプト。

- 主催・公認の両一覧から開催済み大会を列挙し、scrape_meet_all で全区分取得
- 大会単位のチェックポイント (logs/backfill_done.json) があるため、
  中断しても再実行すれば続きから処理される
- 完走後: ntfy通知 → 完了マーカー作成 → launchdジョブを自己解除
- PDF配布のみの大会(奈良・ひのくに・東北・湘南平塚)は対象外

手動実行: caffeinate -i python3 backfill_all.py
"""
import os
import re
import sys
import json
import logging
import subprocess
import warnings
from datetime import date

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
        logging.FileHandler(os.path.join(LOG_DIR, "backfill.log"), encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)

CHECKPOINT = os.path.join(LOG_DIR, "backfill_done.json")
COMPLETED_MARKER = os.path.join(LOG_DIR, "backfill_completed")
LAUNCHD_LABEL = "com.jmsa.ranking.backfill"
PLIST = os.path.expanduser(f"~/Library/LaunchAgents/{LAUNCHD_LABEL}.plist")


def load_checkpoint():
    if os.path.exists(CHECKPOINT):
        with open(CHECKPOINT) as f:
            return set(json.load(f))
    return set()


def save_checkpoint(done):
    with open(CHECKPOINT, "w") as f:
        json.dump(sorted(done), f, ensure_ascii=False)


def list_held_meets(year, today_iso):
    """両一覧ページから開催済み大会を (source, meet_id, name, date_iso) で列挙"""
    from meet_scraper import fetch, parse_jmsa_meet_list, parse_meet_list, parse_meet_date, BASE

    meets = []
    html = fetch(f"{BASE}/JMSA/SCM{year}.html")
    if html:
        for m in parse_jmsa_meet_list(html):
            month = m.get("month", 1)
            dm = re.search(r"(\d+)日", m.get("date_str", ""))
            date_iso = (
                f"{year:04d}-{month:02d}-{int(dm.group(1)):02d}" if dm
                else f"{year}-{month:02d}-01"
            )
            if date_iso <= today_iso:
                meets.append(("主催", int(m["meet_id"]), m["name"], date_iso))
    html = fetch(f"{BASE}/Masters/mi{year}.php")
    if html:
        for m in parse_meet_list(html):
            if not m.get("meet_id"):
                continue
            date_iso = parse_meet_date(year, m["date_str"])
            if date_iso <= today_iso:
                meets.append(("公認", int(m["meet_id"]), m["name"], date_iso))
    return meets


def notify(title, message):
    if not NTFY_TOPIC:
        return
    import requests
    try:
        requests.post(
            "https://ntfy.sh",
            json={
                "topic": NTFY_TOPIC,
                "title": title,
                "message": message,
                "tags": ["swimmer"],
            },
            timeout=15,
        )
    except Exception as e:
        logger.error(f"ntfy送信失敗: {e}")


def self_disable():
    """launchdの定期起動を解除(完走後はもう不要)"""
    if os.path.exists(PLIST):
        os.remove(PLIST)
        logger.info("plist削除済み")
    # bootoutは自分自身のプロセスを終了させるため最後に呼ぶ
    subprocess.run(
        ["launchctl", "bootout", f"gui/{os.getuid()}/{LAUNCHD_LABEL}"],
        check=False, capture_output=True,
    )


def main():
    if os.path.exists(COMPLETED_MARKER):
        logger.info("バックフィルは完了済み。何もしません。")
        return

    today_iso = date.today().isoformat()
    year = date.today().year
    logger.info(f"=== バックフィル開始 ({today_iso}) ===")

    from meet_scraper import scrape_meet_all

    meets = list_held_meets(year, today_iso)
    done = load_checkpoint()
    pending = [m for m in meets if f"{m[0]}:{m[1]}" not in done]
    logger.info(f"対象 {len(meets)}大会 / 残り {len(pending)}大会")

    lines = []
    grand_total = 0
    failed = []
    for src, gid, name, d in pending:
        logger.info(f"--- [{src}] G={gid} {name} ({d}) ---")
        try:
            counts = scrape_meet_all(year, gid, src)
        except Exception as e:
            logger.error(f"G={gid} 失敗: {e}")
            failed.append(f"[{src}] G={gid} {name}")
            continue
        if counts is None:
            failed.append(f"[{src}] G={gid} {name} (大会情報取得失敗)")
            continue
        total = sum(counts.values())
        m_total = sum(v for (g, _), v in counts.items() if g == "M")
        f_total = sum(v for (g, _), v in counts.items() if g == "F")
        grand_total += total
        lines.append(f"{name} ({d}): 計{total} (男{m_total}/女{f_total})")
        done.add(f"{src}:{gid}")
        save_checkpoint(done)

    summary = "\n".join(lines) if lines else "新規処理なし"
    summary += f"\n\n総登録: {grand_total}件"
    if failed:
        summary += "\n失敗:\n" + "\n".join(failed)
    logger.info(summary)

    if failed:
        # 失敗があれば自己解除せず、翌晩の再実行でリトライさせる
        notify("バックフィル一部失敗 (翌晩リトライ)", summary)
        logger.info("=== 一部失敗のため再実行待ち ===")
        return

    with open(COMPLETED_MARKER, "w") as f:
        f.write(today_iso)
    try:
        from auto_update import publish_static
        publish_static()
    except Exception as e:
        logger.error(f"静的サイト公開に失敗: {e}")
    notify("バックフィル完了", summary)
    logger.info("=== バックフィル完了 ===")
    self_disable()


if __name__ == "__main__":
    main()
