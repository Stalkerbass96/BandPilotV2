# FretPilot v2 — 前端重构 v2 PRD（对齐后端 8 阶段 + Dark-first 视觉重构）

> ⚠️ **已被 v3 取代**：后续基于"后端全部 API 能力 + 用户旅程"重新设计了 v3 规格（Linear/Ableton/Figma 风格）。请以 [`FRONTEND_REDESIGN_PRD_v3.md`](./FRONTEND_REDESIGN_PRD_v3.md) 为准；本文保留作为历史记录。
>
> 文档类型：简单 PRD（增量功能）
> 作者：Bob（AI 工作搭子）
> 需求来源：用户 Steven
> 状态：第一批已完成，第二批待前端专家团评审
> 上游文档：`docs/FRONTEND_PRD.md`（已标记过时）

---

## 1. 项目信息

| 项 | 内容 |
| --- | --- |
| Language | 中文 |
| Project Name | `frontend_redesign_v2` |
| 技术栈 | Vite + React 18 + MUI 5 + Tailwind CSS + Framer Motion + alphaTab（现有栈，不引入新框架） |
| 原始需求复述 | 用户 Steven 反馈：当前前端"丑、不够具备美感"。经诊断发现两层问题——(1) 前端与后端逻辑脱节（7 阶段 vs 后端 8 阶段、alphaTab 只渲染单轨 vs 后端声部分离产双轨）；(2) 视觉为通用 SaaS 后台风格，与"吉他 MIDI 修复工具"的产品气质不符。需分两批修复。 |

---

## 2. 产品定义

### 2.1 产品目标（Product Goals）

1. **前端与后端逻辑对齐**：PipelineProgress 显示 8 阶段（含 Stream Separation）；alphaTab 渲染声部分离后的 Lead + Rhythm 双轨，用户不再看不到 Rhythm 谨。
2. **建立"录音棚/琴房"视觉语言**：Dark-first 主题，琥珀/铜色品牌色（呼应琴弦金属 + 音孔玫瑰木），摆脱 Tailwind indigo 模板感，使工具从"能用的 demo"升级为"吉他手想用的音频工作台"。
3. **声部分离可视化**：把文字列表升级为 pitch-vs-measure 分层图，一眼看懂"哪里被拆开、拆得准不准"——这是产品最独特的差异化 feature。

### 2.2 成功标准（可度量）

- 修复后进度条显示 8 个阶段，且 `Separation` 阶段在 `Voice` 与 `Fingering` 之间。
- 声部分离项目在 alphaTab 中同时显示 Lead + Rhythm 两条谱。
- Dark-first 主题切换可用，配色 token 由 CSS 变量驱动，无硬编码 `rgba()` 残色。
- 声部分离结果以 pitch-vs-measure 图展示，低音 riff 与高音 melody 用不同颜色区分。

### 2.3 用户故事（User Stories）

1. 作为吉他手，我修复完成后在 alphaTab 中同时看到 Lead 轨和 Rhythm 轨两条谱，这样我能分别查看旋律与低音 riff。
2. 作为吉他手，我看到 pipeline 进度条有 8 个阶段，其中 Separation 阶段能告诉我"这里拆出了双轨"，这样我知道声部分离发生了。
3. 作为吉他手/制作人，我在深色界面下操作（对标 DAW 心智），谱面是视觉中心，这样我感觉在用专业音频工具而非管理后台。
4. 作为进阶用户，我看到声部分离的 pitch-vs-measure 可视化图，一眼判断分离是否准确，低置信度段有提示。

---

## 3. 需求池（Requirements Pool）

### 第一批 — P0 Must Have（功能对齐，已完成）

| ID | 需求 | 验收标准 | 状态 |
|----|------|----------|------|
| P0-1 | **PipelineProgress 8 阶段** | `PIPELINE_STAGES` 加入 `{ name: "separation", label: "Separation" }`，顺序与后端 `pipeline.py` 一致（Voice 之后、Fingering 之前） | ✅ 已完成 |
| P0-2 | **WorkbenchPage STAGE_COUNT** | `STAGE_COUNT = 8`，timer 逻辑与 comment 同步 | ✅ 已完成 |
| P0-3 | **alphaTab 双轨渲染** | `useAlphaTab.ts` 修正过时注释，`api.load(scoreData)` 不传 trackIndexes 即渲染全部轨；`TabViewer` 容器 `minHeight` 120→240 容纳双轨 | ✅ 已完成 |

