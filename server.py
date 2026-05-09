#!/usr/bin/env python3
"""Flask server for SillyTavern character card generator."""
import json
import os
import threading
import uuid
import sys

# Allow running as script: add parent dir to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flask import Flask, request, jsonify, send_file, render_template
from charcard.llm import generate_card
from charcard.card_builder import build
from charcard.png_assembler import embed, build_placeholder_card
from charcard.comfy import generate_portrait, _cloud_generate
from charcard import config

app = Flask(__name__)

# In-memory job store: {job_id: {...}}
_jobs = {}
_jobs_lock = threading.Lock()


# ── Routes ────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/config", methods=["GET"])
def get_config():
    """Return default config values for the frontend."""
    return jsonify({
        "api_base": config.DEFAULT_API_BASE,
        "api_key": config.DEFAULT_API_KEY[:8] + "***" if config.DEFAULT_API_KEY else "",
        "has_api_key": bool(config.DEFAULT_API_KEY),
        "llm_model": config.DEFAULT_LLM_MODEL,
        "comfyui_url": config.DEFAULT_COMFYUI_URL,
        "workflow": config.DEFAULT_WORKFLOW,
        "generation_mode": config.DEFAULT_GENERATION_MODE,
        "comfyui_url": config.DEFAULT_COMFYUI_URL,
        "comfyui_checkpoint": config.COMFYUI_CHECKPOINT,
        "image_api_base": config.DEFAULT_IMAGE_API_BASE,
        "image_api_key": config.DEFAULT_IMAGE_API_KEY[:8] + "***" if config.DEFAULT_IMAGE_API_KEY else "",
        "has_image_api_key": bool(config.DEFAULT_IMAGE_API_KEY),
        "image_model": config.DEFAULT_IMAGE_MODEL,
        "output_dir": config.OUTPUT_DIR,
    })


@app.route("/api/generate", methods=["POST"])
def api_generate():
    """Start full character card generation. Returns job_id immediately."""
    data = request.get_json(force=True)
    description = (data.get("description") or "").strip()
    if not description:
        return jsonify({"error": "description is required"}), 400

    job_id = _start_job(data, description)
    return jsonify({"job_id": job_id})


@app.route("/api/regenerate-image/<job_id>", methods=["POST"])
def api_regenerate_image(job_id):
    """Re-run image generation for a job where LLM already succeeded."""
    with _jobs_lock:
        job = _jobs.get(job_id)
    if not job:
        return jsonify({"error": "job not found"}), 404
    if not job.get("_card_dict"):
        return jsonify({"error": "no saved card data — LLM stage may not have completed"}), 400

    data = request.get_json(force=True) or {}
    image_model = data.get("image_model") or job.get("_image_model") or config.DEFAULT_IMAGE_MODEL
    generation_mode = data.get("generation_mode") or job.get("_generation_mode") or config.DEFAULT_GENERATION_MODE
    comfyui_url = data.get("comfyui_url") or job.get("_comfyui_url") or config.DEFAULT_COMFYUI_URL
    comfyui_checkpoint = data.get("comfyui_checkpoint") or job.get("_comfyui_checkpoint") or config.COMFYUI_CHECKPOINT
    image_api_base = data.get("image_api_base") or job.get("_image_api_base") or config.DEFAULT_IMAGE_API_BASE
    image_api_key = data.get("image_api_key") or job.get("_image_api_key") or config.DEFAULT_IMAGE_API_KEY

    with _jobs_lock:
        job["status"] = "queued"
        job["stage"] = "image"
        job["progress"] = 30
        job["message"] = f"正在重新生成立绘 ({generation_mode})..."
        job["image_error"] = None
        _jobs[job_id] = job

    thread = threading.Thread(
        target=_run_image_only,
        args=(job_id, generation_mode, comfyui_url, comfyui_checkpoint,
              image_api_base, image_api_key, image_model),
        daemon=True,
    )
    thread.start()
    return jsonify({"job_id": job_id})


@app.route("/api/status/<job_id>", methods=["GET"])
def api_status(job_id):
    """Poll generation progress."""
    with _jobs_lock:
        job = _jobs.get(job_id)
    if not job:
        return jsonify({"error": "job not found"}), 404
    return jsonify(job)


