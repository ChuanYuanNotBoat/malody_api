import requests
from bs4 import BeautifulSoup
import pandas as pd
from openpyxl import load_workbook
from datetime import datetime, timedelta
import time
import os
import gc
import logging
import sys
import sqlite3
import subprocess
import json
from threading import Lock, Thread
import signal
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
import queue
import re
import argparse
from typing import Any, Dict, List, Optional, Set, Tuple

# 棰滆壊鏀寔锛堜粎鍦ㄧ粓绔彲鐢ㄦ椂鍚敤锛?
USE_COLOR = hasattr(sys.stdout, 'isatty') and sys.stdout.isatty()
def colorize(text, color_code):
    """Add ANSI color escape sequence when terminal supports color."""
    if USE_COLOR:
        return f"\033[{color_code}m{text}\033[0m"
    return text

# 淇 Python 3.12+ 涓?SQLite datetime 閫傞厤鍣ㄧ殑寮冪敤璀﹀憡
def adapt_datetime(dt):
    return dt.isoformat()

def convert_datetime(s):
    return datetime.fromisoformat(s.decode())

sqlite3.register_adapter(datetime, adapt_datetime)
sqlite3.register_converter("timestamp", convert_datetime)

try:
    from tqdm import tqdm
    HAS_TQDM = True
except ImportError:
    HAS_TQDM = False
    print("tqdm not installed; using simple progress output.")

# 閰嶇疆鏃ュ織
logging.basicConfig(
    filename='crawler.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    filemode='a'
)
logger = logging.getLogger()
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)
logger.addHandler(console_handler)

# Cookie 閰嶇疆锛堣鏍规嵁瀹為檯鎯呭喌鏇存柊锛?
def _load_cookies() -> dict:
    """
    Load cookies from runtime sources, highest priority first:
    1) MALODY_COOKIES_JSON (full JSON string)
    2) MALODY_COOKIES_FILE (json file path, default: cookies.local.json)
    3) MALODY_SESSIONID / MALODY_CSRFTOKEN
    """
    cookies = {}

    cookies_file = os.getenv("MALODY_COOKIES_FILE", "cookies.local.json")
    if os.path.exists(cookies_file):
        try:
            with open(cookies_file, "r", encoding="utf-8") as f:
                file_cookies = json.load(f)
            if isinstance(file_cookies, dict):
                cookies.update(file_cookies)
                logger.info("Loaded crawler cookies from %s", cookies_file)
        except Exception as e:
            logger.warning("Failed to load cookies file %s: %s", cookies_file, e)

    cookies_json = os.getenv("MALODY_COOKIES_JSON")
    if cookies_json:
        try:
            env_cookies = json.loads(cookies_json)
            if isinstance(env_cookies, dict):
                cookies.update(env_cookies)
                logger.info("Loaded crawler cookies from MALODY_COOKIES_JSON")
        except Exception as e:
            logger.warning("Invalid MALODY_COOKIES_JSON: %s", e)

    sessionid = os.getenv("MALODY_SESSIONID")
    csrftoken = os.getenv("MALODY_CSRFTOKEN")
    if sessionid:
        cookies["sessionid"] = sessionid
    if csrftoken:
        cookies["csrftoken"] = csrftoken

    if not cookies.get("sessionid"):
        logger.warning("No sessionid configured for crawler cookies.")
    if not cookies.get("csrftoken"):
        logger.warning("No csrftoken configured for crawler cookies.")

    return cookies


COOKIES = _load_cookies()

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://m.mugzone.net/",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}

BASE_URL = "https://m.mugzone.net/page/all/player?from=0&mode={mode}"
PLAYER_PROFILE_URL = "https://m.mugzone.net/accounts/user/{player_id}"
MODES = list(range(10))
NEW_API_BASE_URL = "https://api.mugzone.net/api"
NEW_API_MM_PAGE_SIZE = 40
DEFAULT_MM_LIMIT = 200
MM_RUN_LOCK_FILE = "tmp/mm_sync.lock"

DB_FILE = "malody_rankings.db"
GIT_REPO_PATH = os.path.dirname(os.path.abspath(__file__))
GIT_COMMIT_MESSAGE = datetime.now().strftime("%Y-%m-%d %H:%M updated")

stop_requested = False
skip_current_requested = False
last_sigint_time = 0.0
SIGINT_STOP_WINDOW_SECONDS = 2.0
stop_lock = Lock()

# 鐜╁閰嶇疆鏂囦欢
PLAYER_CONFIG_FILE = "players.txt"

# 鐜╁鐖彇闃熷垪鍜岀姸鎬侊紙甯﹀叏灞€鍘婚噸闆嗗悎锛?
player_queue = queue.Queue()
_player_set = set()          # 鐢ㄤ簬鍘婚噸
_player_set_lock = Lock()
player_crawl_lock = Lock()
player_crawl_in_progress = False
last_player_crawl_time = None

_api_auth_lock = Lock()
_api_auth_cache: Dict[str, Any] = {}

class SkipCurrentTask(Exception):
    """Soft interrupt: skip current crawl unit and continue."""


def is_stop_requested() -> bool:
    with stop_lock:
        return stop_requested


def consume_skip_request() -> bool:
    global skip_current_requested
    with stop_lock:
        if skip_current_requested:
            skip_current_requested = False
            return True
        return False


def raise_if_skip_requested(context: str = "current task"):
    if consume_skip_request():
        raise SkipCurrentTask(context)


def signal_handler(sig, frame):
    """Handle signals with two-stage Ctrl+C behavior."""
    global stop_requested, skip_current_requested, last_sigint_time
    with stop_lock:
        if sig == signal.SIGTERM:
            stop_requested = True
            logger.warning("Received SIGTERM, stopping crawler safely...")
            return

        now = time.time()
        if (now - last_sigint_time) <= SIGINT_STOP_WINDOW_SECONDS:
            stop_requested = True
            logger.warning("Received Ctrl+C twice quickly: stopping crawler safely...")
        else:
            skip_current_requested = True
            logger.warning("Received Ctrl+C: skip current crawl item/source and continue.")
            logger.warning(
                "Press Ctrl+C again within %.0f seconds to stop the crawler safely.",
                SIGINT_STOP_WINDOW_SECONDS,
            )
        last_sigint_time = now

signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

def get_git_commit_message():
    """鐢熸垚 Git 鎻愪氦娑堟伅"""
    return datetime.now().strftime("%Y-%m-%d %H:%M updated")


class DatabaseManager:
    """鏁版嵁搴撹繛鎺ョ鐞嗗櫒锛堟敮鎸佸绾跨▼鐙珛杩炴帴锛?"""
    _instance = None
    _lock = Lock()

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(DatabaseManager, cls).__new__(cls)
            cls._instance.connections = {}
        return cls._instance

    def get_connection(self, thread_id=None):
        """鑾峰彇褰撳墠绾跨▼鐨勬暟鎹簱杩炴帴"""
        if thread_id is None:
            thread_id = threading.get_ident()
        with self._lock:
            if thread_id not in self.connections:
                self.connections[thread_id] = sqlite3.connect(
                    DB_FILE,
                    detect_types=sqlite3.PARSE_DECLTYPES,
                    timeout=30,
                    check_same_thread=False
                )
                self.connections[thread_id].execute("PRAGMA journal_mode=WAL")
                self.connections[thread_id].execute("PRAGMA busy_timeout = 30000")
            return self.connections[thread_id]

    def close_connection(self, thread_id=None):
        """鍏抽棴鎸囧畾绾跨▼鎴栨墍鏈夎繛鎺?"""
        with self._lock:
            if thread_id is None:
                for conn in self.connections.values():
                    conn.close()
                self.connections = {}
            elif thread_id in self.connections:
                self.connections[thread_id].close()
                del self.connections[thread_id]

    def execute_query(self, query, params=None, thread_id=None):
        """鎵ц鍗曟潯鏌ヨ骞舵彁浜?"""
        conn = self.get_connection(thread_id)
        cursor = conn.cursor()
        try:
            if params:
                cursor.execute(query, params)
            else:
                cursor.execute(query)
            conn.commit()
            return cursor
        except Exception as e:
            conn.rollback()
            raise e

    def executemany_query(self, query, params_list, thread_id=None):
        """鎵归噺鎵ц骞舵彁浜?"""
        conn = self.get_connection(thread_id)
        cursor = conn.cursor()
        try:
            cursor.executemany(query, params_list)
            conn.commit()
            return cursor
        except Exception as e:
            conn.rollback()
            raise e


def _new_api_headers() -> Dict[str, str]:
    return {
        "Accept": "application/json, text/plain, */*",
        "Origin": "https://malody.mugzone.net",
        "Referer": "https://malody.mugzone.net/",
        "User-Agent": HEADERS["User-Agent"],
    }


def _new_api_ensure_guest_auth(session: requests.Session, force_refresh: bool = False) -> Dict[str, Any]:
    global _api_auth_cache
    with _api_auth_lock:
        if (
            not force_refresh
            and _api_auth_cache
            and isinstance(_api_auth_cache.get("ts"), float)
            and (time.time() - _api_auth_cache["ts"] < 1800)
        ):
            return _api_auth_cache

        resp = session.get(
            f"{NEW_API_BASE_URL}/web/auth/guest/wt",
            headers=_new_api_headers(),
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") != 0:
            raise RuntimeError(f"guest auth failed: code={data.get('code')}")

        key = data.get("key") or data.get("token")
        if not key:
            raise RuntimeError("guest auth failed: missing key/token")

        _api_auth_cache = {
            "uid": int(data.get("uid", 1)),
            "key": key,
            "store_key": data.get("storeKey") or data.get("tokenStore") or key,
            "ts": time.time(),
        }
        return _api_auth_cache


def _new_api_get(
    session: requests.Session,
    path: str,
    params: Optional[Dict[str, Any]] = None,
    use_store_key: bool = False,
    retry_on_auth: bool = True,
) -> Dict[str, Any]:
    auth = _new_api_ensure_guest_auth(session)
    request_params = dict(params or {})
    request_params.setdefault("uid", auth["uid"])
    request_params.setdefault("key", auth["store_key"] if use_store_key else auth["key"])

    url = NEW_API_BASE_URL + (path if path.startswith("/") else f"/{path}")
    resp = session.get(url, params=request_params, headers=_new_api_headers(), timeout=30)
    resp.raise_for_status()
    data = resp.json()

    if data.get("code") == -1000 and retry_on_auth:
        _new_api_ensure_guest_auth(session, force_refresh=True)
        return _new_api_get(
            session,
            path=path,
            params=params,
            use_store_key=use_store_key,
            retry_on_auth=False,
        )

    return data


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        if value is None or value == "":
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _acquire_mm_run_lock() -> bool:
    os.makedirs(os.path.dirname(MM_RUN_LOCK_FILE), exist_ok=True)
    try:
        fd = os.open(MM_RUN_LOCK_FILE, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(f"{os.getpid()}\n{datetime.now().isoformat()}\n")
        return True
    except FileExistsError:
        return False


def _release_mm_run_lock():
    try:
        if os.path.exists(MM_RUN_LOCK_FILE):
            os.remove(MM_RUN_LOCK_FILE)
    except OSError:
        logger.warning("failed to remove mm run lock: %s", MM_RUN_LOCK_FILE)


def ensure_mm_schema(cursor: sqlite3.Cursor):
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS player_rankings_mm (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            player_id INTEGER,
            uid TEXT NOT NULL,
            mode INTEGER NOT NULL,
            rank INTEGER NOT NULL,
            name TEXT NOT NULL,
            mm_value INTEGER NOT NULL,
            lv INTEGER,
            acc REAL,
            combo INTEGER,
            pc INTEGER,
            crawl_time TIMESTAMP NOT NULL,
            source TEXT DEFAULT 'mm_global',
            FOREIGN KEY (player_id) REFERENCES player_identity (player_id)
        )
        """
    )
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_player_rankings_mm_uid ON player_rankings_mm(uid)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_player_rankings_mm_mode ON player_rankings_mm(mode)")
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_player_rankings_mm_player_mode ON player_rankings_mm(player_id, mode)"
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS player_mmr_samples (
            sample_id INTEGER PRIMARY KEY AUTOINCREMENT,
            player_id INTEGER,
            uid TEXT NOT NULL,
            mode INTEGER NOT NULL,
            mmr INTEGER NOT NULL,
            mm_rank INTEGER,
            name TEXT,
            crawl_time TIMESTAMP NOT NULL,
            source TEXT NOT NULL,
            FOREIGN KEY (player_id) REFERENCES player_identity (player_id)
        )
        """
    )
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_player_mmr_samples_uid ON player_mmr_samples(uid)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_player_mmr_samples_mode ON player_mmr_samples(mode)")
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_player_mmr_samples_uid_mode_time ON player_mmr_samples(uid, mode, crawl_time)"
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS player_mmr_daily (
            uid TEXT NOT NULL,
            mode INTEGER NOT NULL,
            day TEXT NOT NULL,
            mmr INTEGER NOT NULL,
            mm_rank INTEGER,
            name TEXT,
            sample_time TIMESTAMP NOT NULL,
            source TEXT NOT NULL,
            PRIMARY KEY (uid, mode, day)
        )
        """
    )
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_player_mmr_daily_day ON player_mmr_daily(day)")

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS mm_crawl_status (
            task TEXT PRIMARY KEY,
            last_crawled TIMESTAMP,
            last_success TIMESTAMP,
            crawl_count INTEGER DEFAULT 0,
            success_count INTEGER DEFAULT 0,
            last_error TEXT,
            state_json TEXT
        )
        """
    )


