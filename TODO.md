# TODO（按子系统分块）

## 0. 全局状态
- 分支：`main`
- 总体结论：核心 API/CLI/测试链路已打通，可用性从“功能缺口期”进入“稳定化期”
- 当前主要风险：官网结构/API 变动导致爬虫数据源阶段性不可用（已知问题，后续单独修复）

---

## 1. API 网关层（FastAPI Routers）
### 状态：已完成主功能，进入稳定化
- [x] `/analytics/player-compare`
- [x] `/charts/summary`
- [x] `/charts/quality`
- [x] `/charts/stabilizers/top`
- [x] `/charts/creators/{creator_name}/details`
- [x] `/charts/creators/{creator_name}/trends`
- [x] `/page-parser/song/{sid}`
- [x] `/crawler/run` 参数扩展与白名单映射
- [x] `/crawler/status` 统一状态摘要结构

### 下一步
- [x] 为 `player-compare` 和 `creator*` 增加更多边界参数校验（空值、异常区间）
- [ ] 统一错误码语义（400/404/422）并补充错误响应文档

---

## 2. Stats CLI 子系统（`malody_stats.py`）
### 状态：已完成能力补齐
- [x] `export` 全类型落地：`top/history/chart/song/profile`
- [x] `export chart` 支持 `limit/players/time_range`
- [x] `update` 参数映射与脚本能力对齐（player/stb）
- [x] 参数白名单与校验提示

### 下一步
- [ ] 将 `do_update` / `do_export` 的参数解析从手写逻辑升级为统一解析器（可维护性）
- [ ] 增加 CLI 自测样例（命令输入 -> 预期 SQL/脚本命令）

---

## 3. 爬虫控制与调度子系统（API -> 脚本）
### 状态：可用，关键路径已修复
- [x] `/crawler/run` 支持 player/stb 扩展参数
- [x] 参数透传已改为白名单映射
- [x] `/crawler/status` 汇总 `cid/sid/sid_backwards/global`
- [x] 修复脚本路径解析层级（`routers/crawler.py`）

### 已知外部依赖问题（暂缓）
- [ ] 官网变动导致 API 爬取不可用（待数据源适配）
- [ ] 其他数据源半瘫痪（待逐源恢复）

### 下一步
- [ ] 为官网改版建立“解析器版本层”（兼容旧/新 DOM）
- [ ] 为数据源失败增加熔断/降级标记，避免误判“系统正常但无数据”

---

## 4. 服务层与一致性校验子系统
### 状态：已建立最小保障
- [x] `ChartService` 关键方法测试覆盖：summary/quality/stabilizers/creator trends
- [x] 路由集成测试覆盖关键新增端点
- [x] 新增一致性脚本：`scripts/check_stats_api_consistency.py`

### 下一步
- [ ] 将一致性脚本接入定时任务（每日/每次发布后）
- [ ] 差异报告增加阈值规则（仅超阈值告警）

---

## 5. 文档与契约子系统
### 状态：已同步
- [x] README 已更新新增 API 列表
- [x] README 已补充典型请求示例
- [x] TODO 与当前实现状态一致

### 下一步
- [ ] 在 README 增加“爬虫外部依赖异常”运行说明与故障排查
- [ ] 增加 API 示例响应片段（不仅请求示例）

---

## 6. 回归与发布清单（合并前/发布前）
- [x] `python -m unittest discover -s tests -p "test_*.py" -v`
- [x] `python -m compileall -q`（关键文件）
- [ ] （可选）本地启动 API 后执行一次 `scripts/check_stats_api_consistency.py`
- [x] 合并到 `main`
- [ ] 打标签/发布说明（按需）
