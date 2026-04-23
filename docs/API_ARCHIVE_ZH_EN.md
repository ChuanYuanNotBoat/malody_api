# Malody / Mugzone API Archive (ZH-EN)

Last updated: 2026-04-23

## 1. 目标 / Purpose
- 中文：存档当前可观测的新旧 API 入口、鉴权方式、已验证端点和风险边界，避免未来旧站下线后中断。
- EN: Archive currently observable legacy/new API entry points, auth flow, validated endpoints, and risk boundaries so crawler work can continue after legacy shutdown.

## 2. 域名现状 / Domain Status
- 中文：`https://malody.mugzone.net/` 为新官网前端（SPA）。旧主页访问会被重定向到新官网，但旧站部分 URL 仍可直接访问。
- EN: `https://malody.mugzone.net/` is the new SPA frontend. Legacy homepage redirects to the new site, while some legacy URLs are still directly accessible.

## 3. API 基础地址 / API Base URLs
- 新 API / New API: `https://api.mugzone.net/api`
- 旧站接口 / Legacy endpoints: `https://m.mugzone.net/...`

## 4. 鉴权流程 / Authentication Flow
### 4.1 新 API（推荐）/ New API (recommended)
1. `GET /web/auth/guest/wt`
2. 读取返回中的 `uid` 与 `key`（部分 store 接口还要 `storeKey`/`tokenStore`）
3. 后续请求带 `uid` + `key`（或对应 store key）

EN:
1. Call `GET /web/auth/guest/wt`
2. Read `uid` and `key` (`storeKey`/`tokenStore` for store endpoints)
3. Include `uid` + `key` (or store key) in subsequent requests

### 4.2 旧站接口 / Legacy m-site
- 常见需要 cookies（`sessionid`, `csrftoken`）
- 可能需要请求头 `X-CSRFToken` + `X-Requested-With`

EN:
- Often requires cookies (`sessionid`, `csrftoken`)
- Some endpoints expect `X-CSRFToken` and `X-Requested-With`

## 5. 响应码约定 / Response Code Notes
- `code = 0`: 成功 / success
- `code = -1000`: token 无效或缺失 / invalid or missing token

## 6. 已验证可读端点 / Verified Read Endpoints
### 6.1 新 API / New API (`api.mugzone.net`)
- `GET /web/auth/guest/wt`
- `GET /community/song/info?sid={sid}`
- `GET /community/song/charts?sid={sid}`
- `GET /community/chart/info?cid={cid}`
- `GET /ranking/list?cid={cid}`
- `GET /ranking/global?mode={mode}&from={offset}`
- `GET /player/search?keyword={keyword}`
- `GET /push/info/wt`
- `GET /store/list2?from={offset}&type=0` (store key required)

### 6.2 旧站 / Legacy (`m.mugzone.net`)
- `POST /page/chart/filter`（常见为 JSON 文本，但 content-type 可能是 `text/html`）
- `GET /chart/{cid}`
- `GET /song/{sid}`

EN:
- `POST /page/chart/filter` may return JSON payload with `text/html` content-type
- `GET /chart/{cid}` and `GET /song/{sid}` remain useful for HTML parsing fallback

## 7. 已知变化与风险 / Known Changes & Risks
- 中文：旧首页结构（如 `newMap`）已失效，不应再依赖首页解析。
- EN: Legacy homepage DOM structure (e.g. `newMap`) is obsolete and should not be relied on.
- 中文：旧站部分页面出现登录门槛与 403，稳定性下降。
- EN: Legacy pages increasingly hit auth gates/403 and are less stable.
- 中文：应优先迁移到 `api.mugzone.net` 数据链路。
- EN: Prefer migrating crawler pipelines to `api.mugzone.net`.

## 8. 新 API 当前可做什么 / What New API Can Do Now
- 获取最近歌曲与谱面列表 / Fetch recent songs and chart lists
- 通过 `sid/cid` 拉取歌曲与谱面详情 / Retrieve song/chart details by `sid/cid`
- 读取排行榜数据 / Read ranking data
- 关键词搜索玩家 / Search players by keyword

## 9. 不建议自动化的接口 / Endpoints Not Recommended for Automation
- 任何写操作或管理操作（删除、编辑、打分操作等）
- Any mutating/admin operations (delete/edit/score-operation, etc.)

## 10. 迁移建议 / Migration Recommendations
1. 中文：将核心采集链路改为新 API（guest token + refresh on `code=-1000`）。
   EN: Move core ingestion to New API with guest token and refresh-on-`code=-1000`.
2. 中文：保留旧站作为短期兜底，不再作为主路径。
   EN: Keep legacy site as temporary fallback only.
3. 中文：统一全局限速与并发上限，避免被判定异常流量。
   EN: Enforce global rate limits and worker caps to avoid abusive traffic signatures.

## 11. 相关脚本 / Related Scripts
- `scripts/probe_new_mugzone_api.py`
- `scripts/probe_mugzone_api.py`
- `stb_crawler.py` (`--source newapi`)
