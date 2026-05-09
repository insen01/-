"""charcard configuration — all defaults in one place."""
import os

# ── SiliconFlow ──────────────────────────────────────────
SILICONFLOW_API_KEY = os.environ.get("SILICONFLOW_API_KEY", "")
SILICONFLOW_BASE = "https://api.siliconflow.cn/v1"

# ── LLM ──────────────────────────────────────────────────
DEFAULT_LLM_MODEL = "deepseek-ai/DeepSeek-V3"
LLM_TEMPERATURE = 0.8
LLM_MAX_TOKENS = 4096
LLM_TIMEOUT = 60

# ── ComfyUI ──────────────────────────────────────────────
DEFAULT_COMFYUI_URL = "http://127.0.0.1:8188"
DEFAULT_WORKFLOW = "anime_char.json"
COMFYUI_TIMEOUT = 300  # 5 min before fallback

# ── Image generation (fallback) ──────────────────────────
DEFAULT_IMAGE_MODEL = "stabilityai/stable-diffusion-xl-base-1.0"

# ── Output ───────────────────────────────────────────────
OUTPUT_DIR = "/sdcard/Download/claude code/characters"

# ── Server ───────────────────────────────────────────────
SERVER_HOST = "0.0.0.0"
SERVER_PORT = 5000
