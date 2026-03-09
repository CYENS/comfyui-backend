"""
Utilities for extracting model requirements from ComfyUI workflow JSON.

Supports both API-format (dict keyed by node ID) and UI-format (nodes array)
workflow JSON. Extracted requirements can optionally include download URLs
scraped from node properties in the UI format.
"""
from urllib.parse import urlparse

# Each entry: (field_name, folder, model_type, ui_widget_index)
# ui_widget_index is the position of this field in widgets_values for UI-format JSON.
MODEL_LOADER_FIELDS: dict[str, list[tuple[str, str, str, int]]] = {
    "CheckpointLoaderSimple":    [("ckpt_name",         "checkpoints",      "checkpoint", 0)],
    "CheckpointLoader":          [("ckpt_name",         "checkpoints",      "checkpoint", 0)],
    "VAELoader":                 [("vae_name",           "vae",              "vae",        0)],
    "CLIPLoader":                [("clip_name",          "text_encoders",    "clip",       0)],
    "DualCLIPLoader":            [
        ("clip_name1", "text_encoders", "clip", 0),
        ("clip_name2", "text_encoders", "clip", 1),
    ],
    "LoraLoader":                [("lora_name",          "loras",            "lora",       0)],
    "LoraLoaderModelOnly":       [("lora_name",          "loras",            "lora",       0)],
    "ControlNetLoader":          [("control_net_name",   "controlnet",       "controlnet", 0)],
    "UNETLoader":                [("unet_name",          "diffusion_models", "unet",       0)],
    "ImageOnlyCheckpointLoader": [("ckpt_name",          "checkpoints",      "checkpoint", 0)],
}

_ALLOWED_DOMAINS = {"civitai.com", "huggingface.co"}
_ALLOWED_EXTENSIONS = {".safetensors", ".sft", ".gguf", ".pt"}


def validate_download_url(url: str) -> str:
    """
    Validate that a download URL is from an allowed domain with an allowed file
    extension. Returns the URL unchanged on success; raises ValueError otherwise.
    """
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise ValueError(f"Download URL must use HTTPS: {url!r}")
    domain = parsed.netloc.lower().lstrip("www.")
    if domain not in _ALLOWED_DOMAINS:
        raise ValueError(
            f"Download URL domain {domain!r} is not in the allowed list "
            f"({', '.join(sorted(_ALLOWED_DOMAINS))})"
        )
    path = parsed.path.lower()
    if not any(path.endswith(ext) or f"{ext}?" in path for ext in _ALLOWED_EXTENSIONS):
        raise ValueError(
            f"Download URL must point to a file with one of the allowed extensions: "
            f"{', '.join(sorted(_ALLOWED_EXTENSIONS))}"
        )
    return url


def extract_from_api_json(prompt_json: dict) -> list[dict]:
    """
    Extract model requirements from an API-format workflow JSON
    (dict keyed by node ID, each node has 'class_type' and 'inputs').

    Returns a list of dicts with keys:
      node_id, node_type, field, model_name, folder, model_type
    """
    results: list[dict] = []
    for node_id, node in prompt_json.items():
        if not isinstance(node, dict):
            continue
        node_type = node.get("class_type")
        if node_type not in MODEL_LOADER_FIELDS:
            continue
        inputs = node.get("inputs", {})
        for field_name, folder, model_type, _ in MODEL_LOADER_FIELDS[node_type]:
            value = inputs.get(field_name)
            # Skip node-reference arrays like ["4", 0]
            if not isinstance(value, str) or not value:
                continue
            results.append({
                "node_id": str(node_id),
                "node_type": node_type,
                "field": field_name,
                "model_name": value,
                "folder": folder,
                "model_type": model_type,
                "download_url": None,
            })
    return results


def extract_from_ui_json(ui_json: dict) -> list[dict]:
    """
    Extract model requirements from a ComfyUI UI-format workflow JSON.

    Searches both the top-level ``nodes`` array and any nodes nested inside
    ``definitions.subgraphs[*].nodes`` (used by modern ComfyUI template
    workflows that wrap loaders in subgraph nodes).

    URL extraction priority:
      1. ``properties.models`` array — standard ComfyUI metadata added by the
         model browser / template system: ``[{name, url, directory}, ...]``
      2. Positional ``widgets_values`` lookup (fallback for older workflows)

    Returns a list of dicts with keys:
      node_id, node_type, field, model_name, folder, model_type, download_url
    """
    # Collect all nodes: top-level + every subgraph definition
    all_nodes: list[dict] = list(ui_json.get("nodes") or [])
    for subgraph in (ui_json.get("definitions") or {}).get("subgraphs") or []:
        all_nodes.extend(subgraph.get("nodes") or [])

    results: list[dict] = []
    seen: set[tuple[str, str]] = set()  # (model_name, folder) — deduplicate across subgraphs

    for node in all_nodes:
        if not isinstance(node, dict):
            continue
        node_type = node.get("type")
        if node_type not in MODEL_LOADER_FIELDS:
            continue
        node_id = str(node.get("id", ""))
        props = node.get("properties") or {}
        field_defs = MODEL_LOADER_FIELDS[node_type]

        # ── Priority 1: properties.models (ComfyUI standard metadata) ──────
        models_meta = props.get("models") if isinstance(props, dict) else None
        if models_meta and isinstance(models_meta, list):
            for m in models_meta:
                if not isinstance(m, dict):
                    continue
                model_name = m.get("name")
                directory = m.get("directory")
                raw_url = m.get("url")
                if not model_name or not directory:
                    continue
                # Derive model_type from our mapping; fall back to the directory itself
                model_type = next(
                    (mt for _, f, mt, _ in field_defs if f == directory),
                    directory,
                )
                download_url = _safe_validate_url(raw_url)
                key = (model_name, directory)
                if key not in seen:
                    seen.add(key)
                    results.append({
                        "node_id": node_id,
                        "node_type": node_type,
                        "field": directory,
                        "model_name": model_name,
                        "folder": directory,
                        "model_type": model_type,
                        "download_url": download_url,
                    })
            continue  # don't also do widgets_values for this node

        # ── Priority 2: positional widgets_values (older workflow format) ───
        widgets = node.get("widgets_values") or []
        for field_name, folder, model_type, widget_idx in field_defs:
            if widget_idx >= len(widgets):
                continue
            value = widgets[widget_idx]
            if not isinstance(value, str) or not value:
                continue
            key = (value, folder)
            if key not in seen:
                seen.add(key)
                results.append({
                    "node_id": node_id,
                    "node_type": node_type,
                    "field": field_name,
                    "model_name": value,
                    "folder": folder,
                    "model_type": model_type,
                    "download_url": None,
                })

    return results


def _safe_validate_url(url: str | None) -> str | None:
    """Return validated URL or None if missing/invalid."""
    if not url:
        return None
    try:
        return validate_download_url(url)
    except ValueError:
        return None
