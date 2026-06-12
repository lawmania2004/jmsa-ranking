import sqlite3
import os
from datetime import datetime

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import DB_PATH


def get_connection():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    conn = get_connection()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS meetings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            date DATE,
            type TEXT NOT NULL,
            course_type TEXT NOT NULL,
            scraped_at DATETIME NOT NULL,
            UNIQUE(name, date, course_type)
        );

        CREATE TABLE IF NOT EXISTS results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            meeting_id INTEGER,
            athlete_name TEXT NOT NULL,
            club TEXT,
            age_group TEXT NOT NULL,
            gender TEXT NOT NULL,
            event TEXT NOT NULL,
            course_type TEXT NOT NULL,
            time_seconds REAL NOT NULL,
            time_display TEXT NOT NULL,
            rank INTEGER,
            venue TEXT,
            created_at DATETIME NOT NULL,
            FOREIGN KEY (meeting_id) REFERENCES meetings(id)
        );

        CREATE INDEX IF NOT EXISTS idx_results_event ON results(event, course_type, gender, age_group);
        CREATE INDEX IF NOT EXISTS idx_results_athlete ON results(athlete_name);
        CREATE INDEX IF NOT EXISTS idx_results_time ON results(time_seconds);
    """)
    # 既存DBへのマイグレーション: 注意書きカラム(部分集計大会の注記など)
    cols = [r["name"] for r in conn.execute("PRAGMA table_info(meetings)").fetchall()]
    if "note" not in cols:
        conn.execute("ALTER TABLE meetings ADD COLUMN note TEXT")
    conn.commit()
    conn.close()


def get_athlete_summary(course_type, gender, age_group, athlete_name, year=None):
    """選手名(部分一致)に該当する選手の全種目サマリ。

    各種目について、その選手のベストタイム・種目内順位(同タイムは同順位)・
    種目内人数・大会情報を返す。
    """
    conn = get_connection()
    where = "r.course_type = ? AND r.gender = ? AND r.age_group = ?"
    params = [course_type, gender, age_group]
    if year:
        where += " AND strftime('%Y', m.date) = ?"
        params.append(str(year))

    query = f"""
        WITH filtered AS (
            SELECT r.athlete_name, r.event, r.club, r.time_seconds, r.time_display,
                   r.venue, m.name AS meeting_name, m.date AS meeting_date,
                   ROW_NUMBER() OVER (
                       PARTITION BY r.athlete_name, r.event
                       ORDER BY r.time_seconds ASC
                   ) AS rn
            FROM results r
            JOIN meetings m ON r.meeting_id = m.id
            WHERE {where}
        ),
        bests AS (
            SELECT *,
                   RANK() OVER (PARTITION BY event ORDER BY time_seconds ASC) AS rank,
                   COUNT(*) OVER (PARTITION BY event) AS total
            FROM filtered WHERE rn = 1
        )
        SELECT athlete_name, event, club, time_seconds, time_display,
               meeting_name, meeting_date, venue, rank, total
        FROM bests
        WHERE REPLACE(REPLACE(athlete_name, '　', ''), ' ', '') LIKE ?
        ORDER BY athlete_name
    """
    import re as _re
    params.append("%" + _re.sub(r"\s+", "", athlete_name) + "%")
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_japan_record(event, course_type, gender, age_group):
    """該当条件の日本記録を返す (japan_recordsテーブル未作成なら None)"""
    conn = get_connection()
    try:
        row = conn.execute(
            """SELECT holder, club, time_display, time_seconds, record_date, as_of
               FROM japan_records
               WHERE event = ? AND course_type = ? AND gender = ? AND age_group = ?""",
            (event, course_type, gender, age_group),
        ).fetchone()
    except sqlite3.OperationalError:
        row = None
    conn.close()
    return dict(row) if row else None


def get_meeting_notes():
    """注意書き付きの大会一覧 (未集計・部分集計の注記表示用)"""
    conn = get_connection()
    rows = conn.execute(
        "SELECT name, date, note FROM meetings WHERE note IS NOT NULL AND note != '' ORDER BY date"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def insert_ranking_results(results_list, course_type, year):
    conn = get_connection()
    now = datetime.now().isoformat()

    meeting_name = f"{year}年度総合ランキング"
    meeting_type = "主催"

    cursor = conn.execute(
        "SELECT id FROM meetings WHERE name = ? AND course_type = ?",
        (meeting_name, course_type)
    )
    row = cursor.fetchone()
    if row:
        meeting_id = row["id"]
        conn.execute("DELETE FROM results WHERE meeting_id = ?", (meeting_id,))
    else:
        cursor = conn.execute(
            "INSERT INTO meetings (name, date, type, course_type, scraped_at) VALUES (?, ?, ?, ?, ?)",
            (meeting_name, f"{year}-01-01", meeting_type, course_type, now)
        )
        meeting_id = cursor.lastrowid

    conn.execute(
        "UPDATE meetings SET scraped_at = ? WHERE id = ?",
        (now, meeting_id)
    )

    for r in results_list:
        conn.execute(
            """INSERT INTO results
               (meeting_id, athlete_name, club, age_group, gender, event,
                course_type, time_seconds, time_display, rank, venue, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (meeting_id, r["athlete_name"], r["club"], r["age_group"],
             r["gender"], r["event"], course_type,
             r["time_seconds"], r["time_display"], r.get("rank"),
             r.get("venue"), now)
        )

    conn.commit()
    conn.close()
    return len(results_list)


