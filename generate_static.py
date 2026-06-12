#!/usr/bin/env python3
"""GitHub Pages用の静的データ(docs/data/*.json)を生成する。

- docs/index.html, docs/static/* は手書き(再生成しない)
- 本スクリプトは data/*.json と meta.json のみを書き出す
- 週次自動更新(auto_update.py)の最後に呼ばれ、git pushで公開される

データ形式 (docs/data/{course}_{age_group}.json):
  [{"e":種目,"n":選手名,"c":クラブ,"t":表示タイム,"s":秒,
    "m":大会名,"d":大会日,"y":年,"v":会場}, ...]
  ※ 選手×種目×年ごとのベストのみ。年度フィルタ・全期間集約はクライアントJSで行う。
"""
import os
import sys
import json
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)
sys.path.insert(0, os.path.join(BASE_DIR, "db"))

from config import EVENTS_SCM, EVENTS_LCM, AGE_GROUPS
from database import get_connection, get_meeting_notes, get_last_updated

DOCS_DIR = os.path.join(BASE_DIR, "docs")
DATA_DIR = os.path.join(DOCS_DIR, "data")
PENDING_JSON = os.path.join(BASE_DIR, "db", "pending_meets.json")


def main():
    os.makedirs(DATA_DIR, exist_ok=True)
    conn = get_connection()

    rows = conn.execute("""
        SELECT r.event, r.athlete_name, r.club, r.time_display, r.time_seconds,
               r.age_group, r.course_type, r.venue,
               m.name AS meeting_name, m.date AS meeting_date,
               CAST(strftime('%Y', m.date) AS INTEGER) AS year
        FROM results r JOIN meetings m ON r.meeting_id = m.id
    """).fetchall()
    conn.close()

    # (course, age_group) → (athlete, event, year) → ベスト行
    buckets = {}
    for r in rows:
        bkey = (r["course_type"], r["age_group"])
        akey = (r["athlete_name"], r["event"], r["year"])
        best = buckets.setdefault(bkey, {})
        cur = best.get(akey)
        if cur is None or r["time_seconds"] < cur["time_seconds"]:
            best[akey] = r

    # 古いファイルを掃除してから書き出し
    for f in os.listdir(DATA_DIR):
        if f.endswith(".json"):
            os.remove(os.path.join(DATA_DIR, f))

    years = set()
    for (course, age_group), best in buckets.items():
        out = []
        for r in sorted(best.values(), key=lambda x: (x["event"], x["time_seconds"])):
            years.add(r["year"])
            out.append({
                "e": r["event"], "n": r["athlete_name"], "c": r["club"] or "",
                "t": r["time_display"], "s": r["time_seconds"],
                "m": r["meeting_name"], "d": r["meeting_date"],
                "y": r["year"], "v": r["venue"] or "",
            })
        path = os.path.join(DATA_DIR, f"{course}_{age_group}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, separators=(",", ":"))

    pending = []
    if os.path.exists(PENDING_JSON):
        with open(PENDING_JSON, encoding="utf-8") as f:
            pending = json.load(f)

    # 日本記録 (japan_recordsテーブルが無い環境でも動くように防御)
    records = {}
    records_as_of = None
    conn = get_connection()
    try:
        for r in conn.execute("SELECT * FROM japan_records").fetchall():
            key = f"{r['course_type']}_{r['age_group']}_{r['event']}"
            records[key] = {
                "n": r["holder"], "c": r["club"] or "",
                "t": r["time_display"], "s": r["time_seconds"],
                "d": r["record_date"] or "",
            }
            records_as_of = r["as_of"]
    except Exception:
        pass
    conn.close()
    with open(os.path.join(DATA_DIR, "records.json"), "w", encoding="utf-8") as f:
        json.dump({"as_of": records_as_of, "records": records}, f,
                  ensure_ascii=False, separators=(",", ":"))

    meta = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "last_updated": get_last_updated(),
        "events_scm": EVENTS_SCM,
        "events_lcm": EVENTS_LCM,
        "age_groups": AGE_GROUPS,
        "years": sorted(years, reverse=True),
        "notes": get_meeting_notes(),
        "pending": pending,
    }
    with open(os.path.join(DATA_DIR, "meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, separators=(",", ":"))

    total = sum(len(b) for b in buckets.values())
    print(f"generated: {len(buckets)} data files, {total} entries, meta.json")


if __name__ == "__main__":
    main()
