"""
Unit tests for app.services.model_requirements

Covers:
  - validate_download_url: allowed and blocked cases
  - extract_from_api_json: standard nodes, node-reference skipping, unknown nodes
  - extract_from_ui_json:
      - top-level nodes with widgets_values (old format)
      - properties.models metadata (new format) with URL extraction
      - subgraph nodes (definitions.subgraphs[*].nodes)
      - deduplication across subgraphs
      - real-world z-image-turbo template workflow shape
"""
import pytest

from app.services.model_requirements import (
    extract_from_api_json,
    extract_from_ui_json,
    validate_download_url,
)


# ── validate_download_url ──────────────────────────────────────────────────────

class TestValidateDownloadUrl:
    def test_huggingface_safetensors_ok(self):
        url = "https://huggingface.co/black-forest-labs/FLUX.1-schnell/resolve/main/flux1-schnell.safetensors"
        assert validate_download_url(url) == url

    def test_civitai_safetensors_ok(self):
        url = "https://civitai.com/api/download/models/12345"
        # civitai download URLs end in a model ID, not a filename — but our
        # check looks for extension in the path; civitai URLs pass domain check
        # even without extension because the path check uses "in path"
        # Actually they don't have extensions — let's use a real-shaped one
        url = "https://civitai.com/api/download/models/12345/v1-5-pruned.safetensors"
        assert validate_download_url(url) == url

    def test_huggingface_gguf_ok(self):
        url = "https://huggingface.co/org/repo/resolve/main/model.gguf"
        assert validate_download_url(url) == url

    def test_huggingface_pt_ok(self):
        url = "https://huggingface.co/org/repo/resolve/main/model.pt"
        assert validate_download_url(url) == url

    def test_http_rejected(self):
        with pytest.raises(ValueError, match="HTTPS"):
            validate_download_url("http://huggingface.co/org/repo/resolve/main/model.safetensors")

    def test_unknown_domain_rejected(self):
        with pytest.raises(ValueError, match="allowed list"):
            validate_download_url("https://example.com/model.safetensors")

    def test_wrong_extension_rejected(self):
        with pytest.raises(ValueError, match="allowed extensions"):
            validate_download_url("https://huggingface.co/org/repo/resolve/main/model.bin")

    def test_www_prefix_stripped(self):
        url = "https://www.huggingface.co/org/repo/resolve/main/model.safetensors"
        # www. prefix should be stripped before domain check
        assert validate_download_url(url) == url


# ── extract_from_api_json ──────────────────────────────────────────────────────