def migrate_database():
    """杩佺Щ鏁版嵁搴擄細涓哄悇琛ㄦ坊鍔?uid 瀛楁锛堝鏋滃皻鏈坊鍔狅級"""
    db_manager = DatabaseManager()
    cursor = db_manager.get_connection().cursor()
    logger.info("寮€濮嬫暟鎹簱杩佺Щ...")
    try:
        # 妫€鏌?player_identity 琛?
        cursor.execute("PRAGMA table_info(player_identity)")
        columns = [column[1] for column in cursor.fetchall()]
        if 'uid' not in columns:
            cursor.execute('ALTER TABLE player_identity ADD COLUMN uid TEXT')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_player_identity_uid ON player_identity(uid)')
            logger.info("宸叉坊鍔?uid 瀛楁鍒?player_identity 琛?")

        cursor.execute("PRAGMA table_info(player_aliases)")
        columns = [column[1] for column in cursor.fetchall()]
        if 'uid' not in columns:
            cursor.execute('ALTER TABLE player_aliases ADD COLUMN uid TEXT')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_player_aliases_uid ON player_aliases(uid)')
            logger.info("宸叉坊鍔?uid 瀛楁鍒?player_aliases 琛?")

        cursor.execute("PRAGMA table_info(player_rankings)")
        columns = [column[1] for column in cursor.fetchall()]
        if 'uid' not in columns:
            cursor.execute('ALTER TABLE player_rankings ADD COLUMN uid TEXT')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_player_rankings_uid ON player_rankings(uid)')
            logger.info("宸叉坊鍔?uid 瀛楁鍒?player_rankings 琛?")

        ensure_mm_schema(cursor)
        logger.info("MM/MMR schema ensured")

        db_manager.get_connection().commit()
        # 璁板綍鍙樻洿鍒?markdown 鏂囦欢
        with open('sql_changes.md', 'w', encoding='utf-8') as f:
            f.write("# SQL鏁版嵁搴撶粨鏋勫彉鏇磋褰昞n\n")
            f.write("## 鐗堟湰 2.0 - 娣诲姞UID鏀寔\n\n")
            f.write("### 鍙樻洿鍐呭\n\n")
            f.write("1. 鍦?`player_identity` 琛ㄤ腑娣诲姞 `uid` 瀛楁\n")
            f.write("2. 鍦?`player_aliases` 琛ㄤ腑娣诲姞 `uid` 瀛楁\n")
            f.write("3. 鍦?`player_rankings` 琛ㄤ腑娣诲姞 `uid` 瀛楁\n")
            f.write("4. 涓哄悇琛ㄧ殑 `uid` 瀛楁鍒涘缓绱㈠紩\n\n")
            f.write("### SQL璇彞\n\n")
            f.write("```sql\n")
            f.write("-- 娣诲姞uid瀛楁\n")
            f.write("ALTER TABLE player_identity ADD COLUMN uid TEXT;\n")
            f.write("ALTER TABLE player_aliases ADD COLUMN uid TEXT;\n")
            f.write("ALTER TABLE player_rankings ADD COLUMN uid TEXT;\n\n")
            f.write("-- 鍒涘缓绱㈠紩\n")
            f.write("CREATE INDEX idx_player_identity_uid ON player_identity(uid);\n")
            f.write("CREATE INDEX idx_player_aliases_uid ON player_aliases(uid);\n")
            f.write("CREATE INDEX idx_player_rankings_uid ON player_rankings(uid);\n")
            f.write("```\n")
        logger.info("鏁版嵁搴撹縼绉诲畬鎴愶紝鍙樻洿宸茶褰曞埌 sql_changes.md")
        return True
    except Exception as e:
        logger.error("鏁版嵁搴撹縼绉诲け璐? %s", e)
        db_manager.get_connection().rollback()
        return False


