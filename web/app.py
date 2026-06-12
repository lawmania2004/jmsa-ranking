import os
import re
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)
sys.path.insert(0, os.path.join(BASE_DIR, "db"))
sys.path.insert(0, os.path.join(BASE_DIR, "scraper"))

from fastapi import FastAPI, Request, Query
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.concurrency import run_in_threadpool

from config import (
    MY_NAME, EVENTS_SCM, EVENTS_LCM, AGE_GROUPS,
    EVENT_CODES_SCM, EVENT_CODES_LCM,
)
from database import (
    init_db, get_ranking, get_ranking_count, get_last_updated, get_meetings,
    get_meeting_notes, get_japan_record, get_athlete_summary,
)

app = FastAPI(title="JMSA Ranking")

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "templates")

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
templates = Jinja2Templates(directory=TEMPLATE_DIR)

init_db()


def _load_pending_meets():
    import json
    path = os.path.join(BASE_DIR, "db", "pending_meets.json")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return []


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    last_updated = get_last_updated()
    return templates.TemplateResponse("index.html", {
        "request": request,
        "events_scm": EVENTS_SCM,
        "events_lcm": EVENTS_LCM,
        "age_groups": AGE_GROUPS,
        "last_updated": last_updated,
        "my_name": MY_NAME,
        "meeting_notes": get_meeting_notes(),
        "pending_meets": _load_pending_meets(),
    })


@app.get("/api/ranking")
async def api_ranking(
    event: str = Query(...),
    course: str = Query(...),
    gender: str = Query(...),
    age_group: str = Query(...),
    limit: int = Query(50),
    offset: int = Query(0),
    athlete: str = Query(None),
    year: str = Query(None),
):
    year_param = year if year and year != "all" else None
    results = get_ranking(event, course, gender, age_group, limit, offset, athlete, year_param)

    record = get_japan_record(event, course, gender, age_group)

    # DB側の選手名は空白が全角に正規化されているため、空白を除去して比較する
    my_name_key = re.sub(r"\s+", "", MY_NAME)
    for i, r in enumerate(results):
        r["display_rank"] = offset + i + 1
        r["is_me"] = my_name_key in re.sub(r"\s+", "", r.get("athlete_name") or "")
        r["is_jp_new"] = bool(record and r["best_time"] < record["time_seconds"] - 0.005)
        r["is_jp_tie"] = bool(record and abs(r["best_time"] - record["time_seconds"]) <= 0.005)

    total = get_ranking_count(event, course, gender, age_group, athlete, year_param)

    return JSONResponse({
        "results": results,
        "total": total,
        "limit": limit,
        "offset": offset,
        "japan_record": record,
    })


@app.get("/api/athlete")
async def api_athlete(
    course: str = Query(...),
    gender: str = Query(...),
    age_group: str = Query(...),
    athlete: str = Query(...),
    year: str = Query(None),
):
    year_param = year if year and year != "all" else None
    rows = get_athlete_summary(course, gender, age_group, athlete, year_param)

    # 種目を表示順(config定義順)に並べる
    events_order = EVENTS_SCM if course == "SCM" else EVENTS_LCM
    order = {ev: i for i, ev in enumerate(events_order)}
    rows.sort(key=lambda r: (r["athlete_name"], order.get(r["event"], 999)))

    for r in rows:
        rec = get_japan_record(r["event"], course, gender, age_group)
        r["is_jp_new"] = bool(rec and r["time_seconds"] < rec["time_seconds"] - 0.005)
        r["is_jp_tie"] = bool(rec and abs(r["time_seconds"] - rec["time_seconds"]) <= 0.005)

    return JSONResponse({"results": rows})


@app.get("/api/events")
async def api_events(course: str = Query("SCM")):
    if course == "SCM":
        return JSONResponse({"events": EVENTS_SCM})
    else:
        return JSONResponse({"events": EVENTS_LCM})


@app.get("/admin", response_class=HTMLResponse)
async def admin_page(request: Request):
    meetings = get_meetings()
    last_updated = get_last_updated()
    return templates.TemplateResponse("admin.html", {
        "request": request,
        "meetings": meetings,
        "last_updated": last_updated,
    })


@app.post("/admin/scrape_meet")
async def admin_scrape_meet(request: Request):
    data = await request.json()
    year = data.get("year")
    meet_id = data.get("meet_id")
    gender = data.get("gender", "M")
    age = data.get("age", 40)

    if not year or not meet_id:
        return JSONResponse({"status": "error", "message": "year, meet_idは必須です"})

    meet_source = data.get("meet_source", "公認")

    sys.path.insert(0, os.path.join(BASE_DIR, "scraper"))
    if meet_source == "主催":
        from meet_scraper import scrape_jmsa_meet
        scrape_fn = scrape_jmsa_meet
    else:
        from meet_scraper import scrape_meet
        scrape_fn = scrape_meet

    try:
        # スクレイプは数十秒〜数分かかるためスレッドプールで実行(イベントループを塞がない)
        count = await run_in_threadpool(scrape_fn, year, meet_id, gender, age)
        return JSONResponse({
            "status": "ok",
            "message": f"{count}件の記録を保存しました",
            "count": count,
        })
    except Exception as e:
        return JSONResponse({"status": "error", "message": f"エラー: {e}"})


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
