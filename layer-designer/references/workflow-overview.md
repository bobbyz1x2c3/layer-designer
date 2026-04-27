# Layered Design Generator — 完整工作流信息

> 本文档是 `SKILL.md` 的补充速查，汇总当前 skill 的完整状态。agent 进入工作流前应先读 `SKILL.md`，执行具体阶段前再读对应的 `phase-N-*.md`。

---

## 1. 项目结构

```
layer-designer/
├── SKILL.md                              # 主技能文档（入口点）
├── config.json                           # 配置中心（API、模型约束、工作流行为）
├── models/
│   └── u2net.onnx                        # rembg 抠图模型（176MB，skill 内部托管）
├── references/                           # 阶段参考文档 + 指南
│   ├── workflow-overview.md              # ← 本文档（全貌速查）
│   ├── phase-1-requirements.md           # Phase 1 详细步骤
│   ├── phase-2-confirmation.md           # Phase 2 详细步骤
│   ├── phase-3-rough-design.md           # Phase 3 详细步骤
│   ├── phase-4-check.md                  # Phase 4 详细步骤
│   ├── phase-5-refinement-preview.md     # Phase 5 详细步骤
│   ├── phase-6-refinement-layers.md      # Phase 6 详细步骤
│   ├── phase-7-output.md                 # Phase 7 详细步骤
│   ├── phase-8-variants.md               # Phase 8 详细步骤
│   ├── incremental-update.md             # 增量更新模式（修改已有项目）
│   ├── optimization-modes.md             # 优化模式说明
│   └── prompt-templates.md               # 各阶段 prompt 模板
├── scripts/                              # 全部脚本
│   ├── generate_image.py                 # 文生图 / 图生图（OpenAI-compatible API）
│   ├── check_transparency.py             # 透明度检查 + rembg 抠图
│   ├── generate_variants.py              # 批量生成控件状态变体
│   ├── generate_preview.py               # 生成 HTML 预览（按 layout 定位叠加图层）
│   ├── validate_size.py                  # 尺寸验证 + early/full size 计算
│   ├── path_manager.py                   # 标准路径生成 + 尺寸合规工具
│   ├── config_loader.py                  # 配置加载（含环境变量解析）
│   └── clean_cache.py                    # 缓存清理
└── test-ref/                             # 测试素材
    ├── entrances_001.png                 # RGB 模式样例（需 rembg 抠图）
    └── test_transparent_button.png       # 真 RGBA 样例
```

---

## 2. 8 阶段工作流总览

```
Phase 1 需求收集      →  validate_size.py + generate_image.py generate/edit
      ↓
Phase 2 确认方案      →  视觉分析 + layout 提取 + 写入 layer_plan.json
      ↓
Phase 3 粗稿分层      →  generate_image.py edit（early_size）
      ↓
Phase 4 网页预览校验   →  check_transparency.py + generate_preview.py（网页预览 + 截图检查）
      ↓
Phase 5 精修预览      →  generate_image.py edit（full_size）
      ↓
Phase 6 精修图层      →  generate_image.py edit（full_size）+ check_transparency.py + preview HTML
      ↓
Phase 7 最终交付      →  copy + manifest.json
      ↓
Phase 8 状态变体      →  generate_variants.py（可选）
```

### 阶段与脚本对照表

| Phase | 名称 | 输入 | 输出 | 调用脚本 |
|-------|------|------|------|---------|
| 1 | Requirements | 用户需求 + 尺寸 | 预览图 + size_plan.json | `validate_size.py`, `generate_image.py` |
| 2 | Confirmation | 确认预览图 | layer_plan.json（含 layout）+ style_anchor | （视觉分析，无脚本生成） |
| 3 | Rough Design | layer_plan.json | 各图层隔离图（early_size）+ layout | `generate_image.py edit` |
| 4 | Web Composition Check | 图层隔离图 | 网页预览 + 截图 + 校验报告 | `check_transparency.py`, `generate_preview.py` |
| 5 | Refinement Preview | 原始预览图 / Phase 4 截图 | 精修预览（full_size） | `generate_image.py edit` |
| 6 | Refinement Layers | 精修预览 | 精修图层（full_size）+ layout | `generate_image.py edit`, `check_transparency.py` |
| 7 | Output | 精修图层 | preview.html + layers/ + manifest.json | `generate_preview.py`（copy + write） |
| 8 | State Variants | 控件图层 | hover/active/disabled 变体 | `generate_variants.py` |

---

## 3. 脚本详情

### `generate_image.py` — 统一图像生成

| 子命令 | 用途 | 典型调用阶段 |
|--------|------|-------------|
| `generate` | 文生图 | Phase 1 预览生成 |
| `edit` | 图生图（传入 Path 对象） | Phase 3/4/5/6/8 图层隔离/修改 |

