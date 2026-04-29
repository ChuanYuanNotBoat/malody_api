from .analytics import router as analytics_router
from .charts import router as charts_router
from .crawler import router as crawler_router
from .page_parser import router as page_parser_router
from .players import router as players_router
from .plugins import router as plugins_router
from .quality import router as quality_router
from .query import router as query_router
from .system import router as system_router

__all__ = [
    "players_router",
    "charts_router",
    "analytics_router",
    "system_router",
    "query_router",
    "page_parser_router",
    "crawler_router",
    "quality_router",
    "plugins_router",
]

