# FretPilot v2 — 前端重构 v3 设计规格

> 2026-08-19 · 基于后端全部 API 能力 + 用户旅程重新设计
> 参考：Linear（侧边栏+信息密度）、Ableton（深色工作台）、Figma（面板布局）

---

## 1. 用户旅程

```
Import MIDI
  → 后端自动分析（track detection + style detection + tuning auto-detect）
  → 项目卡片展示检测结果（style、track count、guitar track role）
  → 进入 Workbench
    → 左面板：项目信息 + 修复配置（fidelity 语义化 + tuning 选择 + KB/LLM 状态）
    → 点击 Run Repair
    → 8 阶段进度（每阶段显示真实产出）
    → 谱面预览（alphaTab 双轨，Lead/Rhythm 标签页切换）
    → 声部分离可视化（pitch-vs-measure 图嵌入谱面区）
    → 变更报告（transformations table）
    → Go to Export
      → 格式选择（GP5 / Ample MIDI，附说明）
      → 预览 + 下载
```

## 2. 信息架构

```
Sidebar (240px, collapsible)
  ├── 🎸 FretPilot (logo)
  ├── Import        (/)          — MIDI 上传 + 项目列表
  ├── Workbench     (/projects/:id) — 修复工作台（核心）
  ├── Learning      (/learning)  — KB 学习闭环
  └── Settings      (/settings)  — BYOK + 偏好

Main Content (flex-1)
```

## 3. 页面设计

### 3.1 Layout — 侧边栏导航

- 固定左侧 240px sidebar，深色 `#0E1116`，右侧主内容区 `#161A20`
- Sidebar：logo 顶部，nav items 中间，user + settings 底部
- 可折叠至 56px（icon-only）
- 移动端：bottom tab bar 或 drawer

### 3.2 ImportPage — 上传 + 项目列表

- 顶部 hero 区：大标题 + 副标题，gradient 背景
- 上传区：大 drop zone，拖拽 + 点击
- 项目卡片网格：每张卡片显示
  - 标题 + 源文件名
  - **检测结果**：style label（chip）、track count、guitar track role + confidence
  - 状态：imported / repaired（chip）
  - degraded mode 警告
  - hover：lift + brand border + shadow
- 卡片点击 → Workbench

### 3.3 WorkbenchPage — 核心工作台

三栏布局（可折叠）：

**左面板（280px）— 配置 + 状态**
- 项目信息卡：标题、源文件、检测到的 style、track 列表（role + confidence）
- 修复配置：
  - **Fidelity 滑块**（0-1）带语义标签：
    - 0.0-0.25: "Aggressive — 强力修复，16th note 网格"
    - 0.25-0.5: "Balanced — 平衡修复"
    - 0.5-0.75: "Preserving — 保留 MIDI 细节"
    - 0.75-1.0: "Minimal — 最小干预，32nd note 网格"
  - **Tuning 选择器**：下拉，含 "Auto-detect" + 12 种 tuning profile
    - 每项显示 display_name + string_count
  - **LLM 状态**：Active / Degraded（chip）+ 链接到 Settings
  - **KB 版本**：当前 active version + style coverage
- Run Repair 按钮（大，品牌色，full width）

**中间区（flex-1）— 谱面 + 进度**
- 顶部：Pipeline 进度条（8 阶段水平 stepper，每阶段完成时显示产出数）
- 修复中：骨架屏
- 修复完成：
  - alphaTab 谱面（全宽，深色主题）
  - 双轨时显示 Lead / Rhythm 标签页切换
  - 声部分离可视化图（pitch-vs-measure）嵌入谱面下方

**右面板（320px，可折叠）— 结果**
- Cleanup 摘要（tuning used、tempo dedup、out-of-range、velocity、overlaps）
- Rewrite 摘要（deletions、transpositions、reasons）
- Separation 摘要（segment count、lead/rhythm note count、confidence）
- 变更表格（前 50 条，stage + before→after + confidence + reason）
- Export 按钮

### 3.4 ExportPage — 导出

- 两个大格式卡片（GP5 / Ample MIDI），各附详细说明
- 导出后：alphaTab 预览 + 下载按钮
- 导出历史列表

### 3.5 LearningPage — KB 学习

- 上传 GP tabs（拖拽）
- 选项：style override、auto-promote
- 结果：per-style stats（图表化）+ derived priors（可视化）
- KB 版本管理：版本列表、active badge、rollback、diff

### 3.6 SettingsPage — BYOK + 偏好

- LLM 配置（provider、api_key、base_url、model）
- 测试连接
- 状态指示器

## 4. 设计 Token

### 配色（Dark-first）

| Token | 值 | 用途 |
|-------|-----|------|
| canvas | `#0B0E13` | sidebar 背景（比 surface 更深） |
| surface | `#11161E` | 主内容区背景 |
| elevated | `#1A2029` | 卡片/面板背景 |
| subtle | `#222B36` | 次级背景/hover |
| brandPrimary | `#E8A24B` | 琥珀品牌色 |
| brandHover | `#D4882E` | hover 态 |
| lead | `#4FD1C5` | Lead 轨冷青 |
| rhythm | `#E8A24B` | Rhythm 轨琥珀 |
| success | `#34D399` | |
| warning | `#FBBF24` | |
| error | `#F87171` | |
| info | `#60A5FA` | |
| textPrimary | `#F0F2F5` | |
| textSecondary | `#9DA5B4` | |
| textTertiary | `#6B7280` | |
| borderDefault | `#2D3239` | |
| borderHover | `#3D4451` | |
| borderActive | `#E8A24B` | |

### 间距

- 基准 4px，组件间距 16px，区块间距 24px，页面 padding 32px
- sidebar: 240px (expanded) / 56px (collapsed)
- workbench 左面板: 280px / 右面板: 320px

### 圆角

- card: 12px
- button: 8px
- chip: 6px
- input: 8px

### 字体

- 正文: Inter 400/500
- 标题: Inter 600/700/800
- 数字/代码: Inter (tabular nums)
