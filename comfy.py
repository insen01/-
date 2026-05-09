"""ComfyUI local generation + cloud image API."""
import json
import os
import random
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
    for d in [
        "/storage/emulated/0/ComfyUI/user/default/workflows",
        os.path.expanduser("~/ComfyUI/user/default/workflows"),
        os.path.expanduser("~/comfyui/user/default/workflows"),
        "/sdcard/ComfyUI/user/default/workflows",
    ]:
        paths += glob.glob(os.path.join(d, "*.json"))
    return sorted(set(paths))


def list_workflows(comfyui_url: Optional[str] = None) -> list[str]:
    """List available ComfyUI workflow filenames."""
    names = sorted(set(os.path.basename(p) for p in _search_workflow_files()))
    return names or ["anime_char.json"]


# ── Portrait generation ───────────────────────────────────

def generate_portrait(
    prompt: str,
    mode: str = "cloud",
    comfyui_url: Optional[str] = None,
    checkpoint: Optional[str] = None,
    cloud_model: Optional[str] = None,
    image_api_base: Optional[str] = None,
    image_api_key: Optional[str] = None,
    output_dir: Optional[str] = None,
) -> str:
    """Generate a character portrait.

    Args:
        prompt: Image generation prompt.
        mode: "comfyui" or "cloud".
        comfyui_url: ComfyUI API base URL.
        checkpoint: Checkpoint model name for ComfyUI.
        cloud_model: Model ID for cloud image API.
        image_api_base: Cloud image API base URL.
        image_api_key: Cloud image API key.
        output_dir: Output directory for the generated PNG.

    Returns:
        Absolute path to the generated PNG.
    """
    output_dir = output_dir or config.OUTPUT_DIR

    if mode == "comfyui":
        return _comfyui_generate(
            prompt,
            comfyui_url=comfyui_url or config.DEFAULT_COMFYUI_URL,
            checkpoint=checkpoint or config.COMFYUI_CHECKPOINT,
            output_dir=output_dir,
        )
    else:
        return _cloud_generate(
            prompt,
            model=cloud_model or config.DEFAULT_IMAGE_MODEL,
            output_dir=output_dir,
            image_api_base=image_api_base,
            image_api_key=image_api_key,
        )


# ── ComfyUI generation ────────────────────────────────────

