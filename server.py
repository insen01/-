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

# In-memory job store: {job_id: {status, stage, progress, message, output_path}}
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
        "llm_model": config.DEFAULT_LLM_MODEL,
        "comfyui_url": config.DEFAULT_COMFYUI_URL,
        "workflow": config.DEFAULT_WORKFLOW,
        "image_model": config.DEFAULT_IMAGE_MODEL,
        "output_dir": config.OUTPUT_DIR,
    })


@app.route("/api/generate", methods=["POST"])
def api_generate():
    """Start character card generation. Returns job_id immediately."""
    data = request.get_json(force=True)
    description = (data.get("description") or "").strip()
    if not description:
        return jsonify({"error": "description is required"}), 400

    job_id = str(uuid.uuid4())[:8]
    llm_model = data.get("llm_model") or config.DEFAULT_LLM_MODEL
    comfyui_url = data.get("comfyui_url") or config.DEFAULT_COMFYUI_URL
    workflow = data.get("workflow") or config.DEFAULT_WORKFLOW
    switches = data.get("switches") or {}
    skip_comfyui = data.get("skip_comfyui", False)
    image_model = data.get("image_model") or config.DEFAULT_IMAGE_MODEL

    with _jobs_lock:
        _jobs[job_id] = {
            "status": "queued", "stage": "starting", "progress": 0,
            "message": "正在准备生成...", "output_path": None
        }

    thread = threading.Thread(
        target=_run_generation,
        args=(job_id, description, llm_model, comfyui_url, workflow, switches, skip_comfyui, image_model),
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


# ── Generation pipeline ───────────────────────────────────

def _run_generation(job_id, description, llm_model, comfyui_url, workflow, switches, skip_comfyui, image_model):
    try:
        # Stage 1: LLM text generation
        _update_job(job_id, "llm", 10, "LLM 正在生成角色设定...")
        card_dict = generate_card(description, llm_model)

        # Stage 2: Build card
        _update_job(job_id, "building", 30, "正在组装角色卡 JSON...")
        card = build(card_dict)
        image_prompt = card.pop("_image_prompt", "")
        char_name = card["data"].get("name", "character")

        # Stage 3: Generate portrait
        _update_job(job_id, "image", 50, "正在生成角色立绘...")

        try:
            portrait_path = _cloud_generate(image_prompt, image_model, config.OUTPUT_DIR)
        except Exception as e:
            # Fallback: use placeholder if image generation fails
            os.makedirs(config.OUTPUT_DIR, exist_ok=True)
            portrait_path = os.path.join(config.OUTPUT_DIR, f"placeholder_{job_id}.png")
            build_placeholder_card(portrait_path)

        _update_job(job_id, "image", 80, "立绘生成完成")

        # Stage 4: Embed into PNG
        _update_job(job_id, "embedding", 90, "正在嵌入角色卡数据到 PNG...")
        os.makedirs(config.OUTPUT_DIR, exist_ok=True)
        safe_name = "".join(c for c in char_name if c.isalnum() or c in "._- ")
        output_path = os.path.join(config.OUTPUT_DIR, f"{safe_name}.png")

        if os.path.abspath(portrait_path) == os.path.abspath(output_path):
            output_path = os.path.join(config.OUTPUT_DIR, f"{safe_name}_card.png")

        embed(card, portrait_path, output_path)

        # Stage 5: Done
        _update_job(job_id, "done", 100, "角色卡生成完成！",
                     output_path=output_path, char_name=char_name, card=card)

    except Exception as e:
        _update_job(job_id, "error", 0, f"生成失败: {str(e)}")


def _update_job(job_id, stage, progress, message, output_path=None, char_name=None, card=None):
    with _jobs_lock:
        job = _jobs.get(job_id, {})
        job.update({"stage": stage, "progress": progress, "message": message})
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