**关键实现**（OpenAI SDK 2.32.0）：
- `images.generate()`: `response_format="b64_json"`
- `images.edit()`: `image=Path(image_path)` 直接传 Path 对象，`response_format="b64_json"`
- `--background transparent` 参数存在但**当前端点不支持**（502）

### `check_transparency.py` — 透明度检查 + 背景移除

| 功能 | 说明 |
|------|------|
| 检查 | RGBA 模式 → 随机采样检测 alpha==0 ≥ 2 个像素 |
| 检查 | RGB/L/P 模式 → 降级检测纯色浅色背景 |
| **抠图** | `--remove-bg` 触发 rembg（U²Net）深度学习抠图 |

**抠图实现**：
- 使用 `rembg.remove()`（U²Net ONNX 模型）
- 模型路径：`layer-designer/models/u2net.onnx`（通过 `U2NET_HOME` 环境变量指向）
- **不允许 fallback**，rembg 失败直接报错
- 输出带羽化边缘的真 RGBA PNG

### `validate_size.py` — 尺寸验证

- 验证 5 个约束：max_edge ≤ 3840、align 16、ratio ≤ 3.0、min_pixels ≥ 655360、max_pixels ≤ 8294400
- 不合规则建议最近合规尺寸（保持宽高比）
- 计算 `early_size`（Phase 1~4，默认 0.5× 下采样）和 `full_size`（Phase 5~8）
- 保存 `01-requirements/size_plan.json`

### `generate_preview.py` — 生成 enhanced_layer_plan + 预览模板

| 参数 | 说明 |
|------|------|
| `--project` | 项目名称 |
| `--phase check` | Phase 4 使用：读取 `03-rough-design` 图层，生成 `04-check/enhanced_layer_plan.json`，复制预览模板 |
| `--phase refinement` | Phase 7 使用：读取 `06-refinement-layers` 图层，生成 `06-refinement-layers/enhanced_layer_plan.json` |

- 读取 `layer_plan.json` 获取 layout 和图层信息
- 扫描图层目录，收集最新 PNG 的资源路径
- 按 `size_plan.json` 缩放 layout 坐标（rough/check phase）
- 生成 `enhanced_layer_plan.json`（含 name, content, status, layout, source）
- 复制通用静态模板 `templates/preview.html` 到输出目录

### `generate_variants.py` — 状态变体

- 内部调用 `generate_image.py edit` 子进程
- 内置默认状态 prompt（hover/active/disabled/focused 等）
- 支持 `--custom-prompts` 传入 JSON 覆盖

### `path_manager.py` — 路径与尺寸工具

| 函数 | 用途 |
|------|------|
| `is_size_compliant()` | 检查尺寸是否合规 |
| `compute_compliant_size()` | 计算最小合规尺寸（保持比例） |
| `compute_early_phase_size()` | 计算 early_size（下采样 + 合规修正） |
| `get_layer_path()` / `get_final_layer_path()` / `get_variant_path()` | 标准路径生成 |

---

## 4. 配置中心 (`config.json`)

| 区块 | 关键字段 | 当前值 |
|------|---------|--------|
| `api` | `model` | `gpt-image-2` |
| `model_constraints.gpt-image-2` | 5 个约束 | max_edge 3840, align 16, max_ratio 3.0, min_pixels 655360, max_pixels 8294400 |
| `model_constraints.gpt-image-1.5` | 同上 + `supports_transparent_output: true` | 预留配置 |
| `workflow` | `fast_workflow` | `true` |
| `workflow` | `downsize_early_phases` | `true` |
| `workflow` | `quality_adaptive` | `true` |
| `workflow` | `parallel_generation` | `true` |
| `workflow` | `parallel_max_workers` | `8` |
| `paths` | `output_root` | `./output` |

---

## 5. API 端点已知限制

| 项目 | 状态 | 说明 |
|------|------|------|
| `generate`（文生图） | ✅ 正常 | 输出 RGB 模式 PNG |
| `edit`（图生图） | ✅ 正常 | 输出 RGB 模式 PNG |
| `background=transparent` | ❌ 502 | 端点不支持该参数 |
| 真透明 PNG 输出 | ❌ 不支持 | 所有模型均输出 RGB，无 alpha |
| **透明底解决方案** | ✅ rembg 后处理 | `check_transparency.py --remove-bg` |

---

## 6. 两种工作模式

### Standard Mode（标准模式）
- Phase 1 生成 **3 张预览**
- 修订轮次 **不限**
- Phase 2 **独立阶段**（图层方案需单独 OK）
- 适合：新设计、需求不明确

### Fast Track Mode（快速通道）
- Phase 1 生成 **1 张预览**
- 修订 **不限轮次**
- Phase 2 **合并到 Phase 1 Step 9**（预览 OK 后立即输出图层方案）
- 适合：快速迭代、已知资产类型

