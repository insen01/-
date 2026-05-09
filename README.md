# 🎴 CharCard Generator

SillyTavern v2 角色卡一键生成器 — 输入角色描述，AI 自动生成完整角色卡 PNG（含世界书、性格设定、开场白、AI 立绘）。

## 功能清单

- **LLM 文本生成** — 调用 SiliconFlow / DeepSeek API，自动生成角色名、性格、场景、开场白、世界书
- **AI 立绘生成** — 优先本地 ComfyUI 动漫工作流，自动兜底云端图片 API
- **SillyTavern v2 规范** — 输出标准 PNG 角色卡，元数据嵌入 tEXt chunk，直接导入即用
- **Web 界面** — 单页前端，三种输入模式（直接填写/上传文件/引导式），实时进度 + 预览
- **安全** — API Key 仅通过环境变量读取，无硬编码密钥

## 安装

```bash
git clone git@github.com:insen01/-.git
cd -
pip install -r requirements.txt
```

## 启动

```bash
# 1. 设置 API Key
export SILICONFLOW_API_KEY=sk-your-key-here

# 2. 启动服务
python3 server.py

# 3. 浏览器打开 (手机/PC均可)
# http://localhost:5000
```

如需局域网访问（手机调试），修改 `config.py` 中 `SERVER_HOST = "0.0.0.0"`（默认已启用）。

## 使用方式

### Web 界面（推荐）

打开 `http://localhost:5000`：

| 输入模式 | 说明 |
|---------|------|
| **直接输入** | 在文本框中粘贴角色描述，自由格式 |
| **上传文件** | 上传 `.txt` 或 `.md` 文件 |
| **引导填写** | 逐字段填写角色名、外貌、性格、背景、世界观 |

点击「生成」→ LLM 写文本 → ComfyUI/云端生成立绘 → 嵌入 PNG → 下载。

### 命令行

```bash
# 文件输入
python3 charcard.py -f character.txt

# 直接输入
python3 charcard.py -t "一个冷酷的流浪女剑客..."

# 交互式问答
python3 charcard.py -i
```

## 高级设置

在 Web 界面展开「⚙ 高级设置」：

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| LLM Model | `deepseek-ai/DeepSeek-V3` | 任意 SiliconFlow 支持的 Chat 模型 |
| ComfyUI URL | `http://127.0.0.1:8188` | 本地 ComfyUI 地址 |
| Workflow | `anime_char.json` | ComfyUI 工作流文件名 |
| Fallback Image Model | `stabilityai/stable-diffusion-xl-base-1.0` | 云端兜底图片模型 |

跳过本地 ComfyUI 可直接使用云端兜底生成立绘。

## API 路由

| 路由 | 方法 | 说明 |
|------|------|------|
| `/` | GET | Web 界面 |
| `/api/config` | GET | 获取默认配置 |
| `/api/generate` | POST | 提交生成任务 → 返回 `job_id` |
| `/api/status/<id>` | GET | 轮询进度 `{stage, progress, message}` |
| `/api/download/<id>` | GET | 下载最终角色卡 PNG |
| `/api/workflows` | GET | 列出 ComfyUI 工作流 |

### POST /api/generate

```json
{
  "description": "角色描述文本（必填）",
  "llm_model": "deepseek-ai/DeepSeek-V3",
  "comfyui_url": "http://127.0.0.1:8188",
  "workflow": "anime_char.json",
  "image_model": "stabilityai/sdxl",
  "switches": {},
  "skip_comfyui": false
}
```

## 输出文件

生成的 PNG 角色卡保存在：

```
/sdcard/Download/claude code/characters/
```

PNG 文件兼容 SillyTavern 直接导入（Drag & Drop 到 ST 界面即可）。

## 项目结构

```
.
├── server.py              # Flask API + 任务编排
├── templates/index.html   # 前端界面
├── llm.py                 # LLM 文本生成 (SiliconFlow)
├── card_builder.py        # 角色卡 JSON → v2 spec
├── comfy.py               # ComfyUI + 云端图片生成
├── png_assembler.py       # JSON 嵌入 PNG 元数据
├── config.py              # 默认配置（可自定义）
└── requirements.txt       # flask + pillow
```

## 依赖

- Python 3.8+
- Flask ≥ 3.0
- Pillow ≥ 10.0
- SiliconFlow API Key（注册获取: https://cloud.siliconflow.cn）
- ComfyUI（可选，用于本地立绘生成）
