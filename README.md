# Layered Design Generator

将 UI 设计拆解为可独立使用的透明图层，支持从需求到交付的完整工作流。

> 🎯 **Kimi Skill**：基于 OpenAI 兼容图像模型的 AI 辅助设计生成工具。

---

## 功能特性

| 特性 | 说明 |
|------|------|
| **8 阶段工作流** | 需求 → 确认 → 粗稿 → 校验 → 精修预览 → 精修图层 → 交付 → 变体（可选） |
| **交互式网页预览** | 在浏览器中拖拽、缩放、编辑图层位置，导出调整后的布局 JSON |
| **透明图层提取** | 非背景图层自动检测透明度，若无 alpha 通道则使用 rembg 抠图；支持 U²Net / BiRefNet 等可配置模型 |
| **尺寸合规校验** | 自动验证 gpt-image-2 尺寸约束（最大边 3840px、16 对齐、宽高比 ≤ 3:1） |
| **双分辨率策略** | Phase 1-4 使用降采样尺寸加速迭代，Phase 5-6 使用完整尺寸输出 |
| **状态变体（可选）** | Phase 8 可生成控件的 hover、active、disabled 等状态图 |
| **快速通道模式** | 单预览快速迭代，Phase 1~2 合并减少确认步骤 |

---

## 写在最前的话

这一段不是AI写的了（嗯其他的都是AI写的基本上）

1. 一个是下载模型的时候会非常非常卡，这个时候agent超时会等的要死，我的建议是自己下了放进去让agent去硬链接继续配置
2. 这玩意中间AI做着做着很容易因为上下文或者什么奇妙原因跳步骤，以及生成图片的时候也有这种超时问题（尤其是异步任务），个人建议是用cron回来做一次检查或者唤起subagent去做
3. BiRefNet模型推理抠图的时候非常容易卡，是正常的
4. 这个工作流主要是应对游戏UI这种相对复杂的东西，最后出来的都是一张张的图素，如果是简单的网页之类的其实像Figma Make，Gemini之类的性价比更高

---

## 快速开始

### 前置条件

- Python 3.9+
- Git

### 安装（推荐交互式）

**推荐方式**：直接告诉 AI Agent **"开始安装"** 或 **"开始部署"**，Agent 会引导你完成交互式安装，包括：
- 选择 API 端点和模型
- 选择抠图模型（U²Net / BiRefNet 等）
- 中国大陆用户可选择镜像下载
- 自动安装依赖并下载模型

### 手动安装

如果希望手动安装，可运行初始化脚本：

```bash
cd layer-designer
python scripts/setup.py
```

`setup.py` 会自动：
1. 安装 Python 依赖（`openai`、`Pillow`、`rembg`、`numpy`）
2. 下载默认 U²Net 模型（约 176MB）
3. 从模板创建 `config.json`

> **中国大陆用户**：若 GitHub 下载超时，可在 `config.json` 中设置 `"download_mirror": "https://ghproxy.cn"`，或运行 `python scripts/setup.py --mirror https://ghproxy.cn`
>
> 也可手动下载模型后放置到 `layer-designer/models/` 目录，并在 `config.json` 的 `matting` 中指定 `"model_file": "你的文件名.onnx"`

### ⚠️ 配置（重要）

**必须**编辑配置文件，填入你的 API 端点和密钥：

```bash
# 如果 setup.py 没有自动创建，手动复制模板
cp layer-designer/config.example.json layer-designer/config.json
```

然后编辑 `layer-designer/config.json`：
- `api.base_url` — 你的 OpenAI 兼容端点
- `api.api_key` — 你的 API 密钥

> `config.json` 已被 `.gitignore` 忽略，不会意外提交到仓库。

---

## 工作流总览

```
Phase 1  需求收集     →  收集需求、校验尺寸、生成预览图
      ↓
Phase 2  方案确认     →  图层拆分方案 + 布局提取 + 风格锚点
      ↓
Phase 3  粗稿分层     →  生成各图层隔离图（降采样尺寸）
      ↓
Phase 4  网页合成校验  →  透明度检查 → 交互式网页预览 → 用户确认布局
      ↓
Phase 5  精修预览     →  高画质完整预览图（可选）
      ↓
Phase 6  精修图层     →  最终高画质各图层（完整尺寸）
      ↓
Phase 7  最终交付     →  交付资源 + 网页预览 + 清单文件
      ↓
Phase 8  状态变体     →  hover / active / disabled 等状态（可选，默认不执行）
```

### Phase 4 交互式校验

不生成静态合成图，而是生成：
- `enhanced_layer_plan.json` — 布局数据 + 资源路径
- `preview.html` — 通用静态预览页面

用浏览器打开 `preview.html` 即可：
- **拖拽** 图层调整位置
- **缩放** 8 方向手柄调整大小
- **编辑** 名称、内容、状态、布局数值
- **导出** 更新后的 `enhanced_layer_plan.json`

用户确认布局无误后再进入精修阶段。

---

## 项目结构

```
layer-designer/
├── config.example.json          # 配置模板（复制为 config.json 后编辑）
├── config.json                  # 本地配置（gitignored）
├── SKILL.md                     # Skill 入口文档（供 AI Agent 阅读）
├── .gitignore                   # Git 忽略规则
├── .gitattributes               # Git 属性配置
│
├── models/                      # 模型目录（初始化时自动下载）
│   └── u2net.onnx               # U²Net 分割模型（setup.py 下载）
│
├── scripts/                     # 核心脚本
├── templates/
│   └── preview.html             # 通用静态交互式预览页面
│
├── references/                  # 阶段参考文档
│   ├── workflow-overview.md     # 工作流全貌速查
│   ├── phase-1-requirements.md  # Phase 1 详细步骤
│   ├── phase-2-confirmation.md  # Phase 2 详细步骤
│   ├── phase-3-rough-design.md  # Phase 3 详细步骤
│   ├── phase-4-check.md         # Phase 4 详细步骤
│   ├── phase-5-refinement-preview.md
│   ├── phase-6-refinement-layers.md
│   ├── phase-7-output.md
│   ├── phase-8-variants.md
│   ├── incremental-update.md    # 增量更新模式
│   └── prompt-templates.md      # 各阶段 Prompt 模板
│
└── output/                      # 生成输出目录（gitignored）
    └── {project_name}/
```

---

## 尺寸约束（硬性限制）

配置的端点对图像尺寸有以下限制（违反将返回 502 错误）：

- 最大边长：≤ 3840px
- 对齐要求：两边均为 16 的倍数
- 宽高比：≤ 3:1
- 最小像素数：≥ 655,360（约 1024×640）
- 最大像素数：≤ 8,294,400（约 4K）

任何图像生成前必须先通过尺寸校验。

---

## 透明度说明

配置的 API 端点输出 **RGB 模式 PNG**（无真实 alpha 通道）。对于需要透明底的图层：

1. 通过图生图生成隔离图层
2. 使用 rembg 深度学习抠图（支持 U²Net / BiRefNet 等模型），生成带羽化边缘的真 RGBA PNG
3. 透明版本另存为 `{layer}_rgba.png`

可在 `config.json` 的 `matting` 区块切换模型：
```json
"matting": {
  "model": "birefnet-general",
  "model_file": "BiRefNet-general-epoch_244.onnx"
}
```

---

## License

MIT
