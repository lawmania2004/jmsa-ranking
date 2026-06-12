import re
from bs4 import BeautifulSoup


def parse_time_to_seconds(time_str):
    """Convert time string like '26.65', '1:02.34', '2:11.92' to seconds."""
    time_str = time_str.strip()
    if not time_str or time_str == "-":
        return None

    time_str = time_str.replace("：", ":").replace("．", ".")

    match = re.match(r'^(\d+):(\d{2})\.(\d{1,2})$', time_str)
    if match:
        minutes = int(match.group(1))
        seconds = int(match.group(2))
        centis = match.group(3).ljust(2, '0')
        return minutes * 60 + seconds + int(centis) / 100

    match = re.match(r'^(\d+)\.(\d{1,2})$', time_str)
    if match:
        seconds = int(match.group(1))
        centis = match.group(2).ljust(2, '0')
        return seconds + int(centis) / 100

    return None


def parse_ranking_page(html, event, gender, age_group, course_type):
    """Parse a ranking page and return list of result dicts."""
    soup = BeautifulSoup(html, "html.parser")
    results = []

    tables = soup.find_all("table")
    if len(tables) < 2:
        return results

    data_table = tables[1]
    rows = data_table.find_all("tr")

    for row in rows:
        cells = row.find_all("td")
        if len(cells) < 6:
            continue

        rank_text = cells[0].get_text(strip=True)
        if not rank_text.isdigit():
            continue

        rank = int(rank_text)
        athlete_name = cells[1].get_text(strip=True)
        club = cells[2].get_text(strip=True)
        time_display = cells[3].get_text(strip=True)
        venue = cells[5].get_text(strip=True)

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
            "venue": venue,
            "event": event,
            "gender": gender,
            "age_group": age_group,
        })

    return results


def parse_event_list_page(html):
    """Parse the event list page to get available events with their P codes."""
    soup = BeautifulSoup(html, "html.parser")
    events = []
    buttons = soup.find_all("button", {"type": "submit", "name": "P"})
    for btn in buttons:
        text = btn.get_text(strip=True)
        value = btn.get("value", "")
        if value and text:
            events.append({"text": text, "code": value})
    return events