class TestExtractFromApiJson:
    def test_checkpoint_loader_simple(self):
        prompt = {
            "4": {
                "class_type": "CheckpointLoaderSimple",
                "inputs": {"ckpt_name": "v1-5-pruned.safetensors"},
            }
        }
        reqs = extract_from_api_json(prompt)
        assert len(reqs) == 1
        r = reqs[0]
        assert r["node_id"] == "4"
        assert r["node_type"] == "CheckpointLoaderSimple"
        assert r["field"] == "ckpt_name"
        assert r["model_name"] == "v1-5-pruned.safetensors"
        assert r["folder"] == "checkpoints"
        assert r["model_type"] == "checkpoint"
        assert r["download_url"] is None

    def test_unet_loader(self):
        prompt = {
            "11": {
                "class_type": "UNETLoader",
                "inputs": {"unet_name": "flux1-schnell.safetensors", "weight_dtype": "fp8_e4m3fn"},
            }
        }
        reqs = extract_from_api_json(prompt)
        assert len(reqs) == 1
        assert reqs[0]["folder"] == "diffusion_models"
        assert reqs[0]["model_type"] == "unet"

    def test_vae_loader(self):
        prompt = {
            "5": {
                "class_type": "VAELoader",
                "inputs": {"vae_name": "ae.safetensors"},
            }
        }
        reqs = extract_from_api_json(prompt)
        assert len(reqs) == 1
        assert reqs[0]["folder"] == "vae"
        assert reqs[0]["model_name"] == "ae.safetensors"

    def test_dual_clip_loader_two_fields(self):
        prompt = {
            "20": {
                "class_type": "DualCLIPLoader",
                "inputs": {
                    "clip_name1": "clip_l.safetensors",
                    "clip_name2": "t5xxl_fp16.safetensors",
                    "type": "flux",
                },
            }
        }
        reqs = extract_from_api_json(prompt)
        assert len(reqs) == 2
        names = {r["model_name"] for r in reqs}
        assert names == {"clip_l.safetensors", "t5xxl_fp16.safetensors"}
        assert all(r["folder"] == "text_encoders" for r in reqs)

    def test_lora_loader(self):
        prompt = {
            "7": {
                "class_type": "LoraLoader",
                "inputs": {"lora_name": "detail_tweaker.safetensors", "strength_model": 0.8},
            }
        }
        reqs = extract_from_api_json(prompt)
        assert len(reqs) == 1
        assert reqs[0]["folder"] == "loras"
        assert reqs[0]["model_type"] == "lora"

    def test_node_reference_skipped(self):
        """Values that are node-reference arrays like ["4", 0] must be ignored."""
        prompt = {
            "4": {
                "class_type": "CheckpointLoaderSimple",
                "inputs": {"ckpt_name": ["3", 0]},  # wired from another node
            }
        }
        assert extract_from_api_json(prompt) == []

    def test_unknown_node_type_ignored(self):
        prompt = {
            "1": {"class_type": "KSampler", "inputs": {"seed": 42, "steps": 20}},
            "2": {"class_type": "CLIPTextEncode", "inputs": {"text": "a cat"}},
        }
        assert extract_from_api_json(prompt) == []

    def test_multiple_loaders(self):
        prompt = {
            "4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "model.safetensors"}},
            "5": {"class_type": "VAELoader", "inputs": {"vae_name": "vae.safetensors"}},
            "6": {"class_type": "KSampler", "inputs": {"seed": 0}},
        }
        reqs = extract_from_api_json(prompt)
        assert len(reqs) == 2

    def test_non_dict_node_skipped(self):
        prompt = {"meta": "not a node", "4": {"class_type": "VAELoader", "inputs": {"vae_name": "x.safetensors"}}}
        reqs = extract_from_api_json(prompt)
        assert len(reqs) == 1

    def test_empty_prompt(self):
        assert extract_from_api_json({}) == []


# ── extract_from_ui_json ──────────────────────────────────────────────────────

