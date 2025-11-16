# malody_api/routers/__init__.py
from .players import router as players_router
from .charts import router as charts_router
from .analytics import router as analytics_router
from .system import router as system_router
from .query import router as query_router
from .page_parser import router as page_parser_router

__all__ = [
    "players_router", 
    "charts_router", 
    "analytics_router", 
    "system_router",
    "query_router",
    "page_parser_router"
]