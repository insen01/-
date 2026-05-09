"""charcard configuration — all defaults in one place."""
import os

# ── API (generic OpenAI-compatible provider) ──────────────
DEFAULT_API_BASE = "https://api.siliconflow.cn/v1"
DEFAULT_API_KEY = os.environ.get("LLM_API_KEY", "") or os.environ.get("SILICONFLOW_API_KEY", "")

# ── LLM ──────────────────────────────────────────────────
DEFAULT_LLM_MODEL = "deepseek-ai/DeepSeek-V3"
LLM_TEMPERATURE = 0.8
LLM_MAX_TOKENS = 4096
LLM_TIMEOUT = 60

# ── ComfyUI (local) ──────────────────────────────────────
DEFAULT_COMFYUI_URL = "http://127.0.0.1:8188"
DEFAULT_WORKFLOW = "anime_char.json"
COMFYUI_TIMEOUT = 300  # 5 min generation timeout
COMFYUI_CHECKPOINT = "IL-novaAnimeXL_ilV180.safetensors"

# ── Image generation (cloud) ─────────────────────────────
DEFAULT_IMAGE_API_BASE = "https://api.siliconflow.cn/v1"
DEFAULT_IMAGE_API_KEY = os.environ.get("IMAGE_API_KEY", "") or os.environ.get("LLM_API_KEY", "") or os.environ.get("SILICONFLOW_API_KEY", "")
DEFAULT_IMAGE_MODEL = "Qwen/Qwen-Image"
DEFAULT_GENERATION_MODE = "cloud"  # "comfyui" or "cloud"

# ── Output ───────────────────────────────────────────────
OUTPUT_DIR = "/sdcard/Download/claude code/characters"

# ── Server ───────────────────────────────────────────────
SERVER_HOST = "0.0.0.0"
SERVER_PORT = 5000
