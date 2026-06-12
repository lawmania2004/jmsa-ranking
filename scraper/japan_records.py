"""日本マスターズ水泳協会の日本記録PDF(短水路・長水路)を取得・解析してDBに保存する。

PDFは毎年1月1日・7月1日付で更新される:
  https://www.masters-swim.or.jp/record_10nihonkiroku.php
  → /pdf/records/rd_short_*.pdf, /pdf/records/rd_long_*.pdf

PDF構造: 性別(＜女子＞/＜男子＞) → 種目セクション(■自由形■等) →
距離ヘッダ行(25m 50m...) → 年齢区分ごとに4行ブロック
  (開始年齢+タイム / 氏名 / 所属 / 終了年齢+樹立日)。
氏名に空白が含まれるため、列の割当はx座標で行う。
"""
import io
import os
import re
import sys
import unicodedata
import logging
import warnings
import requests

warnings.filterwarnings("ignore")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)
sys.path.insert(0, os.path.join(BASE_DIR, "scraper"))
sys.path.insert(0, os.path.join(BASE_DIR, "db"))

from parser import parse_time_to_seconds
from database import get_connection

logger = logging.getLogger(__name__)

SITE = "https://www.masters-swim.or.jp"
LIST_PAGE = f"{SITE}/record_10nihonkiroku.php"

STROKES = {
    "自由形": "FR", "背泳ぎ": "BK", "平泳ぎ": "BR",
    "バタフライ": "FLY", "個人メドレー": "IM",
}
TIME_RE = re.compile(r"^\d{1,2}:\d{2}\.\d{2}$|^\d{2}\.\d{2}$")
DATE_RE = re.compile(r"^\d{4}/\d{2}/\d{2}$")
DIST_RE = re.compile(r"^(\d+)m$")
COL_HALF_WIDTH = 30  # 列中心からの許容x距離


