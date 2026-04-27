# Setup Guide — 交互式安装流程

> 本文档面向 AI Agent。当用户说出**"开始部署"**或**"开始安装"**时，Agent 必须按以下步骤引导用户完成交互式安装，而不是直接运行 `setup.py` 后静默结束。

---

## 触发条件

用户输入包含以下任一关键词：
- "开始部署"
- "开始安装"
- "setup"
- "初始化"
- "怎么安装"
- "如何配置"

---

## 安装流程（必须逐步交互）

### Step 1 — 环境预检

检查 Python 版本：
```python
import sys
assert sys.version_info >= (3, 9), "Python 3.9+ required"
```

如果不符合，终止安装并提示用户升级 Python。

---

### Step 2 — API 配置询问（必须交互）

**询问用户**：
> 你是否已有可用的图像生成 API？本项目需要支持 OpenAI 兼容接口的端点（如 gpt-image-2、gpt-image-1.5 或类似模型）。

**选项呈现**：

| 选项 | 行为 |
|------|------|
| **A. 现在提供** | Agent 依次询问 `provider`（openai / apimart）、`base_url`、`api_key`、`model`（默认 gpt-image-2），并写入 `config.json` |
| **B. 稍后自行配置** | Agent 跳过 API 写入，但**必须明确提醒**：`config.json` 必须配置后才能运行任何生成脚本。复制 `config.example.json` 为 `config.json` 后由用户手动填写 |

**如果用户选择 A**，Agent 按以下结构写入 `config.json` 的 `api` 区块：
```json
{
  "api": {
    "provider": "openai",
    "openai": {
      "provider_type": "openai",
      "base_url": "用户输入",
      "api_key": "用户输入",
      "model": "gpt-image-2",
      "default_size": "1024x1024",
      "default_quality_low": "low",
      "default_quality_medium": "medium",
      "default_quality_high": "high",
      "default_n": 1,
      "output_format": "png"
    }
  }
}
```

**安全提醒**：告知用户 `config.json` 已被 `.gitignore` 忽略，不会意外提交到仓库。

---

### Step 3 — 抠图模型选择（必须交互）

**询问用户**：
> 请选择背景移除（matting）模型。不同模型在文件大小和边缘质量上有差异：

| 模型 | 大小 | 特点 | 适用场景 |
|------|------|------|---------|
| `u2net` | ~176 MB | 通用模型，速度较快，对简单背景效果好 | 纯色/简单渐变背景、常规 UI 控件 |
| `birefnet-general` | ~973 MB | 边缘质量显著提升，复杂边缘保留更好 | 精细 UI 元素、阴影丰富、纹理复杂的图层 |
| `birefnet-general-lite` | ~300 MB | BiRefNet 轻量版，平衡速度与质量 | 中等复杂度场景 |
| `birefnet-portrait` | ~400 MB | 针对人像/角色优化 | 需要提取人物/角色图层时 |

**推荐**：对于 UI/UX 设计生成，默认推荐 `u2net`（快且省空间）或 `birefnet-general`（质量更好但接近 1GB）。

**额外询问**：
> 你已经下载好模型文件了吗？

- **没有 / 想自动下载** → 只配置 `matting.model`，由 `setup.py` 自动下载
- **已经手动下载** → 询问实际文件名（如 `BiRefNet-general-epoch_244.onnx`），将 `matting.model_file` 写入配置。脚本会自动创建硬链接，无需手动重命名

Agent 将 `matting.model`（及可选的 `matting.model_file`）写入 `config.json`。

---

### Step 4 — 镜像下载询问（中文用户额外步骤）

**如果用户使用中文**（通过对话语言判断），**必须额外询问**：
> 由于模型文件托管在 GitHub，中国大陆用户可能下载缓慢或超时。是否需要启用镜像下载？推荐 `github.tbedu.top`。

**选项**：
- **是** → 在 `config.json` 中设置 `"download_mirror": "https://github.tbedu.top"`
- **否 / 使用其他镜像** → 按用户输入设置 `"download_mirror"`（留空表示不走镜像）
- **我已科学上网** → `download_mirror` 留空

---

### Step 5 — 安装 Python 依赖

Agent 直接执行：
```bash
python -m pip install --upgrade pip
python -m pip install openai>=2.0 Pillow rembg>=2.0 numpy
```

安装完成后告知用户。

---

### Step 6 — 下载 ONNX 模型

Agent 调用 `scripts/setup.py` 中对应的下载逻辑（或直接通过 `rembg.session_factory.new_session` 触发下载），并传入 mirror 配置：

```bash
# 若配置了 mirror
python scripts/setup.py --mirror https://ghproxy.cn

# 或若 mirror 已写入 config.json，直接运行
python scripts/setup.py
```

**注意**：
- 如果模型已存在，setup.py 会跳过下载。
- 如果下载失败，Agent 应输出手动下载命令给用户，而不是静默失败。

---

### Step 7 — 创建/更新 config.json

确保 `config.json` 存在：
1. 如果不存在，从 `config.example.json` 复制。
2. 将 Step 2（API 配置）、Step 3（matting.model）、Step 4（download_mirror）写入 `config.json`。

---

### Step 8 — 安装验证

Agent 执行验证：
1. 检查包可导入：`openai`, `PIL`, `rembg`, `numpy`
2. 检查模型文件：`models/u2net.onnx` 及用户选择的其他模型
3. 检查 `config.json` 存在

输出验证结果，明确告知用户哪些项 OK、哪些项需要后续补充。

---

### Step 9 — 结束语

> 安装完成！当前配置摘要：
> - Python: {version}
> - Matting 模型: {model_name}
> - 镜像下载: {mirror or "未启用"}
> - API 配置: {已配置 / 未配置（请稍后编辑 config.json）}
>
> 你可以随时运行 `python scripts/setup.py` 补充下载模型，或直接修改 `config.json` 调整配置。

---

## 禁止行为

- **禁止**在没有用户确认的情况下自动填写 API 密钥（即使是占位符）。
- **禁止**跳过模型选择直接默认用 `u2net`；必须让用户知情并选择。
- **禁止**在中文用户场景下不询问镜像下载；这是中国大陆用户的体验必要步骤。
- **禁止**把安装过程变成纯脚本自动运行后只输出一句"Done"；每一步关键选择都需要用户确认。