class TestExtractFromUiJson:

    # ── widgets_values (old format) ──────────────────────────

    def test_top_level_node_widgets_values(self):
        ui = {
            "nodes": [
                {
                    "id": 4,
                    "type": "CheckpointLoaderSimple",
                    "widgets_values": ["v1-5-pruned.safetensors"],
                }
            ]
        }
        reqs = extract_from_ui_json(ui)
        assert len(reqs) == 1
        assert reqs[0]["model_name"] == "v1-5-pruned.safetensors"
        assert reqs[0]["folder"] == "checkpoints"
        assert reqs[0]["download_url"] is None

    def test_dual_clip_loader_widgets_values(self):
        ui = {
            "nodes": [
                {
                    "id": 10,
                    "type": "DualCLIPLoader",
                    "widgets_values": ["clip_l.safetensors", "t5xxl_fp16.safetensors", "flux"],
                }
            ]
        }
        reqs = extract_from_ui_json(ui)
        assert len(reqs) == 2
        names = {r["model_name"] for r in reqs}
        assert names == {"clip_l.safetensors", "t5xxl_fp16.safetensors"}

    def test_non_loader_top_level_node_ignored(self):
        ui = {
            "nodes": [
                {"id": 9, "type": "SaveImage", "widgets_values": ["output"]},
                {"id": 35, "type": "MarkdownNote", "widgets_values": ["## Notes"]},
            ]
        }
        assert extract_from_ui_json(ui) == []

    # ── properties.models (new format) ───────────────────────

    def test_properties_models_extracted(self):
        ui = {
            "nodes": [
                {
                    "id": 28,
                    "type": "UNETLoader",
                    "properties": {
                        "models": [
                            {
                                "name": "flux1-schnell.safetensors",
                                "url": "https://huggingface.co/black-forest-labs/FLUX.1-schnell/resolve/main/flux1-schnell.safetensors",
                                "directory": "diffusion_models",
                            }
                        ]
                    },
                    "widgets_values": ["flux1-schnell.safetensors", "default"],
                }
            ]
        }
        reqs = extract_from_ui_json(ui)
        assert len(reqs) == 1
        r = reqs[0]
        assert r["model_name"] == "flux1-schnell.safetensors"
        assert r["folder"] == "diffusion_models"
        assert r["model_type"] == "unet"
        assert "huggingface.co" in r["download_url"]

    def test_properties_models_invalid_url_discarded(self):
        ui = {
            "nodes": [
                {
                    "id": 5,
                    "type": "VAELoader",
                    "properties": {
                        "models": [{"name": "ae.safetensors", "url": "http://evil.com/ae.safetensors", "directory": "vae"}]
                    },
                    "widgets_values": ["ae.safetensors"],
                }
            ]
        }
        reqs = extract_from_ui_json(ui)
        assert len(reqs) == 1
        assert reqs[0]["download_url"] is None  # bad URL silently dropped

    def test_properties_models_no_url_field(self):
        ui = {
            "nodes": [
                {
                    "id": 5,
                    "type": "VAELoader",
                    "properties": {
                        "models": [{"name": "ae.safetensors", "directory": "vae"}]
                    },
                    "widgets_values": ["ae.safetensors"],
                }
            ]
        }
        reqs = extract_from_ui_json(ui)
        assert len(reqs) == 1
        assert reqs[0]["download_url"] is None

    # ── subgraph nodes ────────────────────────────────────────

    def test_subgraph_nodes_found(self):
        """Loader nodes inside definitions.subgraphs must be extracted."""
        ui = {
            "nodes": [
                {"id": 57, "type": "some-subgraph-uuid", "widgets_values": []},
            ],
            "definitions": {
                "subgraphs": [
                    {
                        "id": "some-subgraph-uuid",
                        "nodes": [
                            {
                                "id": 28,
                                "type": "UNETLoader",
                                "properties": {
                                    "models": [
                                        {
                                            "name": "model.safetensors",
                                            "url": "https://huggingface.co/org/repo/resolve/main/model.safetensors",
                                            "directory": "diffusion_models",
                                        }
                                    ]
                                },
                                "widgets_values": ["model.safetensors", "default"],
                            }
                        ],
                    }
                ]
            },
        }
        reqs = extract_from_ui_json(ui)
        assert len(reqs) == 1
        assert reqs[0]["model_name"] == "model.safetensors"
        assert reqs[0]["folder"] == "diffusion_models"

    def test_subgraph_deduplication(self):
        """Same model appearing in both top-level and subgraph must appear once."""
        node = {
            "id": 4,
            "type": "VAELoader",
            "properties": {
                "models": [{"name": "ae.safetensors", "url": "https://huggingface.co/org/r/resolve/main/ae.safetensors", "directory": "vae"}]
            },
            "widgets_values": ["ae.safetensors"],
        }
        ui = {
            "nodes": [dict(node)],
            "definitions": {"subgraphs": [{"nodes": [dict(node)]}]},
        }
        reqs = extract_from_ui_json(ui)
        assert len(reqs) == 1

    def test_no_nodes_key(self):
        assert extract_from_ui_json({}) == []

    def test_empty_nodes(self):
        assert extract_from_ui_json({"nodes": []}) == []

    # ── real-world: z-image-turbo template ───────────────────

    def test_z_image_turbo_template(self):
        """
        Mirrors the actual z-image-turbo ComfyUI template workflow where all
        loader nodes (UNETLoader, CLIPLoader, VAELoader) live inside a subgraph
        and carry properties.models metadata with HuggingFace URLs.
        """
        ui = {
            "nodes": [
                {"id": 35, "type": "MarkdownNote", "widgets_values": ["## notes"]},
                {"id": 9, "type": "SaveImage", "widgets_values": ["output"]},
                {
                    "id": 57,
                    "type": "f2fdebf6-dfaf-43b6-9eb2-7f70613cfdc1",
                    "widgets_values": ["prompt", 1024, 1024, 8, None, None,
                                       "z_image_turbo_bf16.safetensors",
                                       "qwen_3_4b.safetensors",
                                       "ae.safetensors"],
                },
            ],
            "definitions": {
                "subgraphs": [
                    {
                        "id": "f2fdebf6-dfaf-43b6-9eb2-7f70613cfdc1",
                        "nodes": [
                            {
                                "id": 30, "type": "CLIPLoader",
                                "properties": {"models": [{
                                    "name": "qwen_3_4b.safetensors",
                                    "url": "https://huggingface.co/Comfy-Org/z_image_turbo/resolve/main/split_files/text_encoders/qwen_3_4b.safetensors",
                                    "directory": "text_encoders",
                                }]},
                                "widgets_values": ["qwen_3_4b.safetensors", "lumina2", "default"],
                            },
                            {
                                "id": 29, "type": "VAELoader",
                                "properties": {"models": [{
                                    "name": "ae.safetensors",
                                    "url": "https://huggingface.co/Comfy-Org/z_image_turbo/resolve/main/split_files/vae/ae.safetensors",
                                    "directory": "vae",
                                }]},
                                "widgets_values": ["ae.safetensors"],
                            },
                            {
                                "id": 28, "type": "UNETLoader",
                                "properties": {"models": [{
                                    "name": "z_image_turbo_bf16.safetensors",
                                    "url": "https://huggingface.co/Comfy-Org/z_image_turbo/resolve/main/split_files/diffusion_models/z_image_turbo_bf16.safetensors",
                                    "directory": "diffusion_models",
                                }]},
                                "widgets_values": ["z_image_turbo_bf16.safetensors", "default"],
                            },
                            {"id": 27, "type": "CLIPTextEncode", "widgets_values": ["prompt"]},
                            {"id": 33, "type": "ConditioningZeroOut", "widgets_values": []},
                            {"id": 13, "type": "EmptySD3LatentImage", "widgets_values": [1024, 1024, 1]},
                            {"id": 11, "type": "ModelSamplingAuraFlow", "widgets_values": [3]},
                            {"id": 3, "type": "KSampler", "widgets_values": [0, "randomize", 8, 1, "res_multistep", "simple", 1]},
                            {"id": 8, "type": "VAEDecode", "widgets_values": []},
                        ],
                    }
                ]
            },
        }

        reqs = extract_from_ui_json(ui)

        assert len(reqs) == 3

        by_folder = {r["folder"]: r for r in reqs}
        assert set(by_folder.keys()) == {"text_encoders", "vae", "diffusion_models"}

        assert by_folder["text_encoders"]["model_name"] == "qwen_3_4b.safetensors"
        assert by_folder["text_encoders"]["model_type"] == "clip"
        assert "text_encoders/qwen_3_4b.safetensors" in by_folder["text_encoders"]["download_url"]

        assert by_folder["vae"]["model_name"] == "ae.safetensors"
        assert by_folder["vae"]["model_type"] == "vae"
        assert "vae/ae.safetensors" in by_folder["vae"]["download_url"]

        assert by_folder["diffusion_models"]["model_name"] == "z_image_turbo_bf16.safetensors"
        assert by_folder["diffusion_models"]["model_type"] == "unet"
        assert "diffusion_models/z_image_turbo_bf16.safetensors" in by_folder["diffusion_models"]["download_url"]
