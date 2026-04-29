from datetime import datetime
from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, Depends, HTTPException

from malody_api.core.models import APIResponse
from malody_api.core.security import require_api_key
from malody_api.core.services.plugin_service import plugin_service

router = APIRouter(prefix="/plugins", tags=["plugins"], dependencies=[Depends(require_api_key)])


@router.get("", response_model=APIResponse)
async def list_plugins():
    return APIResponse(success=True, data={"plugins": plugin_service.list_plugins()}, timestamp=datetime.now())


@router.get("/{plugin_id}", response_model=APIResponse)
async def get_plugin(plugin_id: str):
    try:
        plugin = plugin_service.get_plugin(plugin_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="plugin not found")
    return APIResponse(success=True, data=plugin, timestamp=datetime.now())


@router.post("/{plugin_id}/run", response_model=APIResponse)
async def run_plugin(
    plugin_id: str,
    payload: Optional[Dict[str, Any]] = Body(default=None),
):
    payload = payload or {}
    config = payload.get("config", {})
    run_payload = payload.get("payload", {})
    try:
        result = plugin_service.run_plugin(plugin_id, config=config, payload=run_payload)
    except KeyError:
        raise HTTPException(status_code=404, detail="plugin not found")
    except Exception as e:
        return APIResponse(success=False, error=str(e), timestamp=datetime.now())
    return APIResponse(success=True, data=result, timestamp=datetime.now())