@app.route("/api/download/<job_id>", methods=["GET"])
def api_download(job_id):
    """Download the final character card PNG."""
    with _jobs_lock:
        job = _jobs.get(job_id)
    if not job or not job.get("output_path"):
        return jsonify({"error": "card not ready"}), 404
    filename = f"{job.get('char_name', 'character')}.png"
    return send_file(job["output_path"], mimetype="image/png", as_attachment=True, download_name=filename)


@app.route("/api/workflows", methods=["GET"])
def api_workflows():
    """List available ComfyUI workflows."""
    from charcard.comfy import list_workflows
    names = list_workflows()
    return jsonify({"workflows": names})


# ── Job helpers ───────────────────────────────────────────

def _start_job(data: dict, description: str) -> str:
    """Create a new job and launch the full generation thread."""
    job_id = str(uuid.uuid4())[:8]
    api_base = data.get("api_base") or config.DEFAULT_API_BASE
    api_key = data.get("api_key") or config.DEFAULT_API_KEY
    llm_model = data.get("llm_model") or config.DEFAULT_LLM_MODEL
    generation_mode = data.get("generation_mode") or config.DEFAULT_GENERATION_MODE
    comfyui_url = data.get("comfyui_url") or config.DEFAULT_COMFYUI_URL
    comfyui_checkpoint = data.get("comfyui_checkpoint") or config.COMFYUI_CHECKPOINT
    image_api_base = data.get("image_api_base") or config.DEFAULT_IMAGE_API_BASE
    image_api_key = data.get("image_api_key") or config.DEFAULT_IMAGE_API_KEY
    image_model = data.get("image_model") or config.DEFAULT_IMAGE_MODEL
    extra_instructions = (data.get("extra_instructions") or "").strip()

    with _jobs_lock:
        _jobs[job_id] = {
            "status": "queued", "stage": "starting", "progress": 0,
            "message": "正在准备生成...", "output_path": None,
            "_api_base": api_base, "_api_key": api_key,
            "_generation_mode": generation_mode,
            "_comfyui_url": comfyui_url, "_comfyui_checkpoint": comfyui_checkpoint,
            "_image_api_base": image_api_base, "_image_api_key": image_api_key,
            "_image_model": image_model,
        }

    thread = threading.Thread(
        target=_run_generation,
        args=(job_id, description, api_base, api_key, llm_model,
              generation_mode, comfyui_url, comfyui_checkpoint,
              image_api_base, image_api_key, image_model, extra_instructions),
        daemon=True,
    )
    thread.start()
    return job_id


# ── Generation pipeline ───────────────────────────────────

def _run_generation(job_id, description, api_base, api_key, llm_model,
                    generation_mode, comfyui_url, comfyui_checkpoint,
                    image_api_base, image_api_key, image_model, extra_instructions):
    try:
        # Stage 1: LLM text generation
        _update_job(job_id, "llm", 10, "LLM 正在生成角色设定...")
        card_dict = generate_card(
            description, llm_model,
            api_base=api_base, api_key=api_key,
            extra_instructions=extra_instructions,
        )

        # Save card_dict for potential image retry
        with _jobs_lock:
            _jobs[job_id]["_card_dict"] = card_dict

        # Stage 2: Build card
        _update_job(job_id, "building", 30, "正在组装角色卡 JSON...")
        card = build(card_dict)
        image_prompt = card.pop("_image_prompt", "")
        char_name = card["data"].get("name", "character")

        # Stage 3: Generate portrait
        _run_image_stage(job_id, image_prompt, generation_mode,
                         comfyui_url, comfyui_checkpoint,
                         image_api_base, image_api_key, image_model)

        # Stage 4: Embed into PNG
        _update_job(job_id, "embedding", 90, "正在嵌入角色卡数据到 PNG...")
        os.makedirs(config.OUTPUT_DIR, exist_ok=True)
        safe_name = "".join(c for c in char_name if c.isalnum() or c in "._- ")
        output_path = _do_embed(job_id, card, char_name, safe_name)

        # Stage 5: Done
        _update_job(job_id, "done", 100, "角色卡生成完成！",
                     output_path=output_path, char_name=char_name, card=card)

    except Exception as e:
        _update_job(job_id, "error", 0, f"生成失败: {str(e)}")


