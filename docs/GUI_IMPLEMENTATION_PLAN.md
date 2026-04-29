# Malody 增强 GUI 实施计划（执行版）

## 1. 目标
- 使用 `Tauri 2 + React + TypeScript` 实现本地桌面 GUI（非浏览器）。
- 前后端分离：桌面端调用本地 FastAPI。
- V1 覆盖核心能力：总览、数据分析、爬虫控制、查询导出。
- 同步建设：插件扩展体系、数据库维护能力、数据质量治理。

## 2. 架构原则
- 桌面 App 自动拉起本地 API 子进程，固定 `127.0.0.1` 与专用端口。
- 首版双轨：默认依赖本机 Python；预留内置 Python 运行时打包入口。
- API 保持兼容优先，新增字段/接口不破坏已有调用。
- 数据质量采用“报告驱动”模式，不阻断主流程。

## 3. 后端改造清单
### 3.1 爬虫任务化
- 扩展 `POST /crawler/run`，返回 `data.task`（保留 `data.command`）。
- 新增：
  - `GET /crawler/tasks`
  - `GET /crawler/tasks/{task_id}`
  - `GET /crawler/tasks/{task_id}/log?tail=...`
- 任务记录字段：`task_id/status/pid/started_at/ended_at/exit_code/log_file/command`。

### 3.2 总览聚合接口
- 新增 `GET /analytics/dashboard-overview`，聚合：
  - 系统健康、数据库体积
  - 玩家 MM 统计摘要
  - 谱面统计摘要
  - 最近爬虫任务摘要

### 3.3 数据库维护中心
- 新增：
  - `GET /system/db/health`
  - `POST /system/db/maintain`
  - `GET /system/db/maintain/history`
- 维护动作首版支持：`ANALYZE`、`VACUUM`（手动触发 + 安全确认 + 审计日志）。

### 3.4 数据质量治理
- 新增：
  - `GET /quality/rules`
  - `POST /quality/check`
  - `GET /quality/report`
- 规则维度：完整性、一致性、时效性、异常值、跨表关联。
- 报告字段：`score/severity/issues/repair_suggestions/trend`。

### 3.5 插件体系（后端）
- 新增：
  - `GET /plugins`
  - `GET /plugins/{plugin_id}`
  - `POST /plugins/{plugin_id}/run`
- 插件最小清单字段：
  - `id/name/version/capabilities/config_schema/run_schema`
- 首版内置示例插件：
  - 分析类插件（overview 扩展）
  - 维护类插件（DB 维护建议）

## 4. 前端改造清单
- 新建 `desktop/` 工程（`Tauri 2 + React + TS`）。
- 页面：
  - 总览
  - 数据分析
  - 爬虫控制（含状态与日志）
  - 查询导出
  - 插件中心
  - 数据库维护
  - 数据质量
- 统一 API 客户端与轮询策略（任务状态、日志 tail、质量报告刷新）。

## 5. 测试与验收
### 5.1 后端测试
- 爬虫任务生命周期与兼容性。
- DB 维护安全护栏与审计记录。
- 质量规则评分稳定性与边界场景。
- 插件注册、发现、执行及异常隔离。

### 5.2 前端测试
- 动态插件卡片与参数表单渲染。
- 爬虫状态轮询与日志流展示。
- DB 维护确认流与结果反馈。
- 质量报告可视化展示。

### 5.3 验收场景
- 桌面启动自动拉起后端可用。
- 可发起爬虫任务并追踪状态与日志。
- 可执行一次安全维护并保留历史。
- 可生成质量评分报告并展示问题清单。
- 可运行至少一个分析插件与一个维护插件。