### 第二批 — P1 Should Have（Dark-first 视觉重构，待专家团）

| ID | 需求 | 验收标准 |
|----|------|----------|
| P1-1 | **设计 token 重做（Dark-first）** | `tokens.ts` dark 接入 theme + CSS 变量驱动；背景深蓝黑 `#0E1116` / 面板 `#161A20`；品牌色琥珀 `#E8A24B`；消除所有硬编码 `rgba()` |
| P1-2 | **alphaTab 深色主题** | alphaTab 定制深色渲染主题，谱面成为产品中心舞台；双轨上下排布 |
| P1-3 | **声部分离可视化** | 新增 pitch-vs-measure 分层图组件：横轴小节、纵轴音高、低音琥珀 / 高音青 `#4FD1C5`、分割线标 `split_pitch`；取代 `SeparationSummary` 文字列表 |
| P1-4 | **Pipeline 真实进度 timeline** | 8 阶段 timeline，每阶段显示真实产出（如 Separation: "2 轨 · 5 混合段"）；需后端补进度上报通道（SSE 或 polling） |
| P1-5 | **首页 hero + 信息架构** | Import 首页 hero 式首屏；BYOK 降为设置入口而非顶级导航 |
| P1-6 | **字体与品牌标题** | 加一个 display 字体做品牌标题，与 Inter 正文形成对比 |
| P1-7 | **组件库分层 + Storybook** | Summary 卡片等去重；建立设计系统文档 |

### P2 — Nice to Have（增强功能，可选）

| ID | 需求 | 验收标准 |
|----|------|----------|
| P2-1 | **dark mode 切换 UI** | 顶栏主题切换按钮，`localStorage` 持久化 |
| P2-2 | **alphaTab 音频回放** | 启用 alphaTab 内置播放器，浏览器内试听修复结果 |
| P2-3 | **变更 diff 高亮** | alphaTab 谱面上高亮被 pipeline 修改的音符 |

---

## 4. 设计方向：Dark-first「录音棚/琴房」美学

### 4.1 设计判断

产品本质是"吉他 MIDI → 六线谱的修复/重建工具"，目标用户是吉他手/制作人，心智锚点是 DAW（Ableton / Guitar Pro / Bias FX）——深色、沉浸、以谱面为中心。当前 UI 是"上传文件的管理后台"（indigo + 白卡片 + Inter），与产品气质相反。

### 4.2 配色方案

| Token | 现在（亮色 indigo） | 目标（Dark-first 琥珀） |
|------|------|------|
| 背景 canvas | `#FFFFFF` | `#0E1116` |
| 背景 surface | `#F9FAFB` | `#161A20` |
| 背景 elevated | `#FFFFFF` | `#1C2128` |
| 品牌色 primary | `#6366F1`（Tailwind indigo-500） | `#E8A24B`（琥珀/铜色） |
| 品牌色 hover | `#4F46E5` | `#D4882E` |
| 声部 Lead | — | `#4FD1C5`（冷青，高音 melody） |
| 声部 Rhythm | — | `#E8A24B`（琥珀，低音 riff） |
| 文字 primary | `#111827` | `#F0F2F5` |
| 文字 secondary | `#6B7280` | `#9DA5B4` |

### 4.3 关键页面改造

- **WorkbenchPage**：谱面成为中心舞台（alphaTab 深色主题，双轨上下排布）；声部分离结果用 pitch-vs-measure 图替代文字列表
- **ImportPage**：hero 式首屏，强调"拖入 MIDI，得到可弹的六线谱"
- **Layout**：深色顶栏，BYOK 降为设置入口
- **LearningPage**：统计数据加图表，降低表格信息密度

---

## 5. 与原 PRD 差异说明

| 原 `FRONTEND_PRD.md` | 本 PRD | 原因 |
|--------|--------|------|
| 7-stage pipeline | **8-stage**（加 Separation） | 后端已加 `StreamSeparationStage` |
| alphaTab 渲染单轨 | **渲染全部轨**（双轨） | 后端声部分离产 `[Lead, Rhythm]` |
| 亮色为主，indigo 品牌 | **Dark-first，琥珀/铜色** | 产品是音频工作台，对标 DAW 心智；indigo 模板感强 |
| P0-5 修假进度条 bug | 假进度条 bug 已修（三态模型），现问题是**阶段数不对** | 之前已修逻辑，本次补阶段 |