def init_database():
    """鍒濆鍖栨暟鎹簱锛屽垱寤烘墍鏈夎〃缁撴瀯"""
    db_manager = DatabaseManager()
    cursor = db_manager.get_connection().cursor()
    try:
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS player_identity (
            player_id INTEGER PRIMARY KEY AUTOINCREMENT,
            uid TEXT,
            current_name TEXT NOT NULL,
            first_seen TIMESTAMP NOT NULL,
            last_seen TIMESTAMP NOT NULL
        )
        ''')

        cursor.execute('''
        CREATE TABLE IF NOT EXISTS player_aliases (
            alias_id INTEGER PRIMARY KEY AUTOINCREMENT,
            player_id INTEGER NOT NULL,
            uid TEXT,
            alias TEXT NOT NULL,
            first_seen TIMESTAMP NOT NULL,
            last_seen TIMESTAMP NOT NULL,
            FOREIGN KEY (player_id) REFERENCES player_identity (player_id)
        )
        ''')

        cursor.execute('''
        CREATE TABLE IF NOT EXISTS player_rankings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            player_id INTEGER,
            uid TEXT,
            mode INTEGER NOT NULL,
            rank INTEGER NOT NULL,
            name TEXT NOT NULL,
            lv INTEGER,
            exp INTEGER,
            acc REAL,
            combo INTEGER,
            pc INTEGER,
            crawl_time TIMESTAMP NOT NULL,
            FOREIGN KEY (player_id) REFERENCES player_identity (player_id)
        )
        ''')

        cursor.execute('''
        CREATE TABLE IF NOT EXISTS import_metadata (
            mode INTEGER PRIMARY KEY,
            last_import_time TIMESTAMP
        )
        ''')

        cursor.execute('''
        CREATE TABLE IF NOT EXISTS player_config (
            config_id INTEGER PRIMARY KEY AUTOINCREMENT,
            player_identifier TEXT NOT NULL UNIQUE,
            player_name TEXT,
            is_active BOOLEAN DEFAULT 1,
            priority INTEGER DEFAULT 5,
            notes TEXT,
            created_time TIMESTAMP NOT NULL,
            last_updated TIMESTAMP NOT NULL
        )
        ''')

        cursor.execute('''
        CREATE TABLE IF NOT EXISTS player_crawl_status (
            player_identifier TEXT PRIMARY KEY,
            last_crawled TIMESTAMP,
            crawl_count INTEGER DEFAULT 0,
            success_count INTEGER DEFAULT 0,
            last_error TEXT
        )
        ''')

        cursor.execute('CREATE INDEX IF NOT EXISTS idx_player_identity_uid ON player_identity(uid)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_player_aliases_uid ON player_aliases(uid)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_player_rankings_uid ON player_rankings(uid)')
        ensure_mm_schema(cursor)

        # 鍒濆鍖?import_metadata
        for mode in MODES:
            cursor.execute(
                "INSERT OR IGNORE INTO import_metadata (mode, last_import_time) VALUES (?, NULL)",
                (mode,)
            )

        db_manager.get_connection().commit()
        logger.info("鏁版嵁搴撳垵濮嬪寲瀹屾垚")
        migrate_database()  # 灏濊瘯娣诲姞 uid 瀛楁锛堣嫢宸插瓨鍦ㄥ垯璺宠繃锛?
    except Exception as e:
        logger.error("鏁版嵁搴撳垵濮嬪寲澶辫触: %s", e)
        raise


def resolve_player_identity(name, crawl_time, uid=None):
    """
    瑙ｆ瀽鐜╁韬唤锛屼紭鍏堜娇鐢?uid锛屽鐞嗘敼鍚嶆儏鍐点€?
    杩斿洖 player_id銆?
    """
    db_manager = DatabaseManager()
    cursor = db_manager.get_connection().cursor()
    try:
        player_id = None
        # 浼樺厛浣跨敤 uid 鏌ユ壘
        if uid:
            try:
                cursor.execute(
                    "SELECT player_id FROM player_identity WHERE uid = ?",
                    (uid,)
                )
                result = cursor.fetchone()
                if result:
                    player_id = result[0]
                    # 鏇存柊鏈€鍚庣湅瑙佹椂闂村拰褰撳墠鍚嶅瓧
                    cursor.execute(
                        "UPDATE player_identity SET last_seen = ?, current_name = ? WHERE player_id = ?",
                        (crawl_time, name, player_id)
                    )
                    # 璁板綍鍒悕锛堝鏋滄湭璁板綍锛?
                    cursor.execute(
                        "SELECT alias_id FROM player_aliases WHERE player_id = ? AND alias = ?",
                        (player_id, name)
                    )
                    if not cursor.fetchone():
                        cursor.execute(
                            "INSERT INTO player_aliases (player_id, uid, alias, first_seen, last_seen) VALUES (?, ?, ?, ?, ?)",
                            (player_id, uid, name, crawl_time, crawl_time)
                        )
                    else:
                        cursor.execute(
                            "UPDATE player_aliases SET last_seen = ? WHERE player_id = ? AND alias = ?",
                            (crawl_time, player_id, name)
                        )
            except sqlite3.OperationalError as e:
                if "no such column: uid" in str(e):
                    logger.warning("uid 鍒椾笉瀛樺湪锛屽洖閫€鍒板悕绉版煡鎵?")
                else:
                    raise

        # 濡傛灉鏈€氳繃 uid 鎵惧埌锛屽皾璇曢€氳繃鍒悕鏌ユ壘
        if not player_id:
            cursor.execute(
                "SELECT player_id FROM player_aliases WHERE alias = ?",
                (name,)
            )
            result = cursor.fetchone()
            if result:
                player_id = result[0]
                # 濡傛灉鏈?uid锛屽垯鏇存柊 identity 鍜?aliases 琛ㄤ腑鐨?uid
                if uid:
                    try:
                        cursor.execute(
                            "UPDATE player_identity SET uid = ? WHERE player_id = ?",
                            (uid, player_id)
                        )
                        cursor.execute(
                            "UPDATE player_aliases SET uid = ? WHERE player_id = ?",
                            (uid, player_id)
                        )
                    except sqlite3.OperationalError as e:
                        if "no such column: uid" in str(e):
                            logger.warning("uid 鍒椾笉瀛樺湪锛岃烦杩?uid 鏇存柊")
                        else:
                            raise
                cursor.execute(
                    "UPDATE player_aliases SET last_seen = ? WHERE alias = ?",
                    (crawl_time, name)
                )
                cursor.execute(
                    "UPDATE player_identity SET last_seen = ?, current_name = ? WHERE player_id = ?",
                    (crawl_time, name, player_id)
                )
            else:
                # 鍏ㄦ柊鐜╁
                cursor.execute(
                    "INSERT INTO player_identity (uid, current_name, first_seen, last_seen) VALUES (?, ?, ?, ?)",
                    (uid, name, crawl_time, crawl_time)
                )
                player_id = cursor.lastrowid
                cursor.execute(
                    "INSERT INTO player_aliases (player_id, uid, alias, first_seen, last_seen) VALUES (?, ?, ?, ?, ?)",
                    (player_id, uid, name, crawl_time, crawl_time)
                )
        db_manager.get_connection().commit()
        return player_id
    except Exception as e:
        logger.error("瑙ｆ瀽鐜╁韬唤澶辫触: %s", e)
        db_manager.get_connection().rollback()
        return None


def link_player_aliases(original_name, new_name, change_time):
    """鎵嬪姩鍏宠仈鐜╁鐨勪袱涓悕瀛楋紙澶勭悊鏀瑰悕锛?"""
    db_manager = DatabaseManager()
    cursor = db_manager.get_connection().cursor()
    try:
        cursor.execute(
            "SELECT player_id FROM player_aliases WHERE alias = ?",
            (original_name,)
        )
        result = cursor.fetchone()
        if not result:
            logger.error("鎵句笉鍒板師濮嬪悕瀛? %s", original_name)
            return False
        player_id = result[0]

        cursor.execute(
            "SELECT player_id FROM player_aliases WHERE alias = ?",
            (new_name,)
        )
        result = cursor.fetchone()
        if result:
            # 鏂板悕瀛楀凡鍏宠仈鍒板彟涓€涓?player_id锛岄渶瑕佸悎骞?
            old_player_id = result[0]
            cursor.execute(
                "UPDATE player_rankings SET player_id = ? WHERE player_id = ?",
                (player_id, old_player_id)
            )
            cursor.execute(
                "UPDATE player_aliases SET player_id = ? WHERE player_id = ?",
                (player_id, old_player_id)
            )
            cursor.execute(
                "DELETE FROM player_identity WHERE player_id = ?",
                (old_player_id,)
            )
        else:
            # 鏂板悕瀛楁湭鍑虹幇杩囷紝鐩存帴娣诲姞鍒悕
            cursor.execute(
                "INSERT INTO player_aliases (player_id, alias, first_seen, last_seen) VALUES (?, ?, ?, ?)",
                (player_id, new_name, change_time, change_time)
            )
        cursor.execute(
            "UPDATE player_identity SET current_name = ? WHERE player_id = ?",
            (new_name, player_id)
        )
        db_manager.get_connection().commit()
        logger.info("鎴愬姛鍏宠仈鐜╁鏀瑰悕: %s -> %s", original_name, new_name)
        return True
    except Exception as e:
        logger.error("澶勭悊鐜╁鏀瑰悕澶辫触: %s", e)
        db_manager.get_connection().rollback()
        return False


def parse_player_list(html):
    """瑙ｆ瀽鎺掕姒滈〉闈紝杩斿洖鐜╁鏁版嵁鍒楄〃锛堝寘鍚帺瀹禝D锛?"""
    soup = BeautifulSoup(html, "html.parser")
    players = []

    # 澶勭悊鍓?鍚嶏紙item-top锛?
    top_items = soup.select("div.item-top")
    for item in top_items:
        label_tag = item.select_one("i.label")
        rank = None
        if label_tag and label_tag.has_attr("class"):
            for c in label_tag["class"]:
                if c.startswith("top-"):
                    rank = c.replace("top-", "")
                    break

        name_tag = item.select_one("span.name a")
        lv_tag = item.select_one("span.lv")
        acc_tag = item.select_one("span.acc")
        combo_tag = item.select_one("span.combo")
        pc_tag = item.select_one("span.pc, span[class*=pc]")

        player_id = None
        if name_tag and name_tag.has_attr('href'):
            href = name_tag['href']
            match = re.search(r'/accounts/user/(\d+)', href)
            if match:
                player_id = match.group(1)

        level = None
        exp = None
        if lv_tag:
            lv_text = lv_tag.text.strip()
            if '-' in lv_text:
                parts = lv_text.split('-')
                level = parts[0].replace("Lv.", "").strip()
                exp = parts[1].strip()
            else:
                level = lv_text.replace("Lv.", "").strip()

        acc_text = None
        if acc_tag:
            acc_text = acc_tag.text.replace("Acc:", "").replace("%", "").strip()

        combo_text = None
        if combo_tag:
            combo_text = combo_tag.text.replace("Combo:", "").strip()

        playcount = None
        if pc_tag:
            # Keep this parser prefix-agnostic to avoid locale/encoding regressions.
            pc_text = pc_tag.text.strip()
            digits = ''.join(filter(str.isdigit, pc_text))
            if digits:
                playcount = int(digits)

        players.append({
            "rank": rank,
            "name": name_tag.text.strip() if name_tag else None,
            "player_id": player_id,
            "lv": level,
            "exp": exp,
            "acc": acc_text,
            "combo": combo_text,
            "pc": playcount
        })

    # 澶勭悊4鍚嶅強浠ュ悗锛坉iv.item锛?
    list_items = soup.select("div.item")
    for item in list_items:
        rank_tag = item.select_one("span.rank")
        rank = rank_tag.text.strip() if rank_tag else None

        name_tag = item.select_one("span.name a")
        lv_tag = item.select_one("span.lv")
        exp_tag = item.select_one("span.exp")
        acc_tag = item.select_one("span.acc")
        pc_tag = item.select_one("span.pc, span[class*=pc]")
        combo_tag = item.select_one("span.combo")

        player_id = None
        if name_tag and name_tag.has_attr('href'):
            href = name_tag['href']
            match = re.search(r'/accounts/user/(\d+)', href)
            if match:
                player_id = match.group(1)

        acc_text = None
        if acc_tag:
            acc_text = acc_tag.text.replace("%", "").strip()

        playcount = None
        if pc_tag:
            pc_text = pc_tag.text.strip()
            digits = ''.join(filter(str.isdigit, pc_text))
            if digits:
                playcount = int(digits)

        players.append({
            "rank": rank,
            "name": name_tag.text.strip() if name_tag else None,
            "player_id": player_id,
            "lv": lv_tag.text.strip() if lv_tag else None,
            "exp": exp_tag.text.strip() if exp_tag else None,
            "acc": acc_text,
            "combo": combo_tag.text.strip() if combo_tag else None,
            "pc": playcount
        })

    # 绫诲瀷杞崲涓庢竻娲?
    processed_players = []
    for p in players:
        try:
            rank = int(p["rank"]) if p["rank"] else None
        except:
            rank = None
        try:
            lv = int(p["lv"]) if p["lv"] else 0
        except:
            lv = 0
        try:
            exp = int(p["exp"]) if p["exp"] else 0
        except:
            exp = 0
        try:
            acc = float(p["acc"]) if p["acc"] else 0.0
        except:
            acc = 0.0
        try:
            combo = int(p["combo"]) if p["combo"] else 0
        except:
            combo = 0
        pc = p["pc"] if p["pc"] is not None else 0

        if rank is not None:
            processed_players.append({
                "rank": rank,
                "name": p["name"],
                "player_id": p["player_id"],
                "lv": lv,
                "exp": exp,
                "acc": acc,
                "combo": combo,
                "pc": pc
            })
    return processed_players


def parse_player_profile(html, player_id):
    """瑙ｆ瀽鐜╁涓汉涓婚〉锛岃繑鍥炶鐜╁鎵€鏈夋ā寮忕殑鎺掑悕鏁版嵁"""
    soup = BeautifulSoup(html, "html.parser")
    player_data = []

    name_tag = soup.select_one("div.user_head .name span")
    player_name = name_tag.text.strip() if name_tag else f"鐜╁_{player_id}"

    rank_items = soup.select("div.rank .item")
    for item in rank_items:
        try:
            img_tag = item.select_one("img")
            if not img_tag or not img_tag.has_attr('src'):
                continue
            src = img_tag['src']
            mode = None
            if 'mode-0.png' in src:
                mode = 0
            elif 'mode-1.png' in src:
                mode = 1
            elif 'mode-2.png' in src:
                mode = 2
            elif 'mode-3.png' in src:
                mode = 3
            elif 'mode-4.png' in src:
                mode = 4
            elif 'mode-5.png' in src:
                mode = 5
            elif 'mode-6.png' in src:
                mode = 6
            elif 'mode-7.png' in src:
                mode = 7
            elif 'mode-8.png' in src:
                mode = 8
            elif 'mode-9.png' in src:
                mode = 9
            else:
                continue

            rank_tag = item.select_one("p.rank")
            if not rank_tag:
                continue
            rank_text = rank_tag.text.strip()
            if rank_text.startswith('#'):
                try:
                    rank = int(rank_text[1:].replace(',', ''))
                except:
                    continue
            else:
                continue

            data_spans = item.select("p span")
            exp = 0
            playcount = 0
            acc = 0.0
            combo = 0
            for span in data_spans:
                text = span.text.strip()
                if text.startswith('Exp.'):
                    try:
                        exp = int(text.replace('Exp.', '').strip().replace(',', ''))
                    except:
                        pass
                elif text.startswith('Playcount:'):
                    try:
                        playcount = int(text.replace('Playcount:', '').strip())
                    except:
                        pass
                elif text.startswith('Acc.'):
                    try:
                        acc = float(text.replace('Acc.', '').replace('%', '').strip())
                    except:
                        pass
                elif text.startswith('Combo:'):
                    try:
                        combo = int(text.replace('Combo:', '').strip())
                    except:
                        pass

            player_data.append({
                "rank": rank,
                "name": player_name,
                "lv": 0,
                "exp": exp,
                "acc": acc,
                "combo": combo,
                "pc": playcount,
                "mode": mode
            })
        except Exception as e:
            logger.warning("瑙ｆ瀽鐜╁ %s 妯″紡 %s 鏁版嵁鏃跺嚭閿? %s", player_id, mode, e)
            continue
    return player_data


def crawl_player_profile(session, player_identifier):
    """鐖彇鍗曚釜鐜╁鐨勪釜浜轰富椤垫暟鎹?"""
    try:
        if not player_identifier.isdigit():
            logger.warning("鐜╁鏍囪瘑绗﹀繀椤绘槸鏁板瓧ID: %s", player_identifier)
            return None
        url = PLAYER_PROFILE_URL.format(player_id=player_identifier)
        resp = session.get(url, timeout=30)
        resp.raise_for_status()
        player_data = parse_player_profile(resp.text, player_identifier)
        return player_data
    except requests.exceptions.RequestException as e:
        logger.error("鐖彇鐜╁ %s 涓汉涓婚〉澶辫触: %s", player_identifier, e)
        return None
    except Exception as e:
        logger.error("澶勭悊鐜╁ %s 鏁版嵁鏃跺嚭閿? %s", player_identifier, e)
        return None


def get_excel_filename(mode):
    """鏍规嵁妯″紡杩斿洖 Excel 鏂囦欢鍚?"""
    if mode == 0:
        return "key.xlsx"
    elif mode == 3:
        return "catch.xlsx"
    else:
        return f"mode{mode}.xlsx"


def crawl_mode_player(session, mode):
    """鐖彇鍗曚釜妯″紡鐨勬帓琛屾鏁版嵁锛岃繑鍥?DataFrame"""
    url = BASE_URL.format(mode=mode)
    try:
        resp = session.get(url, timeout=30)
        resp.raise_for_status()
    except requests.exceptions.RequestException as e:
        logger.error("妯″紡 %d 璇锋眰澶辫触: %s", mode, e)
        return pd.DataFrame()

    players = parse_player_list(resp.text)
    df = pd.DataFrame(players)
    if not df.empty:
        df = df[df['rank'].notnull()]
        df['rank'] = df['rank'].astype(int)
        df = df.sort_values('rank').reset_index(drop=True)
    return df


def save_data_to_excel(mode, df, timestamp):
    """淇濆瓨 DataFrame 鍒?Excel 鏂囦欢锛堜粎鍦ㄥ惎鐢?Excel 淇濆瓨鏃朵娇鐢級"""
    if df.empty:
        logger.warning("妯″紡 %d 鏃犳湁鏁堟暟鎹紝璺宠繃淇濆瓨", mode)
        return

    filename = get_excel_filename(mode)
    sheet_name = f"mode_{mode}"

    try:
        if not os.path.exists(filename):
            with pd.ExcelWriter(filename, engine='openpyxl') as writer:
                pd.DataFrame().to_excel(writer, sheet_name=sheet_name)

        wb = load_workbook(filename)
        if sheet_name not in wb.sheetnames:
            with pd.ExcelWriter(filename, engine='openpyxl', mode='a') as writer:
                pd.DataFrame().to_excel(writer, sheet_name=sheet_name)

        sub_sheets = [s for s in wb.sheetnames if s.startswith(f"{sheet_name}_")] if wb.sheetnames else []
        latest_sheet = None
        latest_time = None
        for s in sub_sheets:
            try:
                dt_str = s.replace(f"{sheet_name}_", "")
                dt = datetime.strptime(dt_str, "%Y-%m-%d_%H-%M")
                if latest_time is None or dt > latest_time:
                    latest_time = dt
                    latest_sheet = s
            except:
                continue

        if latest_sheet:
            df_prev = pd.read_excel(filename, sheet_name=latest_sheet)
            if not df_prev.empty and df_prev.equals(df):
                logger.info("妯″紡 %d 鏁版嵁鏈彉鍖栵紝璺宠繃淇濆瓨", mode)
                return

        sub_sheet_name = f"{sheet_name}_{timestamp.strftime('%Y-%m-%d_%H-%M')}"
        with pd.ExcelWriter(filename, engine='openpyxl', mode='a') as writer:
            df.to_excel(writer, sheet_name=sub_sheet_name, index=False)
        logger.info("妯″紡 %d 鏁版嵁淇濆瓨鍒?%s -> %s", mode, filename, sub_sheet_name)
    except Exception as e:
        logger.exception("淇濆瓨妯″紡 %d 鏁版嵁鍒癊xcel澶辫触", mode)


def save_player_ranking_record(player_id, uid, mode, rank, name, lv, exp, acc, combo, pc, crawl_time, source):
    """
    鍖洪棿妯″瀷鎺掕姒滀繚瀛橈紙缁熶竴澶勭悊鎵€鏈夋潵婧愶級銆?
    杩斿洖鍊硷細
        'new'          : 棣栨鎻掑叆
        'diff_insert'  : 鐘舵€佸彉鍖栵紝鎻掑叆鏂?start
        'update'       : 寤堕暱 end
        'same_insert'  : 鎻掑叆 end
        'update_fill'  : 濉厖 lv
    """
    db_manager = DatabaseManager()
    conn = db_manager.get_connection()
    cursor = conn.cursor()

    current_core = (rank, name, exp, acc, combo, pc)

    # 鍙彇鏈€鏂颁袱鏉?
    cursor.execute('''
        SELECT id, rank, name, lv, exp, acc, combo, pc, crawl_time
        FROM player_rankings
        WHERE player_id = ? AND mode = ?
        ORDER BY crawl_time DESC
        LIMIT 2
    ''', (player_id, mode))

    rows = cursor.fetchall()

    # 娌℃湁璁板綍 鈫?start
    if not rows:
        cursor.execute('''
            INSERT INTO player_rankings
            (player_id, uid, mode, rank, name, lv, exp, acc, combo, pc, crawl_time)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (player_id, uid, mode, rank, name, lv, exp, acc, combo, pc, crawl_time))
        conn.commit()
        return 'new'

    # 鏈€鏂拌褰?
    last = rows[0]
    last_id, last_rank, last_name, last_lv, last_exp, last_acc, last_combo, last_pc, last_time = last
    last_core = (last_rank, last_name, last_exp, last_acc, last_combo, last_pc)

    # 鍒ゆ柇鏄惁宸叉湁 end锛堜袱鏉＄浉鍚岋級
    has_two_same = False
    if len(rows) == 2:
        second = rows[1]
        second_core = (second[1], second[2], second[4], second[5], second[6], second[7])
        if second_core == last_core:
            has_two_same = True

    # 鐘舵€佺浉鍚?
    if last_core == current_core:

        # lv 琛ュ叏
        if last_lv == 0 and lv != 0:
            cursor.execute('UPDATE player_rankings SET lv = ?, crawl_time = ? WHERE id = ?', (lv, crawl_time, last_id))
            conn.commit()
            return 'update_fill'

        if not has_two_same:
            # 鎻掑叆 end
            cursor.execute('''
                INSERT INTO player_rankings
                (player_id, uid, mode, rank, name, lv, exp, acc, combo, pc, crawl_time)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (player_id, uid, mode, rank, name, lv, exp, acc, combo, pc, crawl_time))
            conn.commit()
            return 'same_insert'
        else:
            # 寤堕暱 end
            cursor.execute('UPDATE player_rankings SET crawl_time = ? WHERE id = ?', (crawl_time, last_id))
            conn.commit()
            return 'update'

    # 鐘舵€佸彉鍖?鈫?鏂?start
    cursor.execute('''
        INSERT INTO player_rankings
        (player_id, uid, mode, rank, name, lv, exp, acc, combo, pc, crawl_time)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (player_id, uid, mode, rank, name, lv, exp, acc, combo, pc, crawl_time))

    conn.commit()
    return 'diff_insert'


