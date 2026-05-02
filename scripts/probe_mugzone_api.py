import argparse
import json
from pathlib import Path

import requests

BASE_URL = "https://m.mugzone.net"


def load_cookies(path: str) -> dict:
    p = Path(path)
    if not p.exists():
        return {}
    return json.loads(p.read_text(encoding="utf-8"))


def print_result(name: str, resp: requests.Response) -> None:
    text = (resp.text or "").replace("\n", " ")
    print(
        f"[{name}] status={resp.status_code} ct={resp.headers.get('content-type','')} "
        f"len={len(resp.text)} snippet={text[:160]}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Probe read-only Mugzone web APIs")
    parser.add_argument("--cookies-file", default="cookies.local.json")
    parser.add_argument("--cid", type=int, default=155861)
    parser.add_argument("--mode", type=int, default=0)
    parser.add_argument("--status", type=int, default=2)
    parser.add_argument("--count", type=int, default=5)
    args = parser.parse_args()

    cookies = load_cookies(args.cookies_file)
    csrf = cookies.get("csrftoken", "")

    session = requests.Session()
    session.cookies.update(cookies)
    session.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Referer": BASE_URL + "/",
            "Accept-Language": "en-US,en;q=0.5",
        }
    )

    # 1) Chart filter endpoint (primary source for crawler IDs)
    r = session.post(
        BASE_URL + "/page/chart/filter",
        data={
            "status": args.status,
            "count": args.count,
            "page": 0,
            "mode": args.mode,
            "key": "",
            "creator": "",
            "csrfmiddlewaretoken": csrf,
        },
        headers={
            "X-Requested-With": "XMLHttpRequest",
            "X-CSRFToken": csrf,
            "Origin": BASE_URL,
            "Referer": BASE_URL + "/",
        },
        timeout=30,
    )
    print_result("chart_filter", r)
    try:
        body = r.json()
        data = body.get("data", {}) if isinstance(body, dict) else {}
        if isinstance(data, dict):
            items = data.get("list") or []
            print(f"[chart_filter] total={data.get('total')} list_count={len(items)}")
            if items:
                print(f"[chart_filter] first_item_keys={sorted(items[0].keys())}")
    except Exception:
        pass

    # 2) Chart HTML page
    r = session.get(BASE_URL + f"/chart/{args.cid}", timeout=30)
    print_result("chart_html", r)

    # 3) Unread notifications probe
    r = session.get(BASE_URL + "/accounts/msg/unread", timeout=30)
    print_result("accounts_msg_unread", r)


if __name__ == "__main__":
    main()

