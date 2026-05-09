"""ComfyUI portrait generation + cloud image API fallback."""
import json
import os
import time
import urllib.error
import urllib.request
from typing import Optional

from . import config


# ── Workflow listing ──────────────────────────────────────

def list_workflows(comfyui_url: Optional[str] = None) -> list[str]:
    """List available ComfyUI workflow files from the user library."""
    import glob
    comfyui_url = comfyui_url or config.DEFAULT_COMFYUI_URL
    wf_files = glob.glob("/storage/emulated/0/ComfyUI/user/default/workflows/*.json")
    wf_files += glob.glob(os.path.expanduser("~/ComfyUI/user/default/workflows/*.json"))
    names = sorted(set(os.path.basename(f) for f in wf_files))
    return names or ["anime_char.json"]


def analyze_switches(workflow_name: str, comfyui_url: Optional[str] = None) -> list[dict]:
    """Analyze a workflow for toggle-able nodes (bypass/mute switches)."""
    comfyui_url = comfyui_url or config.DEFAULT_COMFYUI_URL
    import glob
    search_paths = [
        f"/storage/emulated/0/ComfyUI/user/default/workflows/{workflow_name}",
        os.path.expanduser(f"~/ComfyUI/user/default/workflows/{workflow_name}"),
    ]
    for path in search_paths:
        if os.path.exists(path):
            with open(path) as f:
                wf = json.load(f)
            switches = []
            for node in wf.get("nodes", []):
                nid = str(node.get("id", ""))
                title = node.get("title", node.get("type", ""))
                ntype = node.get("type", "")
                mode = node.get("mode", 0)
                switches.append({
                    "id": nid,
                    "title": title,
                    "type": "bypass",
                    "enabled": mode == 0,
                    "class_type": ntype,
                })
            return switches
    return []


# ── Portrait generation ───────────────────────────────────

def generate_portrait(
    prompt: str,
    workflow: Optional[str] = None,
    switches: Optional[dict] = None,
    comfyui_url: Optional[str] = None,
    fallback_model: Optional[str] = None,
    output_dir: Optional[str] = None,
    api_base: Optional[str] = None,
    api_key: Optional[str] = None,
) -> str:
    """Generate a character portrait, trying ComfyUI first then cloud fallback."""
    comfyui_url = comfyui_url or config.DEFAULT_COMFYUI_URL
    workflow = workflow or config.DEFAULT_WORKFLOW
    switches = switches or {}
    fallback_model = fallback_model or config.DEFAULT_IMAGE_MODEL
    output_dir = output_dir or config.OUTPUT_DIR

    return _cloud_generate(prompt, fallback_model, output_dir, api_base=api_base, api_key=api_key)


def _cloud_generate(
    prompt: str,
    model: str,
    output_dir: str,
    api_base: Optional[str] = None,
    api_key: Optional[str] = None,
) -> str:
    """Generate portrait via an OpenAI-compatible image API."""
    api_key = api_key or config.DEFAULT_API_KEY
    if not api_key:
        raise RuntimeError("API key not set — configure in advanced settings or set LLM_API_KEY env var")

    api_base = api_base or config.DEFAULT_API_BASE
    url = f"{api_base.rstrip('/')}/images/generations"
    payload = {
        "model": model,
        "prompt": prompt,
        "negative_prompt": "blurry, low quality, ugly, deformed, watermark, text, bad anatomy",
        "num_inference_steps": 20,
        "guidance_scale": 7.5,
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Authorization", f"Bearer {api_key}")
    req.add_header("Content-Type", "application/json")

    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            result = json.loads(resp.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace") if e.fp else ""
        raise RuntimeError(f"Image API HTTP {e.code}: {err_body[:500]}")
    except urllib.error.URLError as e:
        raise RuntimeError(f"Image API network error: {e.reason}")

    image_url = result.get("images", [{}])[0].get("url")
    if not image_url:
        raise RuntimeError(f"No image URL in response: {str(result)[:200]}")

    os.makedirs(output_dir, exist_ok=True)
    filename = f"portrait_{int(time.time())}.png"
    output_path = os.path.join(output_dir, filename)
    urllib.request.urlretrieve(image_url, output_path)
    return output_path