def save_player_ranking_mm_record(
    player_id: int,
    uid: str,
    mode: int,
    rank: int,
    name: str,
    mm_value: int,
    lv: int,
    acc: float,
    combo: int,
    pc: int,
    crawl_time: datetime,
    source: str,
) -> str:
    """
    MM 鎺掕鍖洪棿妯″瀷淇濆瓨銆?
    """
    db_manager = DatabaseManager()
    conn = db_manager.get_connection()
    cursor = conn.cursor()

    current_core = (rank, name, mm_value, lv, acc, combo, pc)
    cursor.execute(
        """
        SELECT id, rank, name, mm_value, lv, acc, combo, pc, crawl_time
        FROM player_rankings_mm
        WHERE player_id = ? AND mode = ?
        ORDER BY crawl_time DESC
        LIMIT 2
        """,
        (player_id, mode),
    )
    rows = cursor.fetchall()

    if not rows:
        cursor.execute(
            """
            INSERT INTO player_rankings_mm
            (player_id, uid, mode, rank, name, mm_value, lv, acc, combo, pc, crawl_time, source)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (player_id, uid, mode, rank, name, mm_value, lv, acc, combo, pc, crawl_time, source),
        )
        conn.commit()
        return "new"

    last = rows[0]
    last_id = last[0]
    last_core = (last[1], last[2], last[3], last[4], last[5], last[6], last[7])
    has_two_same = False
    if len(rows) == 2:
        second = rows[1]
        second_core = (second[1], second[2], second[3], second[4], second[5], second[6], second[7])
        has_two_same = second_core == last_core

    if last_core == current_core:
        if not has_two_same:
            cursor.execute(
                """
                INSERT INTO player_rankings_mm
                (player_id, uid, mode, rank, name, mm_value, lv, acc, combo, pc, crawl_time, source)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (player_id, uid, mode, rank, name, mm_value, lv, acc, combo, pc, crawl_time, source),
            )
            conn.commit()
            return "same_insert"
        cursor.execute("UPDATE player_rankings_mm SET crawl_time = ? WHERE id = ?", (crawl_time, last_id))
        conn.commit()
        return "update"

    cursor.execute(
        """
        INSERT INTO player_rankings_mm
        (player_id, uid, mode, rank, name, mm_value, lv, acc, combo, pc, crawl_time, source)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (player_id, uid, mode, rank, name, mm_value, lv, acc, combo, pc, crawl_time, source),
    )
    conn.commit()
    return "diff_insert"


def save_player_mmr_sample(
    player_id: Optional[int],
    uid: str,
    mode: int,
    mmr: int,
    mm_rank: Optional[int],
    name: Optional[str],
    crawl_time: datetime,
    source: str,
) -> str:
    db_manager = DatabaseManager()
    conn = db_manager.get_connection()
    cursor = conn.cursor()
    day = crawl_time.date().isoformat()

    # Align with ranking dedup model: keep two boundary rows per stable segment.
    cursor.execute(
        """
        SELECT sample_id, mmr, mm_rank, name, source
        FROM player_mmr_samples
        WHERE uid = ? AND mode = ?
        ORDER BY crawl_time DESC
        LIMIT 2
        """,
        (uid, mode),
    )
    rows = cursor.fetchall()
    if not rows:
        cursor.execute(
            """
            INSERT INTO player_mmr_samples
            (player_id, uid, mode, mmr, mm_rank, name, crawl_time, source)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (player_id, uid, mode, mmr, mm_rank, name, crawl_time, source),
        )
        sample_op = "new"
    else:
        last_sample_id, last_mmr, last_mm_rank, last_name, last_source = rows[0]
        has_two_same = False
        if len(rows) == 2:
            second = rows[1]
            has_two_same = (
                int(second[1] or 0) == int(last_mmr or 0)
                and (second[2] if second[2] is not None else None) == (last_mm_rank if last_mm_rank is not None else None)
                and (second[3] or None) == (last_name or None)
                and (second[4] or "") == (last_source or "")
            )

        same_as_last = (
            int(last_mmr or 0) == int(mmr)
            and (last_mm_rank if last_mm_rank is not None else None) == (mm_rank if mm_rank is not None else None)
            and (last_name or None) == (name or None)
            and (last_source or "") == (source or "")
        )
        if same_as_last:
            if not has_two_same:
                cursor.execute(
                    """
                    INSERT INTO player_mmr_samples
                    (player_id, uid, mode, mmr, mm_rank, name, crawl_time, source)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (player_id, uid, mode, mmr, mm_rank, name, crawl_time, source),
                )
                sample_op = "same_insert"
            else:
                cursor.execute(
                    """
                    UPDATE player_mmr_samples
                    SET crawl_time = ?
                    WHERE sample_id = ?
                    """,
                    (crawl_time, last_sample_id),
                )
                sample_op = "update"
        else:
            cursor.execute(
                """
                INSERT INTO player_mmr_samples
                (player_id, uid, mode, mmr, mm_rank, name, crawl_time, source)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (player_id, uid, mode, mmr, mm_rank, name, crawl_time, source),
            )
            sample_op = "diff_insert"

    cursor.execute(
        """
        INSERT INTO player_mmr_daily
        (uid, mode, day, mmr, mm_rank, name, sample_time, source)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(uid, mode, day) DO UPDATE SET
            mmr = excluded.mmr,
            mm_rank = excluded.mm_rank,
            name = excluded.name,
            sample_time = excluded.sample_time,
            source = excluded.source
        WHERE excluded.sample_time >= player_mmr_daily.sample_time
        """,
        (uid, mode, day, mmr, mm_rank, name, crawl_time, source),
    )
    conn.commit()
    return sample_op

def update_mm_crawl_status(
    task: str,
    success: bool,
    error: Optional[str] = None,
    state: Optional[Dict[str, Any]] = None,
):
    db_manager = DatabaseManager()
    conn = db_manager.get_connection()
    cursor = conn.cursor()
    now = datetime.now()
    state_json = json.dumps(state or {}, ensure_ascii=False)
    cursor.execute(
        """
        INSERT OR REPLACE INTO mm_crawl_status
        (task, last_crawled, last_success, crawl_count, success_count, last_error, state_json)
        VALUES (
            ?,
            ?,
            CASE WHEN ? THEN ? ELSE (SELECT last_success FROM mm_crawl_status WHERE task = ?) END,
            COALESCE((SELECT crawl_count FROM mm_crawl_status WHERE task = ?), 0) + 1,
            COALESCE((SELECT success_count FROM mm_crawl_status WHERE task = ?), 0) + CASE WHEN ? THEN 1 ELSE 0 END,
            ?,
            ?
        )
        """,
        (
            task,
            now,
            1 if success else 0,
            now,
            task,
            task,
            task,
            1 if success else 0,
            None if success else error,
            state_json,
        ),
    )
    conn.commit()


def fetch_global_mode(
    session: requests.Session,
    mode: int,
    limit: int = DEFAULT_MM_LIMIT,
    mm: int = 0,
) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    from_offset = 0
    visited_offsets: Set[int] = set()
    while len(rows) < max(limit, 0):
        if from_offset in visited_offsets:
            break
        visited_offsets.add(from_offset)

        payload = _new_api_get(
            session,
            "/ranking/global",
            {"mode": mode, "from": from_offset, "mm": 1 if mm else 0},
        )
        if payload.get("code") != 0:
            raise RuntimeError(f"ranking/global failed: code={payload.get('code')}")
        data = payload.get("data") or []
        if not data:
            break
        for item in data:
            rows.append(item)
            if len(rows) >= limit:
                break

        if not payload.get("hasMore"):
            break
        next_offset = payload.get("next")
        if isinstance(next_offset, int):
            from_offset = next_offset
        else:
            from_offset += len(data)

    return rows


def fetch_mm_global_mode(
    session: requests.Session,
    mode: int,
    limit: int = DEFAULT_MM_LIMIT,
) -> List[Dict[str, Any]]:
    return fetch_global_mode(session=session, mode=mode, limit=limit, mm=1)


def crawl_mode_player_newapi(
    session: requests.Session,
    mode: int,
    limit: int = DEFAULT_MM_LIMIT,
) -> Tuple[pd.DataFrame, List[Dict[str, Any]]]:
    try:
        exp_rows = fetch_global_mode(session=session, mode=mode, limit=limit, mm=0)
    except Exception as e:
        logger.error("newapi exp ranking crawl failed for mode %d: %s", mode, e)
        return pd.DataFrame(), []

    players: List[Dict[str, Any]] = []
    for item in exp_rows:
        uid_int = _safe_int(item.get("uid"), 0)
        if uid_int <= 0:
            continue
        players.append(
            {
                "rank": _safe_int(item.get("rank"), 0),
                "name": item.get("username") or f"uid_{uid_int}",
                "player_id": str(uid_int),
                "lv": _safe_int(item.get("level"), 0),
                "exp": _safe_int(item.get("value"), 0),
                "acc": _safe_float(item.get("acc"), 0.0),
                "combo": _safe_int(item.get("combo"), 0),
                "pc": _safe_int(item.get("playcount"), 0),
            }
        )

    df = pd.DataFrame(players)
    if not df.empty:
        df = df[df["rank"] > 0]
        if df["rank"].duplicated().any():
            dup_count = int(df["rank"].duplicated().sum())
            logger.warning(
                "newapi mode %d contains duplicated ranks (%d), keep first row per rank.",
                mode,
                dup_count,
            )
            df = df.drop_duplicates(subset=["rank"], keep="first")
        df = df.sort_values("rank").reset_index(drop=True)

    mm_rows: List[Dict[str, Any]] = []
    try:
        mm_rows = fetch_mm_global_mode(session=session, mode=mode, limit=limit)
    except Exception as e:
        logger.warning("newapi mm ranking crawl failed for mode %d: %s", mode, e)
        mm_rows = []

    return df, mm_rows


def save_mm_ranking_rows(
    mode: int,
    rows: List[Dict[str, Any]],
    crawl_time: datetime,
    source: str = "mm_global",
) -> Dict[str, int]:
    row_stats = {"new": 0, "same_insert": 0, "update": 0, "diff_insert": 0}
    seen_ranks: Set[int] = set()
    seen_uids: Set[str] = set()
    normalized_rows: List[Dict[str, Any]] = []
    dropped_dup_rank = 0
    dropped_dup_uid = 0
    dropped_invalid = 0

    for item in rows:
        uid = str(_safe_int(item.get("uid"), 0))
        rank = _safe_int(item.get("rank"), 0)
        if uid == "0" or rank <= 0:
            dropped_invalid += 1
            continue
        if rank in seen_ranks:
            dropped_dup_rank += 1
            continue
        if uid in seen_uids:
            dropped_dup_uid += 1
            continue
        seen_ranks.add(rank)
        seen_uids.add(uid)
        normalized_rows.append(item)

    saved_rows = 0
    for item in normalized_rows:
        uid = str(_safe_int(item.get("uid"), 0))
        if uid == "0":
            continue
        name = item.get("username") or f"uid_{uid}"
        player_id = resolve_player_identity(name, crawl_time, uid=uid)
        if player_id is None:
            continue
        op = save_player_ranking_mm_record(
            player_id=player_id,
            uid=uid,
            mode=mode,
            rank=_safe_int(item.get("rank"), 0),
            name=name,
            mm_value=_safe_int(item.get("value"), 0),
            lv=_safe_int(item.get("level"), 0),
            acc=_safe_float(item.get("acc"), 0.0),
            combo=_safe_int(item.get("combo"), 0),
            pc=_safe_int(item.get("playcount"), 0),
            crawl_time=crawl_time,
            source=source,
        )
        if op in row_stats:
            row_stats[op] += 1
        saved_rows += 1
    return {
        "rows": len(rows),
        "saved_rows": saved_rows,
        "dropped_dup_rank": dropped_dup_rank,
        "dropped_dup_uid": dropped_dup_uid,
        "dropped_invalid": dropped_invalid,
        **row_stats,
    }


def fetch_player_mmr_from_api(session: requests.Session, uid: str) -> List[Dict[str, Any]]:
    payload = _new_api_get(session, "/ranking/player/all", {"touid": _safe_int(uid, -1)})
    if payload.get("code") != 0:
        raise RuntimeError(f"ranking/player/all failed: code={payload.get('code')}")
    data = payload.get("data") or []
    rows: List[Dict[str, Any]] = []
    for item in data:
        mode = _safe_int(item.get("mode"), -1)
        if mode < 0:
            continue
        mmr = _safe_int(item.get("grade"), -1)
        if mmr < 0:
            continue
        rows.append(
            {
                "uid": str(uid),
                "mode": mode,
                "mmr": mmr,
                "mm_rank": _safe_int(item.get("gradeRank"), 0) or None,
                "rank": _safe_int(item.get("rank"), 0) or None,
                "name": None,
            }
        )
    return rows


def fetch_player_mmr_from_page(session: requests.Session, uid: str) -> List[Dict[str, Any]]:
    url = PLAYER_PROFILE_URL.format(player_id=uid)
    response = session.get(url, timeout=30)
    if response.status_code != 200:
        return []
    soup = BeautifulSoup(response.text, "html.parser")
    rows: List[Dict[str, Any]] = []
    for item in soup.select("div.rank .item"):
        img = item.select_one("img")
        if not img or not img.has_attr("src"):
            continue
        mode_match = re.search(r"mode-(\d+)\.png", img["src"])
        if not mode_match:
            continue
        mode = _safe_int(mode_match.group(1), -1)
        if mode < 0:
            continue
        text = item.get_text(" ", strip=True)
        mmr_match = re.search(r"(?:MMR|MM|Grade)[\s:锛?]*([0-9,]+)", text, re.IGNORECASE)
        rank_match = re.search(r"(?:MMRank|GradeRank)[\s:锛?]*#?([0-9,]+)", text, re.IGNORECASE)
        if not mmr_match:
            continue
        rows.append(
            {
                "uid": str(uid),
                "mode": mode,
                "mmr": _safe_int(mmr_match.group(1).replace(",", ""), -1),
                "mm_rank": _safe_int(rank_match.group(1).replace(",", ""), 0) if rank_match else None,
                "name": None,
            }
        )
    return [row for row in rows if row["mmr"] >= 0]


def get_recent_mm_tracked_uids(limit_per_mode: int = DEFAULT_MM_LIMIT) -> Set[str]:
    db_manager = DatabaseManager()
    conn = db_manager.get_connection()
    cursor = conn.cursor()
    tracked: Set[str] = set()
    for mode in MODES:
        cursor.execute(
            """
            SELECT uid
            FROM player_rankings_mm
            WHERE mode = ?
              AND crawl_time = (SELECT MAX(crawl_time) FROM player_rankings_mm WHERE mode = ?)
              AND rank <= ?
            """,
            (mode, mode, limit_per_mode),
        )
        tracked.update(str(row[0]) for row in cursor.fetchall() if row and row[0])
    return tracked


def get_recent_exp_tracked_uids(limit_per_mode: int = DEFAULT_MM_LIMIT) -> Set[str]:
    """
    浠庢渶鏂?EXP 姒滄寜妯″紡鎻愬彇 topN uid锛岀敤浜庤ˉ鍏呴潪 MM 姒滅帺瀹剁殑 MMR 鎶撳彇鑼冨洿銆?    """
    db_manager = DatabaseManager()
    conn = db_manager.get_connection()
    cursor = conn.cursor()
    tracked: Set[str] = set()
    for mode in MODES:
        cursor.execute(
            """
            SELECT uid
            FROM player_rankings
            WHERE mode = ?
              AND crawl_time = (SELECT MAX(crawl_time) FROM player_rankings WHERE mode = ?)
              AND rank <= ?
              AND uid IS NOT NULL
              AND uid != ''
            """,
            (mode, mode, limit_per_mode),
        )
        tracked.update(str(row[0]) for row in cursor.fetchall() if row and row[0])
    return tracked


def get_player_id_by_uid(uid: str) -> Optional[int]:
    db_manager = DatabaseManager()
    cursor = db_manager.get_connection().cursor()
    cursor.execute("SELECT player_id FROM player_identity WHERE uid = ?", (uid,))
    row = cursor.fetchone()
    return row[0] if row else None


