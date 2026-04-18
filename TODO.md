# TODO

## P0 - API 功能缺口（对齐现有 stats 能力）

- [x] 新增玩家对比趋势接口（对应 `stats compare`）
  - [x] 设计接口：`GET /analytics/player-compare`
  - [x] 参数支持：`players`（逗号分隔）、`mode`、`days`
  - [x] 返回：各玩家时序排名 + 汇总统计
  - [x] 验收：与 `do_compare` 输出数据一致（不含图片）

- [x] 新增谱面综合统计接口（对应 `stats stb_summary`）
  - [x] 设计接口：`GET /charts/summary`
  - [x] 参数支持：`mode`、`creators`、`difficulties`、`statuses`、`time_range`、`detail_level`
  - [x] 返回：总谱面数、歌曲数、创作者数、状态分布、热度/难度统计、Top 创作者
  - [x] 验收：与 `do_stb_summary` 指标一致

- [x] 新增谱面数据质量检查接口（对应 `stats stb_quality`）
  - [x] 设计接口：`GET /charts/quality`
  - [x] 返回：空创作者、空难度、空更新时间、孤儿谱面、负热度、负打赏等比例
  - [x] 验收：与 `do_stb_quality` 指标一致

- [x] 新增稳定者排行榜接口（对应 `stats stb_top_stabilizers`）
  - [x] 设计接口：`GET /charts/stabilizers/top`
  - [x] 参数支持：`mode`、`limit`
  - [x] 返回：稳定者、stable_count、avg_heat、max_heat、first_stable、last_stable
  - [x] 验收：与 `do_stb_top_stabilizers` 数据一致

- [x] 新增创作者详情与趋势接口（对应 `stats stb_creator_details/stb_creator_trends`）
  - [x] 设计接口：`GET /charts/creators/{name}/details`
  - [x] 设计接口：`GET /charts/creators/{name}/trends`
  - [x] 参数支持：`mode`、`status`、`period`、`since`、`last`
  - [x] 验收：与 `do_stb_creator_details` / `do_stb_creator_trends` 数据一致

- [x] 实现歌曲详情接口（README 标注待实现）
  - [x] 设计接口：`GET /page-parser/song/{sid}`
  - [x] 返回：歌曲基础信息 + 关联谱面列表 + 统计摘要
  - [x] 验收：README 与实际路由一致

## P1 - stats 自身“声明了但未完整实现”的功能

- [x] 完整实现 `export` 子类型
  - [x] 支持 `top`
  - [x] 支持 `history`
  - [x] 支持 `song`
  - [x] 支持 `profile`
  - [x] 当前 `chart` 逻辑补齐 `limit/players/time_range` 参数
  - [x] 验收：`help export` 中列出的类型均可用

- [x] 梳理并修复 `update` 能力映射
  - [x] `--player` 对齐 `player_profile_crawler.py` 可用参数（uid/uid-range/from-db 等）
  - [x] `--stb` 对齐 `stb_crawler.py` 可用参数（source/cid/sid/retry/resume 等）
  - [x] 增加参数校验与错误提示
  - [x] 验收：stats 调用外部脚本参数与脚本实际支持一致

## P1 - 爬虫控制 API 与爬虫脚本能力对齐

- [x] 扩展 `POST /crawler/run` 参数模型
  - [x] leaderboard：保留 `once`
  - [x] player：支持 `uid`、`uid_range`、`from_db`、`max_workers`、`days_since_update` 等
  - [x] stb：支持 `source`、`cid_crawl`、`sid_crawl`、`retry_failed`、`start/end`、`resume` 等
  - [x] 使用白名单映射，禁止任意参数透传
  - [x] 验收：不改脚本情况下可通过 API 驱动主要爬虫流程

- [x] 扩展 `GET /crawler/status`
  - [x] 统一返回 `cid/sid/sid_backwards/global` 进度核心字段
  - [x] 增加最近更新时间与失败队列摘要
  - [x] 验收：可直接用于前端监控面板

## P2 - 文档与契约一致性

- [x] 同步 README 的 API 列表与参数说明
  - [x] 移除或标注未实现接口
  - [x] 新增已补齐接口示例
  - [x] 验收：`README`、`/docs`、实际路由三者一致

- [x] 为新增 API 补充示例请求/响应
  - [x] `docs` 中包含典型参数组合
  - [x] 明确分页/limit 默认值和上限

## P2 - 测试与回归保障

- [x] 为新增服务层补最小单元测试
  - [x] summary/quality/stabilizers/creator trends

- [x] 为关键路由补集成测试
  - [x] `/charts/summary`
  - [x] `/charts/quality`
  - [x] `/charts/stabilizers/top`
  - [x] `/page-parser/song/{sid}`
  - [x] `/crawler/run` 参数校验

- [x] 增加“stats vs API 一致性”校验脚本
  - [x] 同一筛选条件下对比关键指标差异
  - [x] 输出差异报告
