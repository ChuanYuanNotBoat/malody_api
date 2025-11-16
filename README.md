# Malody API

基于 Malody 游戏数据的 RESTful API 服务，提供玩家排名、谱面信息和排行榜数据查询功能。

## 项目简介

Malody API 是一个基于 FastAPI 构建的 Web 服务，提供对 Malody 游戏数据的结构化访问。该项目源自 [malody_rankings](https://github.com/ChuanYuanNotBoat/malody_rankings) 爬虫项目，将其数据通过标准化的 API 接口对外提供。

## 功能特性

### 核心功能
- **玩家数据查询** - 获取玩家排名、详细信息、历史记录
- **谱面数据查询** - 谱面统计、热门谱面、创作者信息
- **实时页面解析** - 解析 Malody 谱面页面，获取最新排行榜数据
- **高级查询系统** - 支持灵活的数据库查询和统计分析
- **数据可视化** - 趋势分析、模式比较、数据统计

### 技术特性
- RESTful API 设计，标准化 JSON 响应格式
- SQLite 数据库，支持复杂查询和数据分析
- 完整的错误处理和状态管理
- 请求频率限制和缓存机制
- 自动数据更新和爬虫集成

## 安装与运行

### 环境要求
- Python 3.8+
- SQLite 3

### 安装步骤

1. 克隆项目
```bash
git clone https://github.com/ChuanYuanNotBoat/malody_api.git
cd malody_api
```

2. 安装依赖
```bash
pip install -r requirements.txt
```

3. 准备数据库
确保 `malody_rankings.db` 数据库文件位于项目根目录。

4. 启动服务
```bash
python run.py
```

服务将在 http://localhost:8000 启动，API 文档可在 http://localhost:8000/docs 查看。

## API 文档

### 主要端点

#### 玩家数据
- `GET /players/top` - 获取顶级玩家排名
- `GET /players/{player_identifier}` - 获取玩家详细信息
- `GET /players/{player_name}/history` - 获取玩家历史排名
- `GET /players/search/{keyword}` - 搜索玩家

#### 谱面数据
- `GET /charts/stats` - 获取谱面统计信息
- `GET /charts/hot` - 获取热门谱面
- `GET /charts/recent` - 获取最近更新的谱面
- `GET /charts/stable-creators` - 获取 Stable 谱面创作者排行榜

#### 页面解析
- `GET /page-parser/chart/{cid}` - 解析谱面页面
- `GET /page-parser/chart/{cid}/ranking` - 仅获取谱面排行榜数据
- `GET /page-parser/song/search` - 搜索歌曲
- `GET /page-parser/song/{sid}` - 获取歌曲详细信息

#### 数据分析
- `GET /analytics/player-trends` - 分析玩家数据变化趋势
- `GET /analytics/chart-trends` - 获取谱面更新趋势
- `GET /analytics/mode-comparison` - 比较不同模式的谱面数据

#### 高级查询
- `POST /query/execute` - 执行高级数据库查询
- `GET /query/tables/{table_name}/schema` - 获取表结构信息
- `GET /query/database/stats` - 获取数据库统计信息

#### 系统管理
- `GET /system/health` - 健康检查
- `GET /system/database-info` - 获取数据库信息

### 响应格式

所有 API 均返回统一格式的 JSON 响应：

```json
{
    "success": true,
    "data": {...},
    "message": "操作成功",
    "error": null,
    "timestamp": "2024-01-01T00:00:00Z"
}
```

## 配置说明

### 环境变量

项目支持以下环境变量配置：

- `MALODY_DB_PATH` - 数据库文件路径（默认：malody_rankings.db）
- `MALODY_API_HOST` - 服务绑定地址（默认：0.0.0.0）
- `MALODY_API_PORT` - 服务端口（默认：8000）
- `MALODY_DEBUG` - 调试模式（默认：false）
- `MALODY_LOG_LEVEL` - 日志级别（默认：info）

### 数据库结构

项目使用 SQLite 数据库，主要包含以下表：

- `player_rankings` - 玩家排名数据
- `player_identity` - 玩家身份信息
- `player_aliases` - 玩家别名历史
- `charts` - 谱面信息
- `songs` - 歌曲信息
- `import_metadata` - 导入元数据

## 相关项目

- [malody_rankings](https://github.com/ChuanYuanNotBoat/malody_rankings) - 原始数据爬虫项目
- [Malody 官方网站](https://m.mugzone.net/) - 游戏官方网站

## 开发说明

### 项目结构

```
malody_api/
├── run.py                 # 主启动文件
├── stb_crawler.py         # STB 谱面爬虫
├── requirements.txt       # Python 依赖
├── malody_rankings.db    # SQLite 数据库
├── core/                  # 核心模块
│   ├── database.py       # 数据库连接
│   ├── models.py         # 数据模型
│   └── services/         # 业务服务
├── routers/              # API 路由
│   ├── players.py        # 玩家相关
│   ├── charts.py         # 谱面相关
│   ├── analytics.py      # 数据分析
│   ├── system.py         # 系统管理
│   ├── query.py          # 高级查询
│   └── page_parser.py    # 页面解析
└── utils/                # 工具类
    ├── query_builder.py  # 查询构建器
    ├── selector.py       # 数据选择器
    └── crawler_manager.py # 爬虫管理
```

### 扩展开发

要添加新的 API 端点：

1. 在 `routers/` 目录创建新的路由文件
2. 在 `routers/__init__.py` 中注册路由
3. 在 `core/services/` 中实现业务逻辑
4. 在 `core/models.py` 中定义数据模型

## 许可证

本项目采用 MIT 许可证。详见 LICENSE 文件。

## 贡献

欢迎提交 Issue 和 Pull Request 来改进这个项目。

## 联系方式

如有问题，请通过 GitHub Issues 提交。