def run_mm_sync_cycle(
    mm_limit: int = DEFAULT_MM_LIMIT,
    include_mm_ranking: bool = True,
    include_mmr: bool = True,
    include_exp_ranking_uids: bool = True,
    exp_limit: int = DEFAULT_MM_LIMIT,
    seed_uids: Optional[Set[str]] = None,
    mmr_min_interval_minutes: int = 20,
) -> Dict[str, Any]:
    if not _acquire_mm_run_lock():
        logger.warning("MM sync is already running, skip this cycle.")
        return {"skipped": True, "reason": "locked"}

    session = requests.Session()
    session.cookies.update(COOKIES)
    session.headers.update(HEADERS)
    session.mount("https://", requests.adapters.HTTPAdapter(max_retries=3))

    stats: Dict[str, Any] = {
        "mm_rows": 0,
        "mm_modes_ok": 0,
        "mm_modes_fail": 0,
        "mmr_users_ok": 0,
        "mmr_users_fail": 0,
        "mmr_samples": 0,
        "mmr_sample_new": 0,
        "mmr_sample_diff_insert": 0,
        "mmr_sample_same_insert": 0,
        "mmr_sample_update": 0,
        "mmr_uid_pool": 0,
        "mmr_uid_from_mm_top": 0,
        "mmr_uid_from_exp_top": 0,
        "mmr_uid_from_manual": 0,
        "mmr_uid_from_seed": 0,
        "mmr_users_skipped_recent": 0,
    }
    mm_uids: Set[str] = set()
    crawl_time = datetime.now()
    logger.info(
        "MM sync start: mm_limit=%d include_mm_ranking=%s include_mmr=%s mmr_min_interval_minutes=%d",
        mm_limit,
        include_mm_ranking,
        include_mmr,
        mmr_min_interval_minutes,
    )

    try:
        if include_mm_ranking:
            mode_iter = tqdm(MODES, desc="MM crawl", unit="mode") if HAS_TQDM else MODES
            for mode in mode_iter:
                if is_stop_requested():
                    logger.info("Stop requested, interrupt MM ranking crawl.")
                    break
                if consume_skip_request():
                    logger.warning("Skip requested, skip MM ranking mode %d.", mode)
                    continue
                task = f"mm_global_mode_{mode}"
                logger.info("MM ranking mode %d start...", mode)
                try:
                    rows = fetch_mm_global_mode(session, mode, mm_limit)
                    for item in rows:
                        uid = str(_safe_int(item.get("uid"), 0))
                        if uid != "0":
                            mm_uids.add(uid)
                    row_stats = save_mm_ranking_rows(
                        mode=mode,
                        rows=rows,
                        crawl_time=crawl_time,
                        source="mm_global",
                    )
                    stats["mm_rows"] += len(rows)
                    stats["mm_modes_ok"] += 1
                    update_mm_crawl_status(task, True, state=row_stats)
                    logger.info(
                        "MM ranking mode %d done: fetched=%d saved=%d",
                        mode,
                        row_stats.get("rows", 0),
                        row_stats.get("saved_rows", 0),
                    )
                    if HAS_TQDM:
                        mode_iter.set_postfix_str(
                            f"rows={stats['mm_rows']} ok={stats['mm_modes_ok']} fail={stats['mm_modes_fail']}"
                        )
                        tqdm.write(
                            colorize(
                                f"[MM][mode {mode}] fetched={row_stats.get('rows', 0)} saved={row_stats.get('saved_rows', 0)}",
                                "96",
                            )
                        )
                    else:
                        print(
                            colorize(
                                f"[MM][mode {mode}] fetched={row_stats.get('rows', 0)} saved={row_stats.get('saved_rows', 0)}",
                                "96",
                            )
                        )
                    time.sleep(0.2)
                except SkipCurrentTask as e:
                    update_mm_crawl_status(task, False, error="skipped_by_user", state={"mode": mode})
                    logger.warning("Skip requested, %s skipped.", e)
                    continue
                except Exception as e:
                    stats["mm_modes_fail"] += 1
                    update_mm_crawl_status(task, False, error=str(e), state={"mode": mode})
                    logger.warning("MM global crawl failed for mode %d: %s", mode, e)
                    if HAS_TQDM:
                        mode_iter.set_postfix_str(
                            f"rows={stats['mm_rows']} ok={stats['mm_modes_ok']} fail={stats['mm_modes_fail']}"
                        )
                        tqdm.write(colorize(f"[MM][mode {mode}] failed: {e}", "91"))
                    else:
                        print(colorize(f"[MM][mode {mode}] failed: {e}", "91"))
        else:
            mm_top_uids = get_recent_mm_tracked_uids(limit_per_mode=mm_limit)
            mm_uids.update(mm_top_uids)
            stats["mmr_uid_from_mm_top"] = len(mm_top_uids)

        if include_mm_ranking:
            stats["mmr_uid_from_mm_top"] = len(mm_uids)

        if include_exp_ranking_uids:
            exp_top_uids = get_recent_exp_tracked_uids(limit_per_mode=max(1, int(exp_limit or mm_limit)))
            before = len(mm_uids)
            mm_uids.update(exp_top_uids)
            stats["mmr_uid_from_exp_top"] = len(exp_top_uids)
            logger.info(
                "MMR uid pool add from EXP top: raw=%d merged=%d(+%d)",
                len(exp_top_uids),
                len(mm_uids),
                len(mm_uids) - before,
            )

        config_players = load_player_config()
        manual_uids = {str(uid).strip() for uid in config_players if str(uid).strip().isdigit()}
        before_manual = len(mm_uids)
        mm_uids.update(manual_uids)
        stats["mmr_uid_from_manual"] = len(manual_uids)
        logger.info(
            "MMR uid pool add from manual config: raw=%d merged=%d(+%d)",
            len(manual_uids),
            len(mm_uids),
            len(mm_uids) - before_manual,
        )

        if seed_uids:
            valid_seed = {str(uid).strip() for uid in seed_uids if str(uid).strip().isdigit()}
            before_seed = len(mm_uids)
            mm_uids.update(valid_seed)
            stats["mmr_uid_from_seed"] = len(valid_seed)
            logger.info(
                "MMR uid pool add from seed: raw=%d merged=%d(+%d)",
                len(valid_seed),
                len(mm_uids),
                len(mm_uids) - before_seed,
            )

        stats["mmr_uid_pool"] = len(mm_uids)
        logger.info(
            "MMR uid pool summary: total=%d mm_top=%d exp_top=%d manual=%d seed=%d",
            stats["mmr_uid_pool"],
            stats["mmr_uid_from_mm_top"],
            stats["mmr_uid_from_exp_top"],
            stats["mmr_uid_from_manual"],
            stats["mmr_uid_from_seed"],
        )

        if include_mmr:
            uid_list = sorted(mm_uids)
            if mmr_min_interval_minutes and mmr_min_interval_minutes > 0 and uid_list:
                db_manager = DatabaseManager()
                cursor = db_manager.get_connection().cursor()
                cutoff = datetime.now() - timedelta(minutes=int(mmr_min_interval_minutes))
                cursor.execute(
                    """
                    SELECT DISTINCT uid
                    FROM player_mmr_samples
                    WHERE crawl_time >= ?
                      AND uid IS NOT NULL
                      AND uid != ''
                    """,
                    (cutoff,),
                )
                recent_uids = {str(row[0]) for row in cursor.fetchall() if row and row[0]}
                filtered = [uid for uid in uid_list if uid not in recent_uids]
                stats["mmr_users_skipped_recent"] = len(uid_list) - len(filtered)
                if stats["mmr_users_skipped_recent"] > 0:
                    logger.info(
                        "MMR request de-dup: skip %d users sampled within %d minutes.",
                        stats["mmr_users_skipped_recent"],
                        mmr_min_interval_minutes,
                    )
                uid_list = filtered
            total_users = len(uid_list)
            logger.info("MMR sync start: users=%d", total_users)
            mmr_iter = tqdm(uid_list, desc="MMR鎶撳彇", unit="鐜╁") if HAS_TQDM else uid_list
            for idx, uid in enumerate(mmr_iter, start=1):
                if is_stop_requested():
                    logger.info("Stop requested, interrupt MMR crawl.")
                    break
                if consume_skip_request():
                    logger.warning("Skip requested, skip current MMR uid %s.", uid)
                    continue
                try:
                    player_rows = fetch_player_mmr_from_api(session, uid)
                    source = "ranking_player_all"
                    if not player_rows:
                        player_rows = fetch_player_mmr_from_page(session, uid)
                        source = "page_profile"
                    if not player_rows:
                        stats["mmr_users_fail"] += 1
                        continue
                    for item in player_rows:
                        if is_stop_requested():
                            break
                        if consume_skip_request():
                            raise SkipCurrentTask(f"mmr uid {uid}")
                        mode = _safe_int(item.get("mode"), -1)
                        mmr = _safe_int(item.get("mmr"), -1)
                        if mode < 0 or mmr < 0:
                            continue
                        name = item.get("name")
                        if name:
                            player_id = resolve_player_identity(name, crawl_time, uid=uid)
                        else:
                            player_id = get_player_id_by_uid(uid)
                        sample_op = save_player_mmr_sample(
                            player_id=player_id,
                            uid=uid,
                            mode=mode,
                            mmr=mmr,
                            mm_rank=item.get("mm_rank"),
                            name=name,
                            crawl_time=crawl_time,
                            source=source,
                        )
                        if sample_op in ("new", "diff_insert", "same_insert"):
                            stats["mmr_samples"] += 1
                        if sample_op == "new":
                            stats["mmr_sample_new"] += 1
                        elif sample_op == "diff_insert":
                            stats["mmr_sample_diff_insert"] += 1
                        elif sample_op == "same_insert":
                            stats["mmr_sample_same_insert"] += 1
                        elif sample_op == "update":
                            stats["mmr_sample_update"] += 1
                    stats["mmr_users_ok"] += 1
                    time.sleep(0.1)
                except SkipCurrentTask as e:
                    logger.warning("Skip requested, %s skipped.", e)
                    continue
                except Exception as e:
                    stats["mmr_users_fail"] += 1
                    logger.warning("MMR crawl failed for uid=%s: %s", uid, e)
                    if HAS_TQDM:
                        tqdm.write(colorize(f"[MMR][{idx}/{total_users}] uid={uid} failed: {e}", "91"))
                    else:
                        print(colorize(f"[MMR][{idx}/{total_users}] uid={uid} failed: {e}", "91"))
                if HAS_TQDM:
                    mmr_iter.set_postfix_str(
                        f"ok={stats['mmr_users_ok']} fail={stats['mmr_users_fail']} samples={stats['mmr_samples']}"
                    )
                if idx == 1 or idx % 20 == 0 or idx == total_users:
                    line = (
                        f"[MMR][{idx}/{total_users}] "
                        f"ok={stats['mmr_users_ok']} fail={stats['mmr_users_fail']} samples={stats['mmr_samples']}"
                    )
                    if HAS_TQDM:
                        tqdm.write(colorize(line, "93"))
                    else:
                        print(colorize(line, "93"))
                    logger.info(
                        "MMR progress: %d/%d users, ok=%d fail=%d samples=%d",
                        idx,
                        total_users,
                        stats["mmr_users_ok"],
                        stats["mmr_users_fail"],
                        stats["mmr_samples"],
                    )

            update_mm_crawl_status(
                "mmr_batch",
                success=(stats["mmr_users_fail"] == 0),
                error=None if stats["mmr_users_fail"] == 0 else f"failed={stats['mmr_users_fail']}",
                state=stats,
            )

        logger.info("MM sync done: %s", stats)
        return stats
    finally:
        _release_mm_run_lock()


def save_to_database(mode, df, crawl_time):
    """灏?DataFrame 涓殑鎺掕姒滄暟鎹€愭潯鏅鸿兘淇濆瓨鍒版暟鎹簱锛屽苟鎵撳嵃缁熻"""
    if df.empty:
        return

    stats = {'new': 0, 'diff_insert': 0, 'same_insert': 0, 'update': 0, 'update_fill': 0}

    for _, row in df.iterrows():
        player_id = resolve_player_identity(row['name'], crawl_time, row.get('player_id'))
        if player_id is not None:
            op = save_player_ranking_record(
                player_id=player_id,
                uid=row.get('player_id'),
                mode=mode,
                rank=row['rank'],
                name=row['name'],
                lv=row['lv'],
                exp=row['exp'],
                acc=row['acc'],
                combo=row['combo'],
                pc=row['pc'],
                crawl_time=crawl_time,
                source='leaderboard'  # 鎺掕姒滄暟鎹?
            )
            stats[op] += 1

    total = sum(stats.values())
    msg = (f"妯″紡 {mode} 鏁版嵁澶勭悊瀹屾垚: 鎬昏 {total} 鏉?| "
           f"{colorize('棣栨', '92')}: {stats['new']} | "
           f"{colorize('鍙樺寲鎻掑叆', '93')}: {stats['diff_insert']} | "
           f"{colorize('鐩稿悓鎻掑叆', '94')}: {stats['same_insert']} | "
           f"{colorize('鏃堕棿鏇存柊', '95')}: {stats['update']} | "
           f"{colorize('LV濉厖', '96')}: {stats['update_fill']}")
    print(msg)
    logger.info("妯″紡 %d 鏁版嵁缁熻: new=%d, diff=%d, same=%d, update=%d, fill=%d",
                mode, stats['new'], stats['diff_insert'], stats['same_insert'], stats['update'], stats['update_fill'])


def save_player_profile_to_database(player_data, crawl_time, player_identifier):
    """灏嗙帺瀹朵釜浜轰富椤电殑鎺掑悕鏁版嵁閫愭潯鏅鸿兘淇濆瓨鍒版暟鎹簱锛屽苟鏇存柊鐖彇鐘舵€?"""
    if not player_data:
        return False

    db_manager = DatabaseManager()
    conn = db_manager.get_connection()
    cursor = conn.cursor()
    success = False
    stats = {'new': 0, 'diff_insert': 0, 'same_insert': 0, 'update': 0, 'update_fill': 0}

    try:
        for data in player_data:
            player_id = resolve_player_identity(data['name'], crawl_time, player_identifier)
            if player_id is not None:
                op = save_player_ranking_record(
                    player_id=player_id,
                    uid=player_identifier,
                    mode=data['mode'],
                    rank=data['rank'],
                    name=data['name'],
                    lv=data['lv'],
                    exp=data['exp'],
                    acc=data['acc'],
                    combo=data['combo'],
                    pc=data['pc'],
                    crawl_time=crawl_time,
                    source='profile'  # 涓汉椤垫暟鎹?
                )
                stats[op] += 1
                success = True

        # 鏇存柊鐖彇鐘舵€?
        cursor.execute('''
            INSERT OR REPLACE INTO player_crawl_status
            (player_identifier, last_crawled, crawl_count, success_count, last_error)
            VALUES (?, ?,
                COALESCE((SELECT crawl_count FROM player_crawl_status WHERE player_identifier = ?), 0) + 1,
                COALESCE((SELECT success_count FROM player_crawl_status WHERE player_identifier = ?), 0) + ?,
                NULL)
        ''', (player_identifier, crawl_time, player_identifier, player_identifier, 1 if success else 0))
        conn.commit()

        total = sum(stats.values())
        msg = (f"鐜╁ {player_identifier} 鏁版嵁澶勭悊瀹屾垚: 鎬昏 {total} 鏉?| "
               f"{colorize('棣栨', '92')}: {stats['new']} | "
               f"{colorize('鍙樺寲鎻掑叆', '93')}: {stats['diff_insert']} | "
               f"{colorize('鐩稿悓鎻掑叆', '94')}: {stats['same_insert']} | "
               f"{colorize('鏃堕棿鏇存柊', '95')}: {stats['update']} | "
               f"{colorize('LV濉厖', '96')}: {stats['update_fill']}")
        print(msg)
        logger.info("鐜╁ %s 鏁版嵁缁熻: new=%d, diff=%d, same=%d, update=%d, fill=%d",
                    player_identifier, stats['new'], stats['diff_insert'], stats['same_insert'], stats['update'], stats['update_fill'])
        return success

    except Exception as e:
        logger.error("淇濆瓨鐜╁ %s 鏁版嵁鍒版暟鎹簱澶辫触: %s", player_identifier, e)
        # 璁板綍澶辫触鐘舵€?
        cursor.execute('''
            INSERT OR REPLACE INTO player_crawl_status
            (player_identifier, last_crawled, crawl_count, success_count, last_error)
            VALUES (?, ?,
                COALESCE((SELECT crawl_count FROM player_crawl_status WHERE player_identifier = ?), 0) + 1,
                COALESCE((SELECT success_count FROM player_crawl_status WHERE player_identifier = ?), 0),
                ?)
        ''', (player_identifier, crawl_time, player_identifier, player_identifier, str(e)))
        conn.commit()
        return False


def check_excel_file_integrity(filename):
    """妫€鏌?Excel 鏂囦欢鏄惁瀹屾暣鍙敤"""
    try:
        if not os.path.exists(filename):
            return False
        with open(filename, 'rb') as f:
            header = f.read(8)
            if header[:4] != b'PK\x03\x04':
                return False
        wb = load_workbook(filename, read_only=True)
        sheetnames = wb.sheetnames
        wb.close()
        return bool(sheetnames)
    except Exception as e:
        logger.warning("Excel鏂囦欢瀹屾暣鎬ф鏌ュけ璐? %s - %s", filename, e)
        return False


def repair_excel_file(filename):
    """灏濊瘯淇鎹熷潖鐨?Excel 鏂囦欢"""
    try:
        backup_name = f"{filename}.backup.{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        import shutil
        shutil.copy2(filename, backup_name)
        logger.info("宸插垱寤哄浠芥枃浠? %s", backup_name)

        try:
            xl = pd.ExcelFile(filename)
            with pd.ExcelWriter(filename, engine='openpyxl') as writer:
                for sheet_name in xl.sheet_names:
                    df = pd.read_excel(filename, sheet_name=sheet_name)
                    df.to_excel(writer, sheet_name=sheet_name, index=False)
            logger.info("鎴愬姛淇Excel鏂囦欢: %s", filename)
            return True
        except Exception as e:
            logger.error("浣跨敤pandas淇澶辫触: %s", e)
            try:
                wb = load_workbook(filename)
                wb.save(filename)
                logger.info("浣跨敤openpyxl淇鎴愬姛: %s", filename)
                return True
            except Exception as e2:
                logger.error("浣跨敤openpyxl淇涔熷け璐? %s", e2)
                return False
    except Exception as e:
        logger.error("淇Excel鏂囦欢杩囩▼涓彂鐢熼敊璇? %s", e)
        return False