def _run_image_only(job_id, generation_mode, comfyui_url, comfyui_checkpoint,
                    image_api_base, image_api_key, image_model):
    """Re-run only the image generation stage for an existing job."""
    try:
        with _jobs_lock:
            card_dict = _jobs[job_id].get("_card_dict", {})
        card = build(card_dict)
        image_prompt = card.pop("_image_prompt", "")
        char_name = card["data"].get("name", "character")
    except Exception as e:
        _update_job(job_id, "error", 0, f"从缓存恢复角色卡数据失败: {str(e)}")
        return

    try:
        _run_image_stage(job_id, image_prompt, generation_mode,
                         comfyui_url, comfyui_checkpoint,
                         image_api_base, image_api_key, image_model)

        _update_job(job_id, "embedding", 90, "正在嵌入角色卡数据到 PNG...")
        os.makedirs(config.OUTPUT_DIR, exist_ok=True)
        safe_name = "".join(c for c in char_name if c.isalnum() or c in "._- ")
        output_path = _do_embed(job_id, card, char_name, safe_name)

        _update_job(job_id, "done", 100, "角色卡生成完成！",
                     output_path=output_path, char_name=char_name, card=card)
    except Exception as e:
        _update_job(job_id, "error", 0, f"生成失败: {str(e)}")


def _run_image_stage(job_id, image_prompt, generation_mode,
                     comfyui_url, comfyui_checkpoint,
                     image_api_base, image_api_key, image_model):
    """Run the image generation portion, with fallback to placeholder."""
    _update_job(job_id, "image", 50, f"正在生成角色立绘 ({generation_mode})...")
    image_error = None

    try:
        portrait_path = generate_portrait(
            image_prompt,
            mode=generation_mode,
            comfyui_url=comfyui_url,
            checkpoint=comfyui_checkpoint,
            cloud_model=image_model,
            image_api_base=image_api_base,
            image_api_key=image_api_key,
            output_dir=config.OUTPUT_DIR,
        )
    except Exception as e:
        image_error = str(e)
        os.makedirs(config.OUTPUT_DIR, exist_ok=True)
        portrait_path = os.path.join(config.OUTPUT_DIR, f"placeholder_{job_id}.png")
        build_placeholder_card(portrait_path)

    with _jobs_lock:
        _jobs[job_id]["_portrait_path"] = portrait_path

    if image_error:
        _update_job(job_id, "image", 80,
                     f"立绘生成失败，已使用占位图。可修改图片模型后点击「重新生成立绘」",
                     image_error=image_error)
    else:
        _update_job(job_id, "image", 80, "立绘生成完成")


def _do_embed(job_id, card, char_name, safe_name):
    """Embed card JSON into the portrait PNG."""
    with _jobs_lock:
        portrait_path = _jobs[job_id].get("_portrait_path") or ""
    output_path = os.path.join(config.OUTPUT_DIR, f"{safe_name}.png")
    if os.path.abspath(portrait_path) == os.path.abspath(output_path):
        output_path = os.path.join(config.OUTPUT_DIR, f"{safe_name}_card.png")
    embed(card, portrait_path, output_path)
    return output_path


def _update_job(job_id, stage, progress, message, output_path=None, char_name=None, card=None, image_error=None):
    with _jobs_lock:
        job = _jobs.get(job_id, {})
        job.update({"stage": stage, "progress": progress, "message": message})
        if image_error:
            job["image_error"] = image_error
        if output_path:
            job["output_path"] = output_path
        if char_name:
            job["char_name"] = char_name
        if card:
            job["card_preview"] = {
                "name": card["data"].get("name", ""),
                "description": card["data"].get("description", ""),
                "personality": card["data"].get("personality", ""),
                "scenario": card["data"].get("scenario", ""),
                "first_mes": card["data"].get("first_mes", ""),
                "tags": card["data"].get("tags", []),
                "world_book_entries": len(card["data"].get("character_book", {}).get("entries", [])),
            }
        _jobs[job_id] = job


# ── Main ──────────────────────────────────────────────────

if __name__ == "__main__":
    print(f"Starting charcard server on http://{config.SERVER_HOST}:{config.SERVER_PORT}")
    app.run(host=config.SERVER_HOST, port=config.SERVER_PORT, debug=False)
