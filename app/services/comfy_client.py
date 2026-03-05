import httpx
from typing import Any
from ..config import settings


class ComfyClient:
    def __init__(self, base_url: str | None = None):
        self.base_url = base_url or settings.comfy_base_url
        self.client = httpx.AsyncClient(base_url=self.base_url, timeout=None)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self.close()

    async def submit_prompt(self, prompt: dict, extra_data: dict) -> dict:
        payload = {"prompt": prompt, "extra_data": extra_data}
        resp = await self.client.post("/prompt", json=payload)
        resp.raise_for_status()
        return resp.json()

    async def get_job(self, prompt_id: str) -> dict:
        resp = await self.client.get(f"/api/jobs/{prompt_id}")
        resp.raise_for_status()
        return resp.json()

    async def download_view(
        self, filename: str, subfolder: str | None = None, type_: str = "output"
    ) -> tuple[bytes, str | None]:
        params: dict[str, Any] = {"filename": filename, "type": type_}
        if subfolder:
            params["subfolder"] = subfolder
        resp = await self.client.get("/view", params=params)
        resp.raise_for_status()
        return resp.content, resp.headers.get("content-type")

    async def close(self):
        await self.client.aclose()
