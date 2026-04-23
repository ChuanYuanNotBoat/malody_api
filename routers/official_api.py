from datetime import datetime

from fastapi import APIRouter, Depends, Query

from malody_api.core.models import APIResponse
from malody_api.core.security import require_api_key
from malody_api.core.services.official_api_service import OfficialAPIService

router = APIRouter(
    prefix="/official-api",
    tags=["official-api"],
    dependencies=[Depends(require_api_key)],
)

official_api_service = OfficialAPIService()


@router.get("/auth/guest", response_model=APIResponse)
async def guest_auth():
    data = official_api_service.guest_auth()
    return APIResponse(success=True, data=data, timestamp=datetime.now())


@router.get("/store/list", response_model=APIResponse)
async def store_list(
    from_index: int = Query(0, ge=0, alias="from"),
    list_type: int = Query(0, ge=0, alias="type"),
):
    data = official_api_service.store_list(from_index=from_index, list_type=list_type)
    return APIResponse(success=True, data=data, timestamp=datetime.now())


@router.get("/song/{sid}", response_model=APIResponse)
async def song_info(sid: int):
    data = official_api_service.song_info(sid=sid)
    return APIResponse(success=True, data=data, timestamp=datetime.now())


@router.get("/song/{sid}/charts", response_model=APIResponse)
async def song_charts(sid: int):
    data = official_api_service.song_charts(sid=sid)
    return APIResponse(success=True, data=data, timestamp=datetime.now())


@router.get("/chart/{cid}", response_model=APIResponse)
async def chart_info(cid: int):
    data = official_api_service.chart_info(cid=cid)
    return APIResponse(success=True, data=data, timestamp=datetime.now())


@router.get("/ranking/list", response_model=APIResponse)
async def ranking_list(
    cid: int = Query(..., ge=1),
    from_index: int = Query(0, ge=0, alias="from"),
):
    data = official_api_service.ranking_list(cid=cid, from_index=from_index)
    return APIResponse(success=True, data=data, timestamp=datetime.now())


@router.get("/ranking/global", response_model=APIResponse)
async def ranking_global(
    mode: int = Query(..., ge=0, le=9),
    from_index: int = Query(0, ge=0, alias="from"),
):
    data = official_api_service.ranking_global(mode=mode, from_index=from_index)
    return APIResponse(success=True, data=data, timestamp=datetime.now())


@router.get("/player/search", response_model=APIResponse)
async def player_search(
    keyword: str = Query(..., min_length=1),
    from_index: int = Query(0, ge=0, alias="from"),
):
    data = official_api_service.player_search(keyword=keyword, from_index=from_index)
    return APIResponse(success=True, data=data, timestamp=datetime.now())

