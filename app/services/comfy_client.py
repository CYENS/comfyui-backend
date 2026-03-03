import httpx
from typing import Any
from ..config import settings


class ComfyClient:
    def __init__(self, base_url: str | None = None):
        self.base_url = base_url or settings.comfy_base_url
        self.client = httpx.AsyncClient(base_url=self.base_url, timeout=None)

    async def submit_prompt(self, prompt: dict, extra_data: dict) -> dict:
        payload = {"prompt": prompt, "extra_data": extra_data}
        resp = await self.client.post("/prompt", json=payload)
        resp.raise_for_status()
        return resp.json()

    async def get_job(self, prompt_id: str) -> dict:
        resp = await self.client.get(f"/api/jobs/{prompt_id}")
        resp.raise_for_status()
        return resp.json()

    async def close(self):
        await self.client.aclose()