def get_ranking(event, course_type, gender, age_group, limit=50, offset=0,
                athlete_name=None, year=None):
    conn = get_connection()
    where = "r.event = ? AND r.course_type = ? AND r.gender = ? AND r.age_group = ?"
    params = [event, course_type, gender, age_group]

    if year:
        where += " AND strftime('%Y', m.date) = ?"
        params.append(str(year))

    if athlete_name:
        where += " AND r.athlete_name LIKE ?"
        params.append(f"%{athlete_name}%")

    # 選手ごとにフィルタ後のベストタイム1件を取る。
    # 付随情報(クラブ・大会名等)も同じ行から取るため、年度フィルタと表示が必ず一致する。
    query = f"""
        WITH filtered AS (
            SELECT r.athlete_name, r.club, r.time_seconds, r.time_display,
                   r.venue, r.age_group,
                   m.name AS meeting_name, m.date AS meeting_date,
                   ROW_NUMBER() OVER (
                       PARTITION BY r.athlete_name
                       ORDER BY r.time_seconds ASC
                   ) AS rn
            FROM results r
            JOIN meetings m ON r.meeting_id = m.id
            WHERE {where}
        )
        SELECT athlete_name, club, time_seconds AS best_time, time_display,
               meeting_name, meeting_date, venue, age_group
        FROM filtered
        WHERE rn = 1
        ORDER BY best_time ASC
        LIMIT ? OFFSET ?
    """
    params.extend([limit, offset])

    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_ranking_count(event, course_type, gender, age_group, athlete_name=None, year=None):
    conn = get_connection()
    query = """
        SELECT COUNT(DISTINCT r.athlete_name) as cnt
        FROM results r
        JOIN meetings m ON r.meeting_id = m.id
        WHERE r.event = ? AND r.course_type = ? AND r.gender = ? AND r.age_group = ?
    """
    params = [event, course_type, gender, age_group]
    if year:
        query += " AND strftime('%Y', m.date) = ?"
        params.append(str(year))
    if athlete_name:
        query += " AND r.athlete_name LIKE ?"
        params.append(f"%{athlete_name}%")

    row = conn.execute(query, params).fetchone()
    conn.close()
    return row["cnt"]


def get_last_updated():
    conn = get_connection()
    row = conn.execute("SELECT MAX(scraped_at) as last FROM meetings").fetchone()
    conn.close()
    return row["last"] if row else None


def get_meetings():
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM meetings ORDER BY scraped_at DESC"
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


if __name__ == "__main__":
    init_db()
    print(f"Database initialized at {DB_PATH}")