def init_records_table():
    conn = get_connection()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS japan_records (
            course_type TEXT NOT NULL,
            gender TEXT NOT NULL,
            age_group TEXT NOT NULL,
            event TEXT NOT NULL,
            time_display TEXT NOT NULL,
            time_seconds REAL NOT NULL,
            holder TEXT,
            club TEXT,
            record_date TEXT,
            as_of TEXT,
            UNIQUE(course_type, gender, age_group, event)
        )
    """)
    conn.commit()
    conn.close()


def find_pdf_urls():
    """記録一覧ページから短水路・長水路の日本記録PDF候補を新しい順に返す"""
    resp = requests.get(LIST_PAGE, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
    resp.encoding = resp.apparent_encoding
    out = {"SCM": [], "LCM": []}
    for m in re.finditer(r'href="(/pdf/records/(rd_(short|long))[^"]*?)"', resp.text):
        url = SITE + m.group(1).split("?")[0]
        course = "SCM" if m.group(3) == "short" else "LCM"
        if url not in out[course]:
            out[course].append(url)
    # ファイル名中の数字(日付)が大きい順
    for c in out:
        out[c].sort(key=lambda u: re.sub(r"\D", "", u.rsplit("/", 1)[-1]), reverse=True)
    return out


def fetch_pdf(urls):
    """候補URLを新しい順に試し、最初に取得できたPDFを返す"""
    for url in urls:
        try:
            r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=60)
            if r.status_code == 200 and r.content[:4] == b"%PDF":
                return url, r.content
        except requests.RequestException:
            continue
    return None, None


def _parse_page(words, gender, headers, records):
    """1ページ分を解析してrecordsに追加。

    左右に2テーブル並ぶページでも行(年齢ブロック)は共有されているため、
    ページ全体を1つの状態機械で処理し、列ごとに種目(ヘッダ位置から判定)を割り当てる。
    """
    cols = []   # [(x_center, event_code)]
    block = None

    def stroke_for_x(x0):
        """列x0の属する種目 = それより左にある最も近い■ヘッダ"""
        cand = [(hx, name) for hx, name in headers if hx <= x0 + 5]
        if not cand:
            return None
        return max(cand)[1]

    def close_block(b):
        for ci, (cx, event) in enumerate(cols):
            t = b["times"].get(ci)
            if not t or event is None:
                continue
            secs = parse_time_to_seconds(t)
            if secs is None:
                continue
            cell_lines = b["cells"].get(ci, [])
            holder = cell_lines[0] if cell_lines else ""
            club = cell_lines[1] if len(cell_lines) > 1 else ""
            records.append({
                "gender": gender,
                "age_group": f"{'M' if gender == 'M' else 'W'}{b['age']}",
                "event": event,
                "time_display": t,
                "time_seconds": secs,
                "holder": holder,
                "club": club,
                "record_date": b["dates"].get(ci, ""),
            })

    def col_of(w):
        xc = w["x0"] + (w["x1"] - w["x0"]) / 2
        best, bd = None, 1e9
        for i, (cx, _) in enumerate(cols):
            d = abs(xc - cx)
            if d < bd:
                best, bd = i, d
        return best if bd <= COL_HALF_WIDTH + 15 else None

    lines = {}
    for w in words:
        lines.setdefault(round(w["top"] / 3), []).append(w)

    for _, ws in sorted(lines.items()):
        ws = sorted(ws, key=lambda w: w["x0"])
        # 全角数字・全角m対策 (長水路男子ページは「５０ｍ」表記)
        texts = [unicodedata.normalize("NFKC", w["text"]) for w in ws]
        joined = "".join(texts)

        # 距離ヘッダ行 (左右テーブル分が1行に並ぶ)
        if all(DIST_RE.match(t) for t in texts) and len(texts) >= 2:
            cols = []
            for w, t in zip(ws, texts):
                dist = DIST_RE.match(t).group(1)
                stroke = stroke_for_x(w["x0"])
                event = f"{dist}{STROKES[stroke]}" if stroke in STROKES else None
                cols.append((w["x0"] + (w["x1"] - w["x0"]) / 2, event))
            continue
        if not cols:
            continue

        first = texts[0]
        # 開始年齢+タイム行
        if first.isdigit() and len(ws) > 1 and any(TIME_RE.match(t) for t in texts[1:]):
            if block:
                close_block(block)
            block = {"age": int(first), "times": {}, "cells": {}, "dates": {}}
            for w, t in zip(ws[1:], texts[1:]):
                if TIME_RE.match(t):
                    ci = col_of(w)
                    if ci is not None and ci not in block["times"]:
                        block["times"][ci] = t
            continue
        # 終了年齢+樹立日行
        if block and first.isdigit() and all(DATE_RE.match(t) for t in texts[1:]):
            for w, t in zip(ws[1:], texts[1:]):
                ci = col_of(w)
                if ci is not None and ci not in block["dates"]:
                    block["dates"][ci] = t
            close_block(block)
            block = None
            continue
        if joined.strip() == "～":
            continue
        # ブロック内: 氏名行・所属行 (列ごとに行単位で蓄積)
        if block:
            line_cells = {}
            for w in ws:
                if w["text"] == "～":
                    continue
                ci = col_of(w)
                if ci is None:
                    continue
                line_cells.setdefault(ci, []).append(w["text"])
            for ci, parts in line_cells.items():
                block["cells"].setdefault(ci, []).append(" ".join(parts))
    if block:
        close_block(block)


def parse_record_pdf(content):
    """PDFを解析して records(list of dict) と as_of を返す"""
    import pdfplumber

    records = []
    as_of = None

    with pdfplumber.open(io.BytesIO(content)) as pdf:
        for page in pdf.pages:
            words = page.extract_words(keep_blank_chars=False)
            text = page.extract_text() or ""

            m = re.search(r"(\d{4})年(\d+)月(\d+)日現在", text)
            if m and not as_of:
                as_of = f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
            if "＜女子＞" in text:
                gender = "F"
            elif "＜男子＞" in text:
                gender = "M"
            else:
                continue  # ＜混合＞リレー等はスキップ

            headers = []
            for w in words:
                hm = re.match(r"■(.+?)■", w["text"])
                if hm:
                    headers.append((w["x0"], hm.group(1).strip()))
            headers.sort()
            if not headers or not any(name in STROKES for _, name in headers):
                continue  # リレーページ等はスキップ

            _parse_page(words, gender, headers, records)
    return records, as_of


def update_japan_records():
    """最新PDFを取得してDBを更新。戻り値: {course: (as_of, 件数)} (更新なしはNone)"""
    init_records_table()
    urls = find_pdf_urls()
    result = {}
    conn = get_connection()
    for course in ("SCM", "LCM"):
        url, content = fetch_pdf(urls.get(course, []))
        if not content:
            logger.error(f"日本記録PDF取得失敗 ({course})")
            result[course] = None
            continue
        records, as_of = parse_record_pdf(content)
        if not records:
            logger.error(f"日本記録PDF解析0件 ({course}) {url}")
            result[course] = None
            continue
        cur = conn.execute(
            "SELECT as_of FROM japan_records WHERE course_type = ? LIMIT 1", (course,)
        ).fetchone()
        if cur and cur["as_of"] == as_of:
            logger.info(f"日本記録は最新 ({course} {as_of})")
            result[course] = None
            continue
        conn.execute("DELETE FROM japan_records WHERE course_type = ?", (course,))
        for r in records:
            conn.execute(
                """INSERT OR REPLACE INTO japan_records
                   (course_type, gender, age_group, event, time_display,
                    time_seconds, holder, club, record_date, as_of)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (course, r["gender"], r["age_group"], r["event"], r["time_display"],
                 r["time_seconds"], r["holder"], r["club"], r["record_date"], as_of),
            )
        conn.commit()
        logger.info(f"日本記録更新 ({course} {as_of}): {len(records)}件 from {url}")
        result[course] = (as_of, len(records))
    conn.close()
    return result


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    res = update_japan_records()
    for course, r in res.items():
        print(course, r if r else "更新なし/失敗")
