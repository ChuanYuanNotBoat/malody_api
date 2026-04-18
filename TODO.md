# TODO

## P0 - API 功能缺口（对齐现有 stats 能力）

- [ ] 新增玩家对比趋势接口（对应 `stats compare`）
  - [ ] 设计接口：`GET /analytics/player-compare`
  - [ ] 参数支持：`players`（逗号分隔）、`mode`、`days`
  - [ ] 返回：各玩家时序排名 + 汇总统计
  - [ ] 验收：与 `do_compare` 输出数据一致（不含图片）

- [ ] 新增谱面综合统计接口（对应 `stats stb_summary`）
  - [ ] 设计接口：`GET /charts/summary`
  - [ ] 参数支持：`mode`、`creators`、`difficulties`、`statuses`、`time_range`、`detail_level`
  - [ ] 返回：总谱面数、歌曲数、创作者数、状态分布、热度/难度统计、Top 创作者
  - [ ] 验收：与 `do_stb_summary` 指标一致

- [ ] 新增谱面数据质量检查接口（对应 `stats stb_quality`）
  - [ ] 设计接口：`GET /charts/quality`
  - [ ] 返回：空创作者、空难度、空更新时间、孤儿谱面、负热度、负打赏等比例
  - [ ] 验收：与 `do_stb_quality` 指标一致

- [ ] 新增稳定者排行榜接口（对应 `stats stb_top_stabilizers`）
  - [ ] 设计接口：`GET /charts/stabilizers/top`
  - [ ] 参数支持：`mode`、`limit`
  - [ ] 返回：稳定者、stable_count、avg_heat、max_heat、first_stable、last_stable
  - [ ] 验收：与 `do_stb_top_stabilizers` 数据一致

- [ ] 新增创作者详情与趋势接口（对应 `stats stb_creator_details/stb_creator_trends`）
  - [ ] 设计接口：`GET /charts/creators/{name}/details`
  - [ ] 设计接口：`GET /charts/creators/{name}/trends`
  - [ ] 参数支持：`mode`、`status`、`period`、`since`、`last`
  - [ ] 验收：与 `do_stb_creator_details` / `do_stb_creator_trends` 数据一致

- [ ] 实现歌曲详情接口（README 标注待实现）
  - [ ] 设计接口：`GET /page-parser/song/{sid}`
  - [ ] 返回：歌曲基础信息 + 关联谱面列表 + 统计摘要
  - [ ] 验收：README 与实际路由一致

## P1 - stats 自身“声明了但未完整实现”的功能

- [ ] 完整实现 `export` 子类型
  - [ ] 支持 `top`
  - [ ] 支持 `history`
  - [ ] 支持 `song`
  - [ ] 支持 `profile`
  - [ ] 当前 `chart` 逻辑补齐 `limit/players/time_range` 参数
  - [ ] 验收：`help export` 中列出的类型均可用

- [ ] 梳理并修复 `update` 能力映射
  - [ ] `--player` 对齐 `player_profile_crawler.py` 可用参数（uid/uid-range/from-db 等）
  - [ ] `--stb` 对齐 `stb_crawler.py` 可用参数（source/cid/sid/retry/resume 等）
  - [ ] 增加参数校验与错误提示
  - [ ] 验收：stats 调用外部脚本参数与脚本实际支持一致

## P1 - 爬虫控制 API 与爬虫脚本能力对齐

- [ ] 扩展 `POST /crawler/run` 参数模型
  - [ ] leaderboard：保留 `once`
  - [ ] player：支持 `uid`、`uid_range`、`from_db`、`max_workers`、`days_since_update` 等
  - [ ] stb：支持 `source`、`cid_crawl`、`sid_crawl`、`retry_failed`、`start/end`、`resume` 等
  - [ ] 使用白名单映射，禁止任意参数透传
  - [ ] 验收：不改脚本情况下可通过 API 驱动主要爬虫流程

- [ ] 扩展 `GET /crawler/status`
  - [ ] 统一返回 `cid/sid/sid_backwards/global` 进度核心字段
  - [ ] 增加最近更新时间与失败队列摘要
  - [ ] 验收：可直接用于前端监控面板

## P2 - 文档与契约一致性

- [ ] 同步 README 的 API 列表与参数说明
  - [ ] 移除或标注未实现接口
  - [ ] 新增已补齐接口示例
  - [ ] 验收：`README`、`/docs`、实际路由三者一致

- [ ] 为新增 API 补充示例请求/响应
  - [ ] `docs` 中包含典型参数组合
  - [ ] 明确分页/limit 默认值和上限

## P2 - 测试与回归保障

- [ ] 为新增服务层补最小单元测试
  - [ ] summary/quality/stabilizers/creator trends

- [ ] 为关键路由补集成测试
  - [ ] `/charts/summary`
  - [ ] `/charts/quality`
  - [ ] `/charts/stabilizers/top`
  - [ ] `/page-parser/song/{sid}`
  - [ ] `/crawler/run` 参数校验

- [ ] 增加“stats vs API 一致性”校验脚本
  - [ ] 同一筛选条件下对比关键指标差异
  - [ ] 输出差异报告

