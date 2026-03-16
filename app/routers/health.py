from fastapi import APIRouter
from pydantic import BaseModel

from ..config import settings
from ..services.comfy_client import ComfyClient

router = APIRouter(prefix="/health", tags=["health"])


class ComfyHealthOut(BaseModel):
    comfyui_url: str
    healthy: bool


@router.get("/comfyui", response_model=ComfyHealthOut)
async def comfyui_health():
    async with ComfyClient() as client:
        healthy = await client.health()
    return ComfyHealthOut(comfyui_url=settings.comfy_base_url, healthy=healthy)
