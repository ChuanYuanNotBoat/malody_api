import time
from typing import Any, Dict, Optional

import requests


class OfficialAPIService:
    """Client wrapper for https://api.mugzone.net/api."""

    API_BASE = "https://api.mugzone.net/api"

    def __init__(self) -> None:
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Origin": "https://malody.mugzone.net",
                "Referer": "https://malody.mugzone.net/",
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
                "Accept": "application/json, text/plain, */*",
            }
        )
        self._auth: Optional[Dict[str, Any]] = None
        self._auth_ts: float = 0.0

    def _auth_expired(self) -> bool:
        # Guest token is refreshed proactively every 30 minutes.
        return (time.time() - self._auth_ts) > 1800

    def ensure_guest_auth(self, force_refresh: bool = False) -> Dict[str, Any]:
        if (not force_refresh) and self._auth and (not self._auth_expired()):
            return self._auth

        resp = self.session.get(f"{self.API_BASE}/web/auth/guest/wt", timeout=30)
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") != 0:
            raise RuntimeError(f"guest auth failed: code={data.get('code')}")

        key = data.get("key") or data.get("token")
        uid = data.get("uid")
        store_key = data.get("storeKey") or data.get("tokenStore") or key
        if not key or uid is None:
            raise RuntimeError("guest auth missing key/uid")

        self._auth = {
            "uid": int(uid),
            "key": key,
            "store_key": store_key,
            "raw": data,
        }
        self._auth_ts = time.time()
        return self._auth

    def _request(
        self,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        use_store_key: bool = False,
        refresh_on_auth_fail: bool = True,
    ) -> Dict[str, Any]:
        auth = self.ensure_guest_auth()
        req_params = dict(params or {})
        req_params["uid"] = auth["uid"]
        req_params["key"] = auth["store_key"] if use_store_key else auth["key"]

        resp = self.session.get(f"{self.API_BASE}{path}", params=req_params, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        if data.get("code") == -1000 and refresh_on_auth_fail:
            self.ensure_guest_auth(force_refresh=True)
            return self._request(
                path=path,
                params=params,
                use_store_key=use_store_key,
                refresh_on_auth_fail=False,
            )

        return data

    def guest_auth(self) -> Dict[str, Any]:
        return self.ensure_guest_auth(force_refresh=True)["raw"]

    def store_list(self, from_index: int = 0, list_type: int = 0) -> Dict[str, Any]:
        return self._request(
            "/store/list2",
            params={"from": from_index, "type": list_type},
            use_store_key=True,
        )

    def song_info(self, sid: int) -> Dict[str, Any]:
        return self._request("/community/song/info", params={"sid": sid})

    def song_charts(self, sid: int) -> Dict[str, Any]:
        return self._request("/community/song/charts", params={"sid": sid})

    def chart_info(self, cid: int) -> Dict[str, Any]:
        return self._request("/community/chart/info", params={"cid": cid})

    def ranking_list(self, cid: int, from_index: int = 0) -> Dict[str, Any]:
        return self._request("/ranking/list", params={"cid": cid, "from": from_index})

    def ranking_global(self, mode: int, from_index: int = 0) -> Dict[str, Any]:
        return self._request("/ranking/global", params={"mode": mode, "from": from_index})

    def player_search(self, keyword: str, from_index: int = 0) -> Dict[str, Any]:
        return self._request("/player/search", params={"keyword": keyword, "from": from_index})