def import_mode_data(mode):
    """瀵煎叆鍗曚釜妯″紡鐨勫巻鍙叉暟鎹紙浠?Excel 鍒版暟鎹簱锛?"""
    global stop_requested

    thread_id = threading.get_ident()
    db_manager = DatabaseManager()
    conn = db_manager.get_connection(thread_id)

    conn.execute("PRAGMA synchronous = OFF")
    conn.execute("PRAGMA journal_mode = MEMORY")
    conn.execute("PRAGMA cache_size = 10000")
    conn.execute("PRAGMA temp_store = MEMORY")

    player_alias_cache = {}

    filename = get_excel_filename(mode)
    if not os.path.exists(filename):
        logger.warning("妯″紡 %d 鐨凟xcel鏂囦欢涓嶅瓨鍦? %s", mode, filename)
        return 0

    if not check_excel_file_integrity(filename):
        logger.warning("妯″紡 %d 鐨凟xcel鏂囦欢鍙兘宸叉崯鍧? %s", mode, filename)
        if repair_excel_file(filename):
            logger.info("鏂囦欢淇鎴愬姛锛岀户缁鍏?")
        else:
            logger.error("鏂囦欢淇澶辫触锛岃烦杩囨ā寮?%d", mode)
            return 0

    cursor = conn.cursor()
    cursor.execute(
        "SELECT last_import_time FROM import_metadata WHERE mode = ?",
        (mode,)
    )
    result = cursor.fetchone()
    last_import_time = result[0] if result else None

    try:
        xl = pd.ExcelFile(filename)
        sheet_names = xl.sheet_names
    except Exception as e:
        logger.error("鎵撳紑Excel鏂囦欢澶辫触: %s", e)
        try:
            wb = load_workbook(filename)
            sheet_names = wb.sheetnames
        except Exception as e2:
            logger.error("涓ょ鏂瑰紡閮芥棤娉曟墦寮€Excel鏂囦欢: %s", e2)
            return 0

    sheet_names = [s for s in sheet_names if s.startswith(f"mode_{mode}_")]

    sheet_times = []
    for sheet_name in sheet_names:
        try:
            time_str = sheet_name.replace(f"mode_{mode}_", "")
            sheet_time = datetime.strptime(time_str, "%Y-%m-%d_%H-%M")
            sheet_times.append((sheet_name, sheet_time))
        except:
            continue

    sheet_times.sort(key=lambda x: x[1])

    if HAS_TQDM:
        mode_pbar = tqdm(
            sheet_times,
            desc=f"妯″紡 {mode}",
            position=mode + 1,
            leave=False,
            unit="row"
        )
    else:
        mode_pbar = sheet_times
        print(f"寮€濮嬪鐞嗘ā寮?{mode}锛屽叡 {len(sheet_times)} 涓〃...")

    imported_count = 0
    batch_size = 50
    batch_data = []

    for i, (sheet_name, sheet_time) in enumerate(mode_pbar):
        with stop_lock:
            if stop_requested:
                logger.info("Mode %d import interrupted, imported %d rows.", mode, imported_count)
                break

        if last_import_time and sheet_time <= datetime.strptime(last_import_time, "%Y-%m-%d %H:%M:%S"):
            if HAS_TQDM:
                mode_pbar.update(1)
            continue

        try:
            df = pd.read_excel(filename, sheet_name=sheet_name)
            if df.empty:
                if HAS_TQDM:
                    mode_pbar.update(1)
                continue

            for _, row in df.iterrows():
                name = row['name']
                if name in player_alias_cache:
                    player_id = player_alias_cache[name]
                else:
                    player_id = resolve_player_identity(name, sheet_time)
                    player_alias_cache[name] = player_id

                if player_id is not None:
                    batch_data.append((
                        player_id, None, mode, row['rank'], name, row['lv'], row['exp'],
                        row['acc'], row['combo'], row['pc'], sheet_time
                    ))

            if batch_data and (len(batch_data) >= 1000 or i == len(sheet_times) - 1):
                cursor.executemany('''
                INSERT OR IGNORE INTO player_rankings
                (player_id, uid, mode, rank, name, lv, exp, acc, combo, pc, crawl_time)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', batch_data)
                imported_count += len(batch_data)
                batch_data = []

            if (i + 1) % batch_size == 0 or i == len(sheet_times) - 1:
                cursor.execute(
                    "UPDATE import_metadata SET last_import_time = ? WHERE mode = ?",
                    (sheet_time.strftime("%Y-%m-%d %H:%M:%S"), mode)
                )
                conn.commit()

            if HAS_TQDM:
                mode_pbar.set_postfix_str(f"宸插鍏? {imported_count}")

        except Exception as e:
            logger.error("瀵煎叆妯″紡 %d 琛?%s 鏃跺嚭閿? %s", mode, sheet_name, e)
            conn.rollback()
            continue

    if batch_data:
        cursor.executemany('''
        INSERT OR IGNORE INTO player_rankings
        (player_id, uid, mode, rank, name, lv, exp, acc, combo, pc, crawl_time)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', batch_data)
        imported_count += len(batch_data)
        conn.commit()

    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.commit()

    db_manager.close_connection(thread_id)

    if HAS_TQDM:
        mode_pbar.close()

    return imported_count


def import_historical_data():
    """浠庢墍鏈夋ā寮忕殑 Excel 鏂囦欢瀵煎叆鍘嗗彶鏁版嵁鍒版暟鎹簱"""
    if HAS_TQDM:
        main_pbar = tqdm(total=len(MODES), desc="鎬讳綋杩涘害", position=0)
    else:
        print("寮€濮嬪鍏ュ巻鍙叉暟鎹?..")

    for mode in MODES:
        try:
            result = import_mode_data(mode)
            if HAS_TQDM:
                main_pbar.update(1)
                main_pbar.set_postfix_str(f"妯″紡 {mode} 瀹屾垚: {result} 鏉¤褰?")
            else:
                print(f"妯″紡 {mode} 瀹屾垚: {result} 鏉¤褰?")
        except Exception as e:
            logger.error("妯″紡 %d 瀵煎叆澶辫触: %s", mode, e)
            if HAS_TQDM:
                main_pbar.update(1)
                main_pbar.set_postfix_str(f"妯″紡 {mode} 澶辫触: {e}")
            else:
                print(f"妯″紡 {mode} 澶辫触: {e}")

    if HAS_TQDM:
        main_pbar.close()

    if not HAS_TQDM:
        print("鍘嗗彶鏁版嵁瀵煎叆瀹屾垚")


def load_player_config():
    """鍔犺浇鐜╁閰嶇疆鏂囦欢 players.txt锛岃繑鍥炵帺瀹禝D鍒楄〃"""
    players = []
    if not os.path.exists(PLAYER_CONFIG_FILE):
        logger.info("鐜╁閰嶇疆鏂囦欢涓嶅瓨鍦紝鍒涘缓绌烘枃浠? %s", PLAYER_CONFIG_FILE)
        with open(PLAYER_CONFIG_FILE, 'w', encoding='utf-8') as f:
            f.write("# 姣忚涓€涓帺瀹禝D锛堝繀椤绘槸鏁板瓧锛塡n")
            f.write("# 渚嬪:\n")
            f.write("# 923177\n")
            f.write("# 123456\n")
        return players
    try:
        with open(PLAYER_CONFIG_FILE, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#'):
                    players.append(line)
        logger.info("Loaded %d players from config file.", len(players))
        return players
    except Exception as e:
        logger.error("鍔犺浇鐜╁閰嶇疆鏂囦欢澶辫触: %s", e)
        return []


def add_players_to_queue(players):
    """灏嗙帺瀹舵坊鍔犲埌鐖彇闃熷垪锛岃嚜鍔ㄥ幓閲?"""
    added = 0
    with _player_set_lock:
        for player in players:
            if player not in _player_set:
                _player_set.add(player)
                player_queue.put(player)
                added += 1
    if added > 0:
        logger.info("Added %d new players into crawl queue.", added)


def get_players_from_leaderboard(df_list):
    """浠庢帓琛屾鏁版嵁涓彁鍙栨墍鏈夌帺瀹禝D锛堝幓閲嶏級"""
    players = set()
    for df in df_list:
        if not df.empty and 'player_id' in df.columns:
            for player_id in df['player_id']:
                if player_id:
                    players.add(player_id)
    return list(players)


def run_player_crawler():
    """杩愯鐜╁涓汉涓婚〉鐖彇鍣紙鍚屾鎵ц锛?"""
    global player_crawl_in_progress, last_player_crawl_time

    with player_crawl_lock:
        if player_crawl_in_progress:
            logger.info("鐜╁鐖彇鍣ㄥ凡鍦ㄨ繍琛岋紝璺宠繃")
            return
        player_crawl_in_progress = True

    try:
        logger.info("寮€濮嬬帺瀹朵釜浜轰富椤电埇鍙栧懆鏈?")
        last_player_crawl_time = datetime.now()

        session = requests.Session()
        session.cookies.update(COOKIES)
        session.headers.update(HEADERS)
        session.mount('https://', requests.adapters.HTTPAdapter(max_retries=3))

        with _player_set_lock:
            total_players = len(_player_set)
        if total_players == 0:
            logger.info("鐖彇闃熷垪涓虹┖锛岃烦杩?")
            return

        logger.info("寮€濮嬬埇鍙?%d 涓帺瀹剁殑涓汉涓婚〉鏁版嵁", total_players)

        successful_crawls = 0
        failed_crawls = 0

        if HAS_TQDM:
            pbar = tqdm(total=total_players, desc="鐜╁涓婚〉鐖彇", unit="鐜╁")
        else:
            print(f"寮€濮嬬埇鍙?{total_players} 涓帺瀹剁殑涓汉涓婚〉鏁版嵁...")

        while True:
            if is_stop_requested():
                logger.info("Player crawler interrupted by stop request.")
                break

            try:
                player_identifier = player_queue.get_nowait()
            except queue.Empty:
                break

            # Remove from dedupe set once popped from queue.
            with _player_set_lock:
                _player_set.discard(player_identifier)

            try:
                player_data = crawl_player_profile(session, player_identifier)
                crawl_time = datetime.now()

                if consume_skip_request():
                    logger.warning("Skip requested, skip player %s.", player_identifier)
                    continue

                if player_data and save_player_profile_to_database(player_data, crawl_time, player_identifier):
                    successful_crawls += 1
                else:
                    failed_crawls += 1

                if HAS_TQDM:
                    pbar.set_postfix_str(f"???: {successful_crawls}, ???: {failed_crawls}")

                time.sleep(3)

            except Exception as e:
                logger.error("Error while processing player %s: %s", player_identifier, e)
                failed_crawls += 1
                if HAS_TQDM:
                    pbar.set_postfix_str(f"???: {successful_crawls}, ???: {failed_crawls}")
            finally:
                if HAS_TQDM:
                    _ = pbar.update(1)
                player_queue.task_done()

        if HAS_TQDM:
            pbar.close()

        logger.info("鐜╁涓汉涓婚〉鐖彇瀹屾垚: 鎴愬姛 %d, 澶辫触 %d", successful_crawls, failed_crawls)

    except Exception as e:
        logger.error("鐜╁鐖彇鍛ㄦ湡鍙戠敓閿欒: %s", e)
    finally:
        with player_crawl_lock:
            player_crawl_in_progress = False


def git_check_updates():
    """妫€鏌ヨ繙绋?Git 浠撳簱鏄惁鏈夋洿鏂帮紙浠呮娴?.db 鍜?.xlsx 鏂囦欢锛?"""
    try:
        if not os.path.exists(os.path.join(GIT_REPO_PATH, '.git')):
            logger.info("褰撳墠鐩綍涓嶆槸Git浠撳簱锛岃烦杩嘒it鏇存柊妫€鏌?")
            return False

        original_cwd = os.getcwd()
        os.chdir(GIT_REPO_PATH)

        result = subprocess.run(["git", "remote", "-v"], capture_output=True, text=True)
        if not result.stdout.strip():
            logger.info("鏈厤缃瓽it杩滅▼浠撳簱锛岃烦杩囨洿鏂版鏌?")
            os.chdir(original_cwd)
            return False

        result = subprocess.run(["git", "fetch", "origin"], capture_output=True, text=True)
        if result.returncode != 0:
            logger.warning("Git fetch澶辫触: %s", result.stderr)
            os.chdir(original_cwd)
            return False

        result = subprocess.run(
            ["git", "diff", "--name-only", "HEAD", "origin/main", "--", "*.db", "*.xlsx"],
            capture_output=True, text=True
        )

        os.chdir(original_cwd)

        if result.stdout.strip():
            updated_files = result.stdout.strip().split('\n')
            logger.info("鍙戠幇杩滅▼鏇存柊鏂囦欢: %s", updated_files)
            return True
        else:
            logger.info("杩滅▼浠撳簱娌℃湁.db鎴?xlsx鏂囦欢鐨勬洿鏂?")
            return False

    except subprocess.CalledProcessError as e:
        logger.warning("Git妫€鏌ユ洿鏂板け璐? %s", e)
        return False
    except Exception as e:
        logger.warning("Git妫€鏌ユ洿鏂板彂鐢熸剰澶栭敊璇? %s", e)
        return False


def git_pull_data_files():
    """浠庤繙绋?Git 浠撳簱鎷夊彇鏁版嵁鏂囦欢锛堢敤鎴蜂氦浜掔‘璁わ級"""
    try:
        if not os.path.exists(os.path.join(GIT_REPO_PATH, '.git')):
            logger.info("褰撳墠鐩綍涓嶆槸Git浠撳簱锛岃烦杩嘒it鎷夊彇")
            return False

        print("\n" + "="*60)
        print("妫€娴嬪埌杩滅▼浠撳簱鏈夋洿鏂帮紒")
        print("鏇存柊鏂囦欢鍖呮嫭: catch.xlsx, key.xlsx, malody_rankings.db 绛夋暟鎹枃浠?")
        print("杩欎簺鏇存柊灏嗚鐩栨偍鏈湴鐨勬暟鎹枃浠躲€?")
        print("="*60)
        print("鎮ㄦ湁10绉掓椂闂村喅瀹氭槸鍚︽媺鍙栨洿鏂帮細")
        print("  - 杈撳叆 'y' 鎴?'yes' 纭鎷夊彇")
        print("  - 杈撳叆 'n' 鎴?'no' 璺宠繃鎷夊彇")
        print("  - 10绉掑唴鏃犲搷搴斿皢鑷姩璺宠繃")
        print("="*60)

        try:
            import select
            import sys
            print("璇风‘璁ゆ槸鍚︽媺鍙栨洿鏂?(y/n, 10绉掕秴鏃?: ", end='', flush=True)
            start_time = time.time()
            while time.time() - start_time < 10:
                if select.select([sys.stdin], [], [], 0.1)[0]:
                    user_input = sys.stdin.readline().strip().lower()
                    if user_input in ['y', 'yes']:
                        print("纭鎷夊彇鏇存柊...")
                        break
                    elif user_input in ['n', 'no']:
                        print("璺宠繃鎷夊彇鏇存柊銆?")
                        return False
                    else:
                        print("鏃犳晥杈撳叆锛岃杈撳叆 y 鎴?n: ", end='', flush=True)
                time.sleep(0.1)
            else:
                print("\n10绉掕秴鏃讹紝鑷姩璺宠繃鎷夊彇鏇存柊銆?")
                return False
        except ImportError:
            print("璇风‘璁ゆ槸鍚︽媺鍙栨洿鏂?(y/n, 10绉掕秴鏃?: ", end='', flush=True)
            user_input = input()
            if user_input.lower() in ['y', 'yes']:
                print("纭鎷夊彇鏇存柊...")
            else:
                print("璺宠繃鎷夊彇鏇存柊銆?")
                return False

        original_cwd = os.getcwd()
        os.chdir(GIT_REPO_PATH)

        DatabaseManager().close_connection()

        excel_files = [get_excel_filename(mode) for mode in MODES]
        files_to_pull = [f for f in excel_files if os.path.exists(f)]
        files_to_pull.append(DB_FILE)

        success = True
        for file in files_to_pull:
            result = subprocess.run(
                ["git", "checkout", "origin/main", "--", file],
                capture_output=True, text=True
            )
            if result.returncode == 0:
                logger.info("宸叉媺鍙栨枃浠? %s", file)
            else:
                logger.warning("鎷夊彇鏂囦欢 %s 澶辫触: %s", file, result.stderr)
                success = False

        os.chdir(original_cwd)
        return success
    except subprocess.CalledProcessError as e:
        logger.warning("Git鎷夊彇鏂囦欢澶辫触: %s", e)
        return False
    except Exception as e:
        logger.warning("Git鎷夊彇鏂囦欢鍙戠敓鎰忓閿欒: %s", e)
        return False


def git_add_commit_push(has_changes=True):
    """鑷姩娣诲姞銆佹彁浜ゅ拰鎺ㄩ€?Git 鏇存敼"""
    if not has_changes:
        logger.info("鎵€鏈夋ā寮忓潎鏃犳暟鎹彉鍖栵紝璺宠繃Git鎺ㄩ€?")
        return True

    try:
        if not os.path.exists(os.path.join(GIT_REPO_PATH, '.git')):
            logger.info("褰撳墠鐩綍涓嶆槸Git浠撳簱锛岃烦杩嘒it鎺ㄩ€?")
            return True

        original_cwd = os.getcwd()
        os.chdir(GIT_REPO_PATH)

        result = subprocess.run(["git", "remote", "-v"], capture_output=True, text=True)
        if not result.stdout.strip():
            logger.info("鏈厤缃瓽it杩滅▼浠撳簱锛岃烦杩囨帹閫?")
            os.chdir(original_cwd)
            return True

        excel_files = [get_excel_filename(mode) for mode in MODES]
        files_to_add = [f for f in excel_files if os.path.exists(f)]
        files_to_add.append(DB_FILE)

        for file in files_to_add:
            result = subprocess.run(["git", "add", file], capture_output=True, text=True)
            if result.returncode != 0:
                logger.warning("娣诲姞鏂囦欢 %s 澶辫触: %s", file, result.stderr)

        result = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True)
        if not result.stdout.strip():
            logger.info("娌℃湁鏂囦欢鏇存敼锛岃烦杩嘒it鎻愪氦")
            os.chdir(original_cwd)
            return True

        result = subprocess.run(["git", "commit", "-m", GIT_COMMIT_MESSAGE], capture_output=True, text=True)
        if result.returncode == 0:
            logger.info("Git鎻愪氦鎴愬姛: %s", GIT_COMMIT_MESSAGE)
        else:
            logger.warning("Git鎻愪氦澶辫触: %s", result.stderr)
            os.chdir(original_cwd)
            return False

        result = subprocess.run(["git", "push"], capture_output=True, text=True)
        if result.returncode == 0:
            logger.info("Git鎺ㄩ€佹垚鍔?")
            success = True
        else:
            logger.warning("Git鎺ㄩ€佸け璐? %s", result.stderr)
            success = False

        os.chdir(original_cwd)
        return success
    except subprocess.CalledProcessError as e:
        logger.warning("Git鎿嶄綔澶辫触: %s", e)
        return False
    except Exception as e:
        logger.warning("Git鎿嶄綔鍙戠敓鎰忓閿欒: %s", e)
        return False


def check_data_changed(mode, df):
    """妫€鏌ュ綋鍓嶆暟鎹笌鏈€鏂扮殑 Excel 琛ㄦ槸鍚︾浉鍚岋紙鐢ㄤ簬鍐冲畾鏄惁淇濆瓨 Excel锛?"""
    filename = get_excel_filename(mode)
    sheet_name = f"mode_{mode}"

    if not os.path.exists(filename):
        return True

    try:
        wb = load_workbook(filename)
        if sheet_name not in wb.sheetnames:
            return True

        sub_sheets = [s for s in wb.sheetnames if s.startswith(f"{sheet_name}_")]
        if not sub_sheets:
            return True

        latest_sheet = None
        latest_time = None
        for s in sub_sheets:
            try:
                dt_str = s.replace(f"{sheet_name}_", "")
                dt = datetime.strptime(dt_str, "%Y-%m-%d_%H-%M")
                if latest_time is None or dt > latest_time:
                    latest_time = dt
                    latest_sheet = s
            except:
                continue

        if latest_sheet:
            df_prev = pd.read_excel(filename, sheet_name=latest_sheet)
            if not df_prev.empty and df_prev.equals(df):
                return False
    except Exception as e:
        logger.error("妫€鏌ユ暟鎹彉鍖栨椂鍑洪敊: %s", e)
        return True

    return True


def run_crawler_cycle(
    crawl_players=False,
    crawl_leaderboard_players=False,
    save_excel=False,
    push_to_git=False,
    mm_sync=False,
    mm_limit=DEFAULT_MM_LIMIT,
    skip_mm_ranking=False,
    skip_mmr=False,
    ranking_source="page",
    ranking_limit=DEFAULT_MM_LIMIT,
):
    """
    杩愯涓€涓埇鍙栧懆鏈熴€?

    Args:
        crawl_players: 鏄惁鍚姩鐜╁鐖櫕锛堟秷璐归槦鍒椾腑鐨勭帺瀹禝D锛屽寘鍚厤缃枃浠朵腑鐨勭帺瀹讹級
        crawl_leaderboard_players: 鏄惁灏嗗綋鍓嶆帓琛屾涓殑鐜╁ID鍔犲叆闃熷垪
        save_excel: 鏄惁淇濆瓨鏁版嵁鍒?Excel 鏂囦欢
        push_to_git: 鏄惁鎺ㄩ€佹暟鎹埌 Git 浠撳簱
        mm_sync: 鏄惁鍦ㄦ湰杞墽琛?MM/MMR 鍚屾
        mm_limit: 姣忎釜妯″紡鎶撳彇鐨?MM 姒滃崟涓婇檺
    """
    # 姣忎釜鍛ㄦ湡閲嶆柊鍔犺浇閰嶇疆鏂囦欢鐜╁
    if crawl_players:
        config_players = load_player_config()
        if config_players:
            add_players_to_queue(config_players)
            logger.info("鍛ㄦ湡寮€濮嬶細宸查噸鏂板姞杞?%d 涓厤缃枃浠剁帺瀹跺埌闃熷垪", len(config_players))

    try:
        if push_to_git and git_check_updates():
            logger.info("妫€娴嬪埌杩滅▼浠撳簱鏈夋洿鏂帮紝姝ｅ湪鎷夊彇鏁版嵁鏂囦欢...")
            if git_pull_data_files():
                logger.info("鏁版嵁鏂囦欢鎷夊彇瀹屾垚锛岄噸鏂板垵濮嬪寲鏁版嵁搴?..")
                DatabaseManager().close_connection()
                init_database()
            else:
                logger.warning("鏁版嵁鏂囦欢鎷夊彇澶辫触锛岀户缁娇鐢ㄦ湰鍦版暟鎹?")
        else:
            logger.info("鏈娴嬪埌杩滅▼鏇存柊鎴朑it涓嶅彲鐢紝缁х画浣跨敤鏈湴鏁版嵁")
    except Exception as e:
        logger.warning("Git鏇存柊妫€鏌ュけ璐ワ紝缁х画浣跨敤鏈湴鏁版嵁: %s", e)

    session = requests.Session()
    session.cookies.update(COOKIES)
    session.headers.update(HEADERS)
    session.mount('https://', requests.adapters.HTTPAdapter(max_retries=3))

    start_time = datetime.now()
    logger.info("=" * 50)
    logger.info("寮€濮嬬埇鍙栧懆鏈? %s", start_time)

    has_changes = False
    all_dfs = []

    for mode in MODES:
        if is_stop_requested():
            logger.info("Stop requested, interrupt ranking crawl cycle.")
            break
        if consume_skip_request():
            logger.warning("Skip requested, skip current ranking mode %d.", mode)
            continue

        try:
            logger.info("Processing ranking mode: %d", mode)
            mm_rows: List[Dict[str, Any]] = []
            if ranking_source == "newapi":
                df, mm_rows = crawl_mode_player_newapi(session, mode, ranking_limit)
            else:
                df = crawl_mode_player(session, mode)
            all_dfs.append(df)

            if consume_skip_request():
                raise SkipCurrentTask(f"ranking mode {mode}")

            if df.empty:
                logger.warning("Mode %d returned empty ranking data, skip.", mode)
                continue

            if save_excel and not check_data_changed(mode, df):
                logger.info("Mode %d data unchanged, skip Excel save.", mode)

            crawl_time = datetime.now()

            if save_excel and check_data_changed(mode, df):
                save_data_to_excel(mode, df, crawl_time)

            if consume_skip_request():
                raise SkipCurrentTask(f"ranking mode {mode}")

            save_to_database(mode, df, crawl_time)
            if ranking_source == "newapi" and mm_rows:
                mm_row_stats = save_mm_ranking_rows(
                    mode=mode,
                    rows=mm_rows,
                    crawl_time=crawl_time,
                    source="newapi_ranking_global",
                )
                update_mm_crawl_status(
                    task=f"mm_global_mode_{mode}",
                    success=True,
                    state={"source": "newapi_ranking_global", **mm_row_stats},
                )
            has_changes = True

            time.sleep(3)
        except SkipCurrentTask as e:
            logger.warning("Skip requested, %s skipped.", e)
            continue
        except Exception as e:
            logger.exception("Unexpected error while processing mode %d", mode)

    mm_seed_uids: Set[str] = set(get_players_from_leaderboard(all_dfs)) if all_dfs else set()

    if mm_sync and not is_stop_requested():
        logger.info("Start MM/MMR sync...")
        if consume_skip_request():
            logger.warning("Skip requested, skip MM/MMR sync in this cycle.")
        else:
            try:
                include_mm_ranking = not skip_mm_ranking
                if ranking_source == "newapi" and include_mm_ranking:
                    logger.info("Ranking source is newapi, skip duplicate MM ranking fetch in mm_sync.")
                    include_mm_ranking = False
                run_mm_sync_cycle(
                    mm_limit=mm_limit,
                    include_mm_ranking=include_mm_ranking,
                    include_mmr=not skip_mmr,
                    include_exp_ranking_uids=True,
                    exp_limit=ranking_limit if ranking_source == "newapi" else mm_limit,
                    seed_uids=mm_seed_uids,
                )
            except Exception as e:
                logger.warning("MM/MMR sync failed, continue with existing flow: %s", e)

    if crawl_players and crawl_leaderboard_players and all_dfs:
        leaderboard_players = get_players_from_leaderboard(all_dfs)
        if leaderboard_players:
            add_players_to_queue(leaderboard_players)
            logger.info("浠庢帓琛屾娣诲姞浜?%d 涓帺瀹跺埌鐖彇闃熷垪", len(leaderboard_players))

    # 鍚姩鐜╁鐖彇锛堝悓姝ユ墽琛岋級
    if crawl_players:
        logger.info("鍚屾鎵ц鐜╁涓婚〉鐖彇...")
        run_player_crawler()
    else:
        logger.info("鐜╁鐖彇宸茬鐢紝璺宠繃")

    # 鍙湁鍦ㄦ槑纭寚瀹氭椂鎵嶆帹閫?Git
    if push_to_git:
        try:
            _ = git_add_commit_push(has_changes)
        except Exception as e:
            logger.warning("Git鎺ㄩ€佸け璐ワ紝浣嗘暟鎹凡淇濆瓨鍒版湰鍦? %s", e)
    else:
        logger.info("Git鎺ㄩ€佸凡绂佺敤锛屾暟鎹粎淇濆瓨鍦ㄦ湰鍦?")

    end_time = datetime.now()
    duration = (end_time - start_time).total_seconds()
    logger.info("Crawl cycle completed, duration: %.2fs", duration)
    logger.info("=" * 50)


def optimize_database():
    """
    浼樺寲鏁版嵁搴擄細鎸夌収鏂拌鍒欐竻鐞嗘棫鏁版嵁锛屽彧淇濈暀蹇呰璁板綍銆?
    瀵逛簬姣忎釜鐜╁姣忎釜妯″紡锛屾寜鏃堕棿鎺掑簭锛?
      - 濡傛灉杩炵画涓ゆ潯璁板綍鏁版嵁鐩稿悓锛屽垯鍒犻櫎涓棿閲嶅鐨勶紝浠呬繚鐣欑涓€鏉″拰鏈€鍚庝竴鏉°€?
    鏈€缁堢粨鏋滐細姣忎釜鐜╁姣忎釜妯″紡鐨勬暟鎹簭鍒椾腑锛岀浉閭讳袱鏉¤褰曠殑鏁版嵁涓€瀹氫笉鍚屻€?
    鎵撳嵃浼樺寲鍓嶅悗鐨勮褰曟暟鍜屾暟鎹簱鏂囦欢澶у皬锛屽苟璁＄畻浼樺寲鐜囥€?
    """
    logger.info("寮€濮嬫暟鎹簱浼樺寲...")
    db_manager = DatabaseManager()
    conn = db_manager.get_connection()
    cursor = conn.cursor()

    # 鑾峰彇浼樺寲鍓嶇殑璁板綍鎬绘暟鍜屾枃浠跺ぇ灏?
    cursor.execute("SELECT COUNT(*) FROM player_rankings")
    before_count = cursor.fetchone()[0]
    before_size = os.path.getsize(DB_FILE) if os.path.exists(DB_FILE) else 0

    # 鑾峰彇鎵€鏈夌帺瀹禝D鍜屾ā寮?
    cursor.execute("SELECT DISTINCT player_id, mode FROM player_rankings")
    player_mode_pairs = cursor.fetchall()

    total_pairs = len(player_mode_pairs)
    if total_pairs == 0:
        logger.info("鏁版嵁搴撲负绌猴紝鏃犻渶浼樺寲")
        return

    # 浣跨敤浜嬪姟鎵归噺澶勭悊
    conn.execute("BEGIN TRANSACTION")
    deleted_total = 0
    kept_total = 0

    # 浣跨敤杩涘害鏉?
    iterator = tqdm(player_mode_pairs, desc="Optimize DB", unit="pair") if HAS_TQDM else player_mode_pairs

    for player_id, mode in iterator:
        # 鑾峰彇璇ョ帺瀹惰妯″紡鐨勬墍鏈夎褰曪紝鎸夋椂闂村崌搴?
        cursor.execute('''
            SELECT id, rank, name, lv, exp, acc, combo, pc, crawl_time
            FROM player_rankings
            WHERE player_id = ? AND mode = ?
            ORDER BY crawl_time ASC
        ''', (player_id, mode))
        rows = cursor.fetchall()

        if len(rows) <= 1:
            continue

        to_delete = []
        i = 0
        while i < len(rows):
            j = i + 1
            # 鎵惧埌浠?i 寮€濮嬬殑杩炵画鐩稿悓鏁版嵁娈?
            while j < len(rows) and rows[j][1:8] == rows[i][1:8]:  # 姣旇緝 rank~pc
                j += 1
            # 鍖洪棿涓?[i, j-1]锛岃嫢闀垮害 > 1锛屽垯鍒犻櫎涓棿閮ㄥ垎锛堜繚鐣?i 鍜?j-1锛?
            if j - i > 1:
                for k in range(i + 1, j - 1):
                    to_delete.append(rows[k][0])
            i = j

        if to_delete:
            placeholders = ','.join('?' * len(to_delete))
            cursor.execute(f"DELETE FROM player_rankings WHERE id IN ({placeholders})", to_delete)
            deleted_total += len(to_delete)
            if HAS_TQDM:
                _ = iterator.set_postfix(deleted=deleted_total)

    conn.commit()

    # 鑾峰彇浼樺寲鍚庣殑璁板綍鎬绘暟鍜屾枃浠跺ぇ灏?
    cursor.execute("SELECT COUNT(*) FROM player_rankings")
    after_count = cursor.fetchone()[0]
    # 鎵ц VACUUM 浠ュ帇缂╂暟鎹簱
    conn.execute("VACUUM")
    after_size = os.path.getsize(DB_FILE)

    # 璁＄畻鍙樺寲
    delta_count = before_count - after_count
    delta_size = before_size - after_size
    count_ratio = (delta_count / before_count * 100) if before_count > 0 else 0
    size_ratio = (delta_size / before_size * 100) if before_size > 0 else 0

    # 鎵撳嵃鎶ュ憡
    print("\n" + "="*50)
    print("鏁版嵁搴撲紭鍖栧畬鎴?")
    print("="*50)
    print(f"浼樺寲鍓嶈褰曟暟: {before_count}")
    print(f"浼樺寲鍚庤褰曟暟: {after_count}")
    print(f"鍒犻櫎璁板綍鏁? {delta_count} ({count_ratio:.2f}%)")
    print(f"浼樺寲鍓嶆枃浠跺ぇ灏? {before_size/1024:.2f} KB")
    print(f"浼樺寲鍚庢枃浠跺ぇ灏? {after_size/1024:.2f} KB")
    print(f"鑺傜渷绌洪棿: {delta_size/1024:.2f} KB ({size_ratio:.2f}%)")
    print("="*50)

    logger.info("鏁版嵁搴撲紭鍖栧畬鎴? 鍒犻櫎 %d 鏉¤褰? 鑺傜渷 %.2f KB", delta_count, delta_size/1024)
    return delta_count


def parse_arguments():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description="Malody rankings crawler")
    _ = parser.add_argument('--all', action='store_true',
                            help='Crawl leaderboard and player pages, including leaderboard players into queue')
    _ = parser.add_argument('--leaderboard-only', action='store_true',
                            help='Only crawl leaderboard, skip all player-profile crawling')
    _ = parser.add_argument('--players-only', action='store_true',
                            help='Only crawl player profiles from players.txt, skip leaderboard')
    _ = parser.add_argument('--no-player-crawl', action='store_true',
                            help='Disable default player-profile crawl')
    _ = parser.add_argument('--migrate-db', action='store_true',
                            help='Run database migration tasks')
    _ = parser.add_argument('--once', action='store_true',
                            help='Run one crawl cycle and exit')
    _ = parser.add_argument('--save-excel', action='store_true',
                            help='Save output to Excel files')
    _ = parser.add_argument('--push-to-git', action='store_true',
                            help='Push updated data to Git repository')
    _ = parser.add_argument('--optimize-db', action='store_true',
                            help='Optimize database and exit')
    _ = parser.add_argument('--mm-sync', action='store_true',
                            help='Run MM ranking and MMR sync in normal cycle')
    _ = parser.add_argument('--mm-only', action='store_true',
                            help='Run only MM ranking and MMR sync')
    _ = parser.add_argument('--mm-limit', type=int, default=DEFAULT_MM_LIMIT,
                            help=f'Max rows per mode for MM sync (default {DEFAULT_MM_LIMIT})')
    _ = parser.add_argument('--skip-mm-ranking', action='store_true',
                            help='Skip MM ranking crawl and only run MMR sync')
    _ = parser.add_argument('--skip-mmr', action='store_true',
                            help='Skip MMR sync and only run MM ranking crawl')

    _ = parser.add_argument('--ranking-source', choices=['page', 'newapi'], default='page',
                            help='Ranking source: page=legacy HTML parse, newapi=/ranking/global')
    _ = parser.add_argument('--ranking-limit', type=int, default=DEFAULT_MM_LIMIT,
                            help=f'Max rows per mode when ranking-source=newapi (default {DEFAULT_MM_LIMIT})')

    return parser.parse_args()

