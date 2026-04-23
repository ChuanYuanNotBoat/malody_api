# Mugzone Server API Research (Phase 1)

Last updated: 2026-04-23

## Scope
- Target site: `https://m.mugzone.net`
- Goal: identify web APIs used by the server-rendered pages and confirm which are useful for crawler/data sync.
- Domain note (confirmed on 2026-04-23):
  - `https://malody.mugzone.net/` currently serves SPA shell pages.
  - Requests targeting the old homepage path on `m.mugzone.net` may be redirected to `malody.mugzone.net`.
  - Server endpoints used by crawler (`/page/chart/filter`, `/chart/{cid}`, `/song/{sid}`) are on `https://m.mugzone.net`.
- Evidence sources:
  - Page/module snapshots under `tmp/research/`
  - Runtime validation with authenticated cookies (`cookies.local.json`)

## Confirmed Working Endpoints

### 1) Chart filter/search
- Endpoint: `POST /page/chart/filter`
- Discovered from: `module/chartlist/index` (`tmp/research/module_module_chartlist_index.js`)
- Request payload (example):
  - `status`, `count`, `page`, `mode`, `key`, `creator`
  - `csrfmiddlewaretoken` (recommended when authenticated)
- Headers (recommended):
  - `X-Requested-With: XMLHttpRequest`
  - `X-CSRFToken: <csrftoken>`
  - `Referer: https://m.mugzone.net/`
- Response (current):
  - Content-Type is `text/html; charset=utf-8` but body is JSON
  - Shape: `{"code":0,"data":{"total":<int>,"list":[...],"page":<int>}}`
- Status:
  - Integrated into `stb_crawler.py` with response normalization

### 2) Chart detail page (HTML parsing path)
- Endpoint: `GET /chart/{cid}`
- Used for extracting chart/song metadata from rendered HTML.
- Status:
  - Working in crawler; used after chart IDs are discovered via filter API.

## Discovered Endpoints (Not Fully Validated Yet)

### Auth/account
- `POST /accounts/login`
- `POST /accounts/register`
- `POST /accounts/forget`
- `POST /accounts/change_email`
- `POST /accounts/invite/active`
- `GET /accounts/msg/unread` (returns `{"code":0}` in current probe)
- Sources:
  - `tmp/research/module_module_account_index.js`
  - `tmp/research/logs_static_js_util.js`

### Wiki/page ops (likely privileged/mutating)
- `POST /page/page_operate`
- `POST /page/delete`
- `GET/POST /page/backup`
- `GET /wiki/get_lang?key=...&lang=...`
- `GET /wiki/edit?key=...`
- `GET /wiki/meta?key=...`
- Sources:
  - `tmp/research/module_module_wiki_index.js`

### Score-related
- `GET /score/{cid}` with params `html=1&from=...&judge=...`
- `POST /score/score_operation` (mutating)
- Sources:
  - `tmp/research/module_module_wiki_index.js`

## Current Constraints
- `/page/latest` currently behaves as login-gated in crawler context; not reliable as a source of fresh chart IDs.
- `/index` is now SPA shell and no longer exposes old `newMap` markup.
- Some endpoints return JSON with non-JSON content-type (`text/html`), so parser logic must not rely on content-type only.

## Safe Next Steps
1. Expand endpoint discovery by crawling more public pages and collecting additional `module/*` scripts.
2. Build a small probe matrix for read-only endpoints (status code, auth required, response schema).
3. Keep mutating endpoints (`/page/delete`, `/score/score_operation`, `/page/page_operate`) out of automation unless explicitly needed and isolated.

## Phase 2: New Official API (`api.mugzone.net`)

### Core finding
- New frontend bundle (`malody.mugzone.net/assets/index-*.js`) hardcodes:
  - `https://api.mugzone.net/api`
- The frontend auth flow is:
  1. `GET /web/auth/guest/wt` to get guest `key/token`, `uid`, `storeKey/tokenStore`
  2. Append `uid` + `key` as query params on API calls
  3. Use `storeKey` for `/store/*` endpoints

### Confirmed read endpoints (with guest token)
- `GET /community/song/info?sid=...`
- `GET /community/song/charts?sid=...`
- `GET /community/chart/info?cid=...`
- `GET /ranking/list?cid=...`
- `GET /ranking/global?mode=...&from=...`
- `GET /player/search?keyword=...`
- `GET /push/info/wt`
- `GET /store/list2?from=...&type=0` (requires store key)

### Response code behavior
- `code = 0`: success
- `code = -1000`: auth/token invalid or missing for that request shape

### Crawler integration status
- `stb_crawler.py` now contains a new source:
  - `crawl_from_new_api(...)`
- Data path:
  1. `/web/auth/guest/wt`
  2. `/store/list2` to get recent song IDs
  3. `/community/song/charts` for cids under each sid
  4. `/community/chart/info` + `/community/song/info`
  5. Save into existing DB schema
- CLI support:
  - `--source newapi`

### Quick verify command
- `python scripts/probe_new_mugzone_api.py`