def _comfyui_generate(
    prompt: str,
    comfyui_url: str,
    checkpoint: str,
    output_dir: str,
    width: int = 512,
    height: int = 768,
    steps: int = 20,
    cfg: float = 7.0,
) -> str:
    """Generate a portrait using a local ComfyUI instance."""
    base = comfyui_url.rstrip("/")

    # 1) Verify ComfyUI is reachable
    try:
        req = urllib.request.Request(f"{base}/system_stats", method="GET")
        with urllib.request.urlopen(req, timeout=10) as resp:
            sys_info = json.loads(resp.read().decode("utf-8", errors="replace"))
    except urllib.error.URLError as e:
        raise RuntimeError(f"ComfyUI 不可达 ({base}): {e.reason}")
    except Exception as e:
        raise RuntimeError(f"ComfyUI 连接异常 ({base}): {e}")

    # 2) Select best available checkpoint if the default isn't found
    checkpoint = _resolve_checkpoint(base, checkpoint)

    # 3) Build workflow
    seed = random.randint(1, 2**31 - 1)
    workflow = {
        "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": checkpoint}},
        "2": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": ["1", 1]}},
        "3": {"class_type": "CLIPTextEncode", "inputs": {
            "text": "blurry, low quality, ugly, deformed, watermark, text, bad anatomy, extra fingers",
            "clip": ["1", 1],
        }},
        "4": {"class_type": "EmptyLatentImage", "inputs": {"width": width, "height": height, "batch_size": 1}},
        "5": {"class_type": "KSampler", "inputs": {
            "seed": seed, "steps": steps, "cfg": cfg,
            "sampler_name": "euler_ancestral", "scheduler": "normal", "denoise": 1.0,
            "model": ["1", 0], "positive": ["2", 0], "negative": ["3", 0], "latent_image": ["4", 0],
        }},
        "6": {"class_type": "VAEDecode", "inputs": {"samples": ["5", 0], "vae": ["1", 2]}},
        "7": {"class_type": "SaveImage", "inputs": {"filename_prefix": "charcard", "images": ["6", 0]}},
    }

    # 4) Submit job
    payload = {"prompt": workflow}
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(f"{base}/prompt", data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace") if e.fp else ""
        raise RuntimeError(f"ComfyUI 提交失败 HTTP {e.code}: {err_body[:300]}")
    except urllib.error.URLError as e:
        raise RuntimeError(f"ComfyUI 提交网络错误: {e.reason}")

    prompt_id = result.get("prompt_id")
    if not prompt_id:
        node_errors = result.get("node_errors", {})
        if node_errors:
            raise RuntimeError(f"ComfyUI 工作流节点错误: {json.dumps(node_errors)[:300]}")
        raise RuntimeError(f"ComfyUI 未返回 prompt_id: {json.dumps(result)[:200]}")

    # 5) Poll for completion
    deadline = time.time() + config.COMFYUI_TIMEOUT
    last_progress = -1
    while time.time() < deadline:
        time.sleep(2)
        try:
            req = urllib.request.Request(f"{base}/history/{prompt_id}", method="GET")
            with urllib.request.urlopen(req, timeout=10) as resp:
                history = json.loads(resp.read().decode("utf-8", errors="replace"))
        except Exception as e:
            raise RuntimeError(f"ComfyUI 轮询失败: {e}")

        entry = history.get(prompt_id)
        if not entry:
            continue

        # Check status
        status = entry.get("status", {})
        if status.get("completed") is False and status.get("status_str") == "error":
            raise RuntimeError(f"ComfyUI 生成出错: {json.dumps(status)[:300]}")

        if "outputs" in entry:
            # Generation complete — extract filename
            outputs = entry["outputs"]
            for node_id, node_output in outputs.items():
                images = node_output.get("images", [])
                if images:
                    img_info = images[0]
                    filename = img_info["filename"]
                    subfolder = img_info.get("subfolder", "")
                    img_type = img_info.get("type", "output")

                    # 6) Download the image
                    return _download_comfyui_image(
                        base, filename, subfolder, img_type, output_dir,
                    )

    raise RuntimeError(f"ComfyUI 生成超时 (>{config.COMFYUI_TIMEOUT}s)")


def _resolve_checkpoint(base: str, preferred: str) -> str:
    """Check if preferred checkpoint exists; if not, pick the first available."""
    try:
        req = urllib.request.Request(f"{base}/object_info/CheckpointLoaderSimple", method="GET")
        with urllib.request.urlopen(req, timeout=5) as resp:
            info = json.loads(resp.read().decode("utf-8", errors="replace"))
        ckpt_list = info.get("CheckpointLoaderSimple", {}).get("input", {}).get("required", {}).get("ckpt_name", [])
        available = [x for x in ckpt_list if isinstance(x, str)]
        if preferred in available:
            return preferred
        if available:
            return available[0]
    except Exception:
        pass
    return preferred


def _download_comfyui_image(base: str, filename: str, subfolder: str, img_type: str, output_dir: str) -> str:
    """Download a generated image from ComfyUI."""
    from urllib.parse import quote, urlencode
    params = urlencode({"filename": filename, "subfolder": subfolder, "type": img_type})
    url = f"{base}/view?{params}"
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, f"comfyui_{int(time.time())}.png")
    try:
        urllib.request.urlretrieve(url, output_path)
    except Exception as e:
        raise RuntimeError(f"下载 ComfyUI 图片失败: {e}\n图片 URL: {url}")
    return output_path


# ── Cloud generation ──────────────────────────────────────

def _cloud_generate(
    prompt: str,
    model: str,
    output_dir: str,
    image_api_base: Optional[str] = None,
    image_api_key: Optional[str] = None,
) -> str:
    """Generate portrait via an OpenAI-compatible image API."""
    image_api_key = image_api_key or config.DEFAULT_IMAGE_API_KEY
    if not image_api_key:
        raise RuntimeError("未设置图片 API Key — 请在高级设置中填写或设置 IMAGE_API_KEY 环境变量")

    image_base = image_api_base or config.DEFAULT_IMAGE_API_BASE
    url = f"{image_base.rstrip('/')}/images/generations"

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
    req.add_header("Authorization", f"Bearer {image_api_key}")
    req.add_header("Content-Type", "application/json")

    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            raw_body = resp.read().decode("utf-8", errors="replace")
            result = json.loads(raw_body)
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace") if e.fp else ""
        raise RuntimeError(f"图片 API HTTP {e.code} ← {url}\n响应: {err_body[:300]}")
    except urllib.error.URLError as e:
        raise RuntimeError(f"图片 API 网络不可达: {e.reason}\n请求地址: {url}")
    except json.JSONDecodeError:
        raise RuntimeError(f"图片 API 返回非 JSON 响应\n请求地址: {url}\n原始内容: {raw_body[:300]}")

    image_url = result.get("images", [{}])[0].get("url")
    if not image_url:
        if "error" in result:
            raise RuntimeError(f"图片 API 错误: {result['error']}\n请求地址: {url}")
        raise RuntimeError(f"图片 API 未返回图片 URL\n请求地址: {url}\n响应: {json.dumps(result)[:300]}")

    os.makedirs(output_dir, exist_ok=True)
    filename = f"portrait_{int(time.time())}.png"
    output_path = os.path.join(output_dir, filename)
    try:
        urllib.request.urlretrieve(image_url, output_path)
    except Exception as e:
        raise RuntimeError(f"下载图片失败: {e}\n图片 URL: {image_url[:200]}")
    return output_path
