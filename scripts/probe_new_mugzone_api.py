import requests


API_BASE = "https://api.mugzone.net/api"


def main() -> None:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json, text/plain, */*",
            "Origin": "https://malody.mugzone.net",
            "Referer": "https://malody.mugzone.net/",
        }
    )

    guest = session.get(f"{API_BASE}/web/auth/guest/wt", timeout=30).json()
    key = guest.get("key") or guest.get("token")
    uid = int(guest.get("uid", 1))
    store_key = guest.get("storeKey") or guest.get("tokenStore") or key
    print(f"[guest] code={guest.get('code')} uid={uid} key_ok={bool(key)}")

    common = {"uid": uid, "key": key}
    store_common = {"uid": uid, "key": store_key}

    probes = [
        ("/community/song/info", {"sid": 9434}, common),
        ("/community/song/charts", {"sid": 9434}, common),
        ("/community/chart/info", {"cid": 155861}, common),
        ("/ranking/list", {"cid": 155861, "from": 0}, common),
        ("/push/info/wt", {}, common),
        ("/store/list2", {"from": 0, "type": 0}, store_common),
    ]

    for path, params, auth in probes:
        r = session.get(f"{API_BASE}{path}", params={**auth, **params}, timeout=30)
        print(f"[{path}] status={r.status_code} body={r.text[:240].replace(chr(10), ' ')}")


if __name__ == "__main__":
    main()

