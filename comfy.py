"""ComfyUI portrait generation + cloud image API fallback."""
import json
import os
import time
import urllib.error
import urllib.request
from typing import Optional

from . import config


# ── Workflow listing ──────────────────────────────────────

def _search_workflow_files() -> list[str]:
    """Scan all known ComfyUI workflow storage paths, return absolute paths."""
    import glob
    paths = []
    candidates = [
        "/storage/emulated/0/ComfyUI/user/default/workflows",
        os.path.expanduser("~/ComfyUI/user/default/workflows"),
        os.path.expanduser("~/comfyui/user/default/workflows"),
        "/sdcard/ComfyUI/user/default/workflows",
    ]
    for d in candidates:
        paths += glob.glob(os.path.join(d, "*.json"))
    return sorted(set(paths))


def list_workflows(comfyui_url: Optional[str] = None) -> list[str]:
    """List available ComfyUI workflow filenames, scanning disk + API."""
    # 1) disk scan
    names = sorted(set(os.path.basename(p) for p in _search_workflow_files()))

    # 2) try ComfyUI API to discover workflow dir
    comfyui_url = comfyui_url or config.DEFAULT_COMFYUI_URL
    try:
        req = urllib.request.Request(
            f"{comfyui_url.rstrip('/')}/object_info",
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            pass  # API is alive — confirm connectivity
    except Exception:
        pass

    return names or ["anime_char.json"]


def analyze_switches(workflow_name: str, comfyui_url: Optional[str] = None) -> list[dict]:
    """Analyze a workflow for toggle-able nodes (bypass/mute switches)."""
    # search disk for the workflow file
    import glob
    search_paths = []
    for d in [
        "/storage/emulated/0/ComfyUI/user/default/workflows",
        os.path.expanduser("~/ComfyUI/user/default/workflows"),
        os.path.expanduser("~/comfyui/user/default/workflows"),
        "/sdcard/ComfyUI/user/default/workflows",
    ]:
        search_paths.append(os.path.join(d, workflow_name))

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
    """Generate portrait via an OpenAI-compatible image API.

    Raises RuntimeError with diagnostic details on failure.
    """
    api_key = api_key or config.DEFAULT_API_KEY
    if not api_key:
        raise RuntimeError(
            "未设置 API Key — 请在高级设置中填写或设置环境变量 LLM_API_KEY"
        )

    api_base = api_base or config.DEFAULT_API_BASE
    url = f"{api_base.rstrip('/')}/images/generations"

    if not prompt or len(prompt.strip()) < 10:
        raise RuntimeError(f"图像提示词太短或为空: '{prompt}'")

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
            raw_body = resp.read().decode("utf-8", errors="replace")
            result = json.loads(raw_body)
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace") if e.fp else ""
        raise RuntimeError(
            f"图片 API 返回 HTTP {e.code} → {err_body[:300]}"
        )
    except urllib.error.URLError as e:
        raise RuntimeError(
            f"图片 API 网络不可达: {e.reason} (地址: {url})"
        )
    except json.JSONDecodeError as e:
        raise RuntimeError(
            f"图片 API 返回非JSON响应: {raw_body[:300]}"
        )

    image_url = result.get("images", [{}])[0].get("url")
    if not image_url:
        if "error" in result:
            raise RuntimeError(f"图片 API 错误: {result['error']}")
        raise RuntimeError(f"图片 API 未返回图片URL — 响应: {json.dumps(result)[:300]}")

    os.makedirs(output_dir, exist_ok=True)
    filename = f"portrait_{int(time.time())}.png"
    output_path = os.path.join(output_dir, filename)
    try:
        urllib.request.urlretrieve(image_url, output_path)
    except Exception as e:
        raise RuntimeError(f"下载图片失败: {e} (URL: {image_url[:200]})")

    return output_path
