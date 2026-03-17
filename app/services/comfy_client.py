from typing import Any

import httpx

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

    async def interrupt_prompt(self, prompt_id: str) -> None:
        resp = await self.client.post("/api/interrupt", json={"prompt_id": prompt_id})
        resp.raise_for_status()

    async def download_view(
        self, filename: str, subfolder: str | None = None, type_: str = "output"
    ) -> tuple[bytes, str | None]:
        params: dict[str, Any] = {"filename": filename, "type": type_}
        if subfolder:
            params["subfolder"] = subfolder
        resp = await self.client.get("/view", params=params)
        resp.raise_for_status()
        return resp.content, resp.headers.get("content-type")

    async def get_folder_models(self, folder: str) -> list[str]:
        """
        Return the list of model filenames available in a ComfyUI model folder.
        Calls GET /models/{folder} on the ComfyUI instance.
        Returns an empty list if the folder is unknown to ComfyUI.
        """
        resp = await self.client.get(f"/models/{folder}")
        if resp.status_code == 404:
            return []
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, list):
            return [str(item) for item in data]
        return []

    async def check_models_available(self, requirements: list[dict]) -> list[dict]:
        """
        Enrich each requirement dict with an ``available`` bool by checking
        ComfyUI's model folder listings.

        Each requirement dict must have at least ``folder`` and ``model_name`` keys.
        Returns a new list of dicts with the same keys plus ``available``.

        Raises ``httpx.ConnectError`` / ``httpx.HTTPStatusError`` if ComfyUI is
        unreachable — callers should catch and convert to HTTP 503.
        """
        # Fetch each unique folder once
        folder_cache: dict[str, set[str]] = {}
        for req in requirements:
            folder = req["folder"]
            if folder not in folder_cache:
                names = await self.get_folder_models(folder)
                folder_cache[folder] = set(names)

        enriched = []
        for req in requirements:
            available_names = folder_cache.get(req["folder"], set())
            model_name = req["model_name"]
            # Match exactly, or by basename for models stored in sub-folders
            available = model_name in available_names or any(
                n.endswith("/" + model_name) or n.endswith("\\" + model_name)
                for n in available_names
            )
            enriched.append({**req, "available": available})
        return enriched

    async def upload_image(self, content: bytes, filename: str, content_type: str) -> str:
        """Upload an image to ComfyUI and return the stored filename."""
        files = {"image": (filename, content, content_type)}
        resp = await self.client.post("/upload/image", files=files, timeout=30.0)
        resp.raise_for_status()
        return resp.json()["name"]

    async def health(self) -> bool:
        """Return True if ComfyUI is reachable and responsive."""
        try:
            resp = await self.client.get("/system_stats", timeout=5.0)
            return resp.status_code == 200
        except httpx.HTTPError:
            return False

    async def close(self):
        await self.client.aclose()
