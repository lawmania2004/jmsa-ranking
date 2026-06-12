import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# 自分の名前(ランキングのハイライト用)。公開リポジトリに載せないよう
# .my_name ファイル(git管理外)から読む。無ければハイライトなし。
def _load_my_name():
    path = os.path.join(BASE_DIR, ".my_name")
    if os.path.exists(path):
        with open(path) as f:
            return f.read().strip()
    return ""

MY_NAME = _load_my_name()

# 自動更新の完了通知 (ntfy.sh)。iPhoneのntfyアプリでこのトピックを購読すると通知が届く。
# トピック名は公開リポジトリに載せないよう .ntfy_topic ファイル(git管理外)から読む。
def _load_ntfy_topic():
    path = os.path.join(BASE_DIR, ".ntfy_topic")
    if os.path.exists(path):
        with open(path) as f:
            return f.read().strip()
    return ""

NTFY_TOPIC = os.environ.get("NTFY_TOPIC") or _load_ntfy_topic()

DB_PATH = os.path.join(BASE_DIR, "db", "ranking.db")
LOG_DIR = os.path.join(BASE_DIR, "logs")

BASE_URL = "https://tdsystem.co.jp"
RANKING_URL = f"{BASE_URL}/RecordSCM.php"
RANKING_PAGE_SCM = "JMSA/SCMRanking{year}.html"
RANKING_PAGE_LCM = "JMSA/LCMRanking{year}.html"
MEET_LIST_SCM = f"{BASE_URL}/JMSA/SCM{{year}}.html"
MEET_LIST_LCM = f"{BASE_URL}/JMSA/LCM{{year}}.html"

REQUEST_DELAY = 1.5

AGE_GROUPS = [18, 25, 30, 35, 40, 45, 50, 55, 60, 65, 70, 75, 80, 85, 90, 95, 100]

EVENT_CODES_SCM = {
    "25FR":  {"F": "011", "M": "111"},
    "50FR":  {"F": "012", "M": "112"},
    "100FR": {"F": "013", "M": "113"},
    "200FR": {"F": "014", "M": "114"},
    "400FR": {"F": "015", "M": "115"},
    "800FR": {"F": "016", "M": "116"},
    "1500FR":{"F": "017", "M": "117"},
    "25BK":  {"F": "021", "M": "121"},
    "50BK":  {"F": "022", "M": "122"},
    "100BK": {"F": "023", "M": "123"},
    "200BK": {"F": "024", "M": "124"},
    "25BR":  {"F": "031", "M": "131"},
    "50BR":  {"F": "032", "M": "132"},
    "100BR": {"F": "033", "M": "133"},
    "200BR": {"F": "034", "M": "134"},
    "25FLY": {"F": "041", "M": "141"},
    "50FLY": {"F": "042", "M": "142"},
    "100FLY":{"F": "043", "M": "143"},
    "200FLY":{"F": "044", "M": "144"},
    "100IM": {"F": "053", "M": "153"},
    "200IM": {"F": "054", "M": "154"},
    "400IM": {"F": "055", "M": "155"},
}

EVENT_CODES_LCM = {
    "50FR":  {"F": "012", "M": "112"},
    "100FR": {"F": "013", "M": "113"},
    "200FR": {"F": "014", "M": "114"},
    "400FR": {"F": "015", "M": "115"},
    "800FR": {"F": "016", "M": "116"},
    "1500FR":{"F": "017", "M": "117"},
    "50BK":  {"F": "022", "M": "122"},
    "100BK": {"F": "023", "M": "123"},
    "200BK": {"F": "024", "M": "124"},
    "50BR":  {"F": "032", "M": "132"},
    "100BR": {"F": "033", "M": "133"},
    "200BR": {"F": "034", "M": "134"},
    "50FLY": {"F": "042", "M": "142"},
    "100FLY":{"F": "043", "M": "143"},
    "200FLY":{"F": "044", "M": "144"},
    "200IM": {"F": "054", "M": "154"},
    "400IM": {"F": "055", "M": "155"},
}

EVENTS_SCM = list(EVENT_CODES_SCM.keys())
EVENTS_LCM = list(EVENT_CODES_LCM.keys())