def run_players_only():
    """鍙繍琛岀帺瀹朵富椤电埇鍙栵紙浠呮秷璐归厤缃枃浠朵腑鐨勭帺瀹讹紝涓嶆秹鍙婃帓琛屾锛?"""
    init_database()
    config_players = load_player_config()
    if config_players:
        add_players_to_queue(config_players)
        run_player_crawler()
    else:
        logger.info("娌℃湁閰嶇疆鐜╁锛岃烦杩囩埇鍙?")
    DatabaseManager().close_connection()


def main():
    args = parse_arguments()

    if args.migrate_db:
        migrate_database()
        return

    init_database()

    # 棰勫姞杞介厤缃枃浠剁帺瀹跺苟鍔犲叆闃熷垪锛堜粎鐢ㄤ簬棣栨杩愯鍓嶇殑闃熷垪濉厖锛屽悗缁懆鏈熶細閲嶆柊鍔犺浇锛?
    if not args.mm_only:
        config_players = load_player_config()
        if config_players:
            add_players_to_queue(config_players)
            logger.info("Loaded %d players from config file.", len(config_players))

    if args.optimize_db:
        optimize_database()
        DatabaseManager().close_connection()
        return

    if args.players_only:
        run_players_only()
        return

    if args.mm_only:
        mm_limit = max(1, int(args.mm_limit or DEFAULT_MM_LIMIT))
        logger.info(
            "Run mm-only cycle: mm_limit=%d skip_mm_ranking=%s skip_mmr=%s",
            mm_limit,
            args.skip_mm_ranking,
            args.skip_mmr,
        )
        try:
            run_mm_sync_cycle(
                mm_limit=mm_limit,
                include_mm_ranking=not args.skip_mm_ranking,
                include_mmr=not args.skip_mmr,
            )
        finally:
            DatabaseManager().close_connection()
        return

    # 纭畾鏄惁鐖彇鐜╁锛堥粯璁ゅ紑鍚紝闄ら潪琚?--no-player-crawl 鎴?--leaderboard-only 鍏抽棴锛?
    crawl_players = True
    if args.no_player_crawl or args.leaderboard_only:
        crawl_players = False

    # 纭畾鏄惁灏嗘帓琛屾鐜╁鍔犲叆闃熷垪锛堥粯璁や笉鍔犲叆锛屽彧鏈?--all 寮€鍚級
    crawl_leaderboard_players = args.all

    # 纭畾鏄惁淇濆瓨Excel鍜屾帹閫丟it
    save_excel = args.save_excel
    push_to_git = args.push_to_git
    mm_sync = args.mm_sync
    mm_limit = max(1, int(args.mm_limit or DEFAULT_MM_LIMIT))
    ranking_source = args.ranking_source
    ranking_limit = max(1, int(args.ranking_limit or DEFAULT_MM_LIMIT))

    if args.once:
        if args.leaderboard_only:
            crawl_players = False
            crawl_leaderboard_players = False
        if args.all:
            crawl_players = True
            crawl_leaderboard_players = True
            if args.no_player_crawl:
                logger.warning("鍚屾椂鎸囧畾浜?--all 鍜?--no-player-crawl锛屼互 --all 涓哄噯锛屽皢鐖彇鐜╁")
                crawl_players = True
                crawl_leaderboard_players = True

        run_crawler_cycle(
            crawl_players=crawl_players,
            crawl_leaderboard_players=crawl_leaderboard_players,
            save_excel=save_excel,
            push_to_git=push_to_git,
            mm_sync=mm_sync,
            mm_limit=mm_limit,
            skip_mm_ranking=args.skip_mm_ranking,
            skip_mmr=args.skip_mmr,
            ranking_source=ranking_source,
            ranking_limit=ranking_limit,
        )
        DatabaseManager().close_connection()
        return

    try:
        while True:
            with stop_lock:
                if stop_requested:
                    logger.info("绋嬪簭琚粓姝?")
                    break

            try:
                run_crawler_cycle(
                    crawl_players=crawl_players,
                    crawl_leaderboard_players=crawl_leaderboard_players,
                    save_excel=save_excel,
                    push_to_git=push_to_git,
                    mm_sync=mm_sync,
                    mm_limit=mm_limit,
                    skip_mm_ranking=args.skip_mm_ranking,
                    skip_mmr=args.skip_mmr,
                    ranking_source=ranking_source,
                    ranking_limit=ranking_limit,
                )
            except Exception as e:
                logger.exception("涓诲惊鐜彂鐢熸湭澶勭悊寮傚父")

            logger.info("绛夊緟30鍒嗛挓鍚庨噸鍚?..")

            for i in range(30):
                with stop_lock:
                    if stop_requested:
                        logger.info("绋嬪簭琚粓姝?")
                        break
                time.sleep(60)
                gc.collect()
    finally:
        DatabaseManager().close_connection()


if __name__ == "__main__":
    main()