---

## 7. 关键规则（11 条）

1. **Invoke scripts, don't reimplement** — 有脚本必须调用，不重写逻辑
2. **Size validation is mandatory** — Phase 1 必须先跑 `validate_size.py`
3. **Explicit OK required** — 阶段切换必须等用户说 "OK"
4. **Style anchor persistence** — Phase 2 提取的 style_anchor 必须写入后续所有 prompt
5. **Per-layer canvas with matching aspect ratio** — 每个非背景图层根据 `layer_plan.json` 中的宽高比例，通过 `compute_layer_size()` 计算独立的合规画布尺寸。控件按比例放大填满画布，画布比例与控件一致。这样既减少透明边距（方便 rembg 抠图），又保证图像尺寸合规。
6. **Quality adaptive** — 简单图层 low→medium，复杂图层 medium→high
7. **Transparent layers** — 非背景层必须有真实 alpha
8. **Preserve aspect ratio** — 修正不合规尺寸时保持原比例
9. **Image-to-image for modifications** — 任何修改必须用 `generate_image.py edit`，不能用 `generate`
10. **Layout extraction** — Phase 2 的 `layer_plan.json` 每个图层必须包含 `layout: {x, y, width, height}`（full-size 坐标）
11. **Preview generation** — Phase 4 和 Phase 7 生成 HTML 预览（`generate_preview.py`）。Phase 4 预览支持拖拽/缩放/导出，用于 layout 微调。

---

## 8. 文件读取顺序

agent 进入工作流时的阅读顺序：

```
1. SKILL.md                              # 了解全貌、规则、脚本映射
2. references/phase-N-*.md               # 进入具体阶段前必读
   └── 每个 phase doc 内含：
       - 该阶段的输入/输出路径
       - 每步操作细节
       - 脚本调用命令
3. references/incremental-update.md      # 仅当用户要求修改已完成项目时读

```

---

## 9. 输出目录树（完整版）

```
{output_root}/{project_name}/
├── 01-requirements/
│   ├── previews/
│   │   ├── preview_v1_001_{timestamp}.png
│   │   ├── preview_v1_002_{timestamp}.png
│   │   ├── preview_v1_003_{timestamp}.png   # Standard 模式
│   │   ├── preview_v2_001_{timestamp}.png   # 修订轮次
│   │   └── ...
│   ├── references/                          # reference-image 模式
│   │   └── ref_image_{timestamp}.png
│   ├── size_plan.json
│   └── conversation_log.json
├── 02-confirmation/
│   └── layer_plan.json
├── 03-rough-design/
│   ├── background/
│   │   └── background_{timestamp}.png
│   ├── sidebar/
│   │   └── sidebar_{timestamp}.png
│   └── ... (one folder per layer)
├── 04-check/
│   ├── enhanced_layer_plan.json          # layout + 资源路径
│   ├── preview.html                      # 静态交互式预览页面
│   ├── preview_check_screenshot.png      # 网页截图
│   └── check_report.json
├── 05-refinement-preview/
│   └── preview_{timestamp}.png
├── 06-refinement-layers/
│   ├── background/
│   │   └── background_{timestamp}.png
│   └── ... (one folder per layer)
├── 07-output/
│   ├── preview.html                      # 最终交付网页预览
│   ├── final_preview.png
│   ├── layers/
│   │   ├── background.png
│   │   ├── sidebar.png
│   │   └── ... (clean names, no timestamps)
│   └── manifest.json
└── 08-variants/                    # 仅当 Phase 8 执行
    ├── submit_btn/
    │   ├── submit_btn_hover_{timestamp}.png
    │   ├── submit_btn_active_{timestamp}.png
    │   └── submit_btn_disabled_{timestamp}.png
    └── ... (one folder per control)
```

---

## 10. 依赖清单

```bash
pip install openai Pillow rembg
```

**已安装版本**（当前环境）：
- `openai` 2.32.0
- `Pillow` 12.2.0
- `rembg` 2.0.75（含 `onnxruntime` 1.24.4、`scikit-image` 0.26.0、`numpy` 2.4.4 等）

---

## 11. 增量更新（Incremental Update）

当用户在工作完成后请求修改时：

| 修改类型 | 重跑阶段 |
|---------|---------|
| 单图层修改 | Phase 3 + Phase 6（该图层） |
| 单状态添加 | Phase 8（该控件） |
| 纯样式变更（颜色/字体） | Phase 5 预览 + Phase 6 全图层 |
| 布局变更 | 受影响图层的 Phase 3 + Phase 4 + Phase 6 |

需读取 `07-output/manifest.json` 确定当前状态，只生成最小变更集。

---

*文档版本：2026-04-24 | 与 SKILL.md + 8 份 phase 文档 + 2 份指南同步*
