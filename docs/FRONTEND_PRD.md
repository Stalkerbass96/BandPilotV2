# FretPilot v2 前端重设计 PRD

> ⚠️ **已过时**：本文档写于"7-stage / 单轨 / 亮色 indigo"阶段。
> 后端已升级为 **8 阶段 pipeline + 声部分离双轨输出**，前端设计方向也调整为 **Dark-first**。
> 历史演进：v2（[`FRONTEND_REDESIGN_PRD_v2.md`](./FRONTEND_REDESIGN_PRD_v2.md)）→ **v3（最新）**：[`FRONTEND_REDESIGN_PRD_v3.md`](./FRONTEND_REDESIGN_PRD_v3.md)。

## 项目信息

| 字段 | 值 |
|------|-----|
| **项目名称** | fretpilot_frontend_redesign |
| **语言** | 中文 |
| **技术栈** | Vite + React 18 + MUI 5 + Tailwind CSS + Framer Motion + alphaTab |
| **原始需求** | FretPilot v2 全站前端重做：嵌入 alphaTab 实现浏览器内六线谱预览，全站视觉升级到 Notion/Linear 级别的现代简洁亮色风格，修复假进度条 bug，启用闲置的 Tailwind，补充动画与过渡 |

### 原始需求复述

用户要求对 FretPilot v2 吉他 MIDI 修复工具的前端进行**全站重做**。当前前端存在五个核心问题：零音乐可视化（无 Tab/谱面，必须导出 GP5 才能看结果）、MUI 默认蓝色外观无品牌感、无任何动画过渡、PipelineProgress 假进度条逻辑有 bug、Tailwind 配置了但完全没用。用户明确要求参考 Notion/Linear 的现代干净亮色风格，嵌入 alphaTab（原生支持 .gp5 渲染）在浏览器里直接看六线谱+标准谱，并追求高质量视觉。

---

## 产品定义

### Product Goals

1. **浏览器内实时可视化修复结果** — 修复完成后用户无需导出即可在 alphaTab 渲染的六线谱+标准谱中直接查看指法、节奏、articulation，消除"盲修"体验，将修复→预览的反馈闭环从分钟级降至秒级。

2. **建立 FretPilot 品牌视觉语言** — 以 Notion/Linear 为参考锚点，用 Tailwind 驱动的设计令牌系统替代 MUI 默认主题，实现统一、克制、有呼吸感的亮色 UI，使工具从"能用的 demo"升级为"想用的产品"。

3. **修复交互缺陷并补齐动效层** — 修复 PipelineProgress 假进度条逻辑 bug，为页面切换、加载、进度推进、结果出现等关键交互补充过渡动画，使全站体验连贯流畅，消除突兀的状态跳变。

### User Stories

**US-1（核心链路：上传→修复→看谱→导出）**
> 作为一个吉他手，我上传一个 AI 生成的 MIDI 文件，调整修复参数后运行 pipeline，修复完成后立即在页面上看到六线谱和标准谱预览，确认指法合理后一键导出 GP5，这样我不用在 FretPilot 和 Guitar Pro 之间来回切换。

**US-2（修复参数调优）**
> 作为一个音乐制作人，我在 Workbench 上拖动 fidelity 滑块和选择调弦后运行修复，看到 pipeline 各阶段的真实进度和每阶段的变更摘要（cleanup / rewrite / 7-stage），这样我能判断修复质量是否达标。

**US-3（Tab 预览与决策）**
> 作为一个吉他手，修复完成后我在 alphaTab 渲染的谱面上看到六线谱的指法分配、string/fret 信息和 articulation 标记（hammer-on / pull-off / palm mute 等），如果发现不合理我可以回到参数面板调整重跑，这样我能在导出前验证结果。

**US-4（导出与历史管理）**
> 作为一个用户，我在 Export 页面选择 GP5 或 Ample MIDI 格式导出，看到导出历史列表并可下载，这样我能管理多个版本的导出文件。

**US-5（LLM 配置）**
> 作为一个高级用户，我在 BYOK 页面配置 LLM API Key 并测试连接，确认后系统从 degraded 模式切换到 LLM active，这样修复 pipeline 能使用 LLM shadow rewrite 能力。

---

## 技术规范

### Requirements Pool

#### P0 — Must Have（核心体验，必须实现）

| ID | 需求 | 验收标准 |
|----|------|----------|
| P0-1 | **alphaTab 集成** — 在 WorkbenchPage 修复完成后嵌入 alphaTab 渲染器 | 修复完成后自动生成 GP5 → 下载 binary blob → 传入 alphaTab `api.load()` → 渲染六线谱+标准谱；支持缩放/滚动；Tab 区域高度 ≥400px，可折叠 |
| P0-2 | **全站视觉重设计 — 设计令牌系统** | 用 Tailwind config 定义品牌色板、间距、圆角、阴影、字体令牌；MUI theme 的 palette/typography 引用令牌变量；消除硬编码 `#1a73e8` 蓝色 |
| P0-3 | **全站视觉重设计 — Layout 导航栏** | 替换 MUI AppBar 为自定义导航栏：左侧 logo + 品牌名、中间导航链接（active 状态下划线指示）、右侧用户头像+下拉菜单；参考 Linear 侧边栏式导航或顶部极简导航 |
| P0-4 | **WorkbenchPage 核心体验重设计** | 左右分栏布局：左侧参数面板（fidelity slider + tuning selector + run button），右侧结果区（alphaTab Tab + cleanup/rewrite 摘要卡片 + 变更表格）；修复运行中显示真实进度 |
| P0-5 | **PipelineProgress 修复** | 修复假进度条 bug：当前 `idx < PIPELINE_STAGES.length` 恒为 true 导致所有 stage 同时显示完成；改为基于真实阶段推进的逐个点亮，active stage 有脉冲动画 |
| P0-6 | **ImportPage 重设计** | UploadZone 升级为大型拖拽区域（参考 Linear 的空状态设计），项目列表改为卡片网格或列表行 hover 效果；上传时有进度反馈 |
| P0-7 | **ExportPage 重设计** | 导出格式卡片视觉升级，导出历史列表优化；导出 GP5 后可直接在页面内 alphaTab 预览（复用 alphaTab 组件） |
| P0-8 | **LoginPage / RegisterPage 重设计** | 居中卡片表单升级为全屏分栏布局（左品牌插画/介绍 + 右表单）或极简居中表单，参考 Linear 登录页 |
| P0-9 | **ByokPage 重设计** | 配置表单视觉升级，状态指示器（degraded vs active）用品牌色区分 |

#### P1 — Should Have（体验增强，应该实现）

| ID | 需求 | 验收标准 |
|----|------|----------|
| P1-1 | **页面切换过渡动画** | 使用 Framer Motion `AnimatePresence` 实现路由切换时的 fade/slide 过渡（150-250ms），消除页面硬切 |
| P1-2 | **加载状态动画** | 骨架屏（Skeleton）替代 CircularProgress 旋转图标，用于 ImportPage 项目列表、WorkbenchPage 项目加载、ExportPage 加载 |
| P1-3 | **结果出现动画** | 修复完成后 cleanup/rewrite 摘要卡片和 alphaTab Tab 区域以 stagger 依次淡入（Framer Motion `staggerChildren`） |
| P1-4 | **暗色模式预留** | 设计令牌系统使用 CSS 变量，MUI theme 支持 `mode: 'dark'` 切换；本期不实现暗色切换 UI，但令牌结构预留 |
| P1-5 | **响应式布局** | WorkbenchPage 左右分栏在 <1024px 时切换为上下堆叠；导航栏在 <768px 时折叠为汉堡菜单；alphaTab 区域宽度自适应 |
| P1-6 | **微交互反馈** | 按钮 hover/press 缩放、卡片 hover 阴影提升、拖拽区域 hover 边框动画 |
| P1-7 | **错误状态视觉优化** | Alert 组件统一定制为品牌风格，错误/警告/成功状态用品牌色系而非 MUI 默认红黄绿 |

#### P2 — Nice to Have（增强功能，可选实现）

| ID | 需求 | 验收标准 |
|----|------|----------|
| P2-1 | **alphaTab 音频回放** | 启用 alphaTab 内置播放器（`playerOptions`），用户可在浏览器内试听修复后的 MIDI 音频 |
| P2-2 | **指板可视化** | 在 alphaTab 旁或下方增加吉他指板图组件，高亮当前选中音符在指板上的位置 |
| P2-3 | **Onboarding 引导** | 首次登录用户看到 3-4 步功能引导（上传→修复→看谱→导出），使用 Framer Motion 驱动的 tooltip 覆盖层 |
| P2-4 | **变更 diff 高亮** | 在 alphaTab 谱面上高亮被 LLM rewrite 或 pipeline 修改的音符（基于 RepairReport 的 TransformationRecord） |
| P2-5 | **键盘快捷键** | WorkbenchPage 支持 `Space` 运行修复、`Cmd/Ctrl+E` 跳转导出等快捷键 |

---

### UI Design Draft

#### 设计语言描述

参考 **Notion** 和 **Linear** 的视觉语言，提取以下核心元素：

**Notion 元素：**
- 极致克制的配色：白底 + 浅灰分隔线 + 黑色文字，色彩仅用于状态指示
- 大量留白和呼吸感：组件间距充裕，不拥挤
- 干净的卡片容器：浅阴影 + 细边框，无重装饰
- 文字层级清晰：标题粗重、正文轻盈、辅助文字浅灰

**Linear 元素：**
- 精准的间距系统：8px 基准网格
- 微妙的交互反馈：hover 时背景色微变 + 边框色过渡
- 现代感的表单控件：圆角输入框、聚焦时品牌色边框光晕
- 紧凑高效的信息密度：列表行不高但信息完整

**品牌差异化：**
- FretPilot 作为音乐工具，主色调应传达"专业感 + 创造力"，建议使用深靛蓝/紫罗兰系而非通用蓝色
- 强调色用于关键操作（Run Repair / Export）和活跃状态指示

#### 配色方案（亮色为主）

```
设计令牌（Tailwind config + CSS 变量）：

背景层级：
  --bg-canvas:     #FFFFFF    /* 页面底色 */
  --bg-surface:    #F9FAFB    /* 卡片/面板背景 */
  --bg-elevated:   #FFFFFF    /* 悬浮卡片/弹窗 */
  --bg-subtle:     #F3F4F6    /* 次级背景/hover 态 */

文字层级：
  --text-primary:   #111827   /* 主文字 */
  --text-secondary: #6B7280   /* 辅助文字 */
  --text-tertiary:  #9CA3AF   /* 占位/禁用 */

品牌色：
  --brand-primary:   #6366F1  /* 靛蓝紫 — 主操作按钮、active 状态 */
  --brand-primary-hover: #4F46E5
  --brand-accent:    #8B5CF6  /* 紫罗兰 — 强调/装饰 */

语义色：
  --semantic-success: #10B981  /* 修复完成 */
  --semantic-warning: #F59E0B  /* degraded 模式 */
  --semantic-error:   #EF4444  /* 错误 */
  --semantic-info:    #3B82F6   /* 信息提示 */

边框与分隔：
  --border-default:  #E5E7EB
  --border-hover:    #D1D5DB
  --border-active:   #6366F1
```

#### 关键页面布局描述

**1. Layout（全局导航壳）**

```
┌─────────────────────────────────────────────────┐
│  🎸 FretPilot   Import  BYOK          👤 user ▾  │  ← 顶部导航栏 (h:56px)
├─────────────────────────────────────────────────┤
│                                                 │
│                 <页面内容>                       │  ← max-w:1200px, mx:auto, py:32px
│                                                 │
└─────────────────────────────────────────────────┘
```
- 导航栏：白底 + 底部 1px 分隔线，active 链接下方 2px 品牌色指示条
- 品牌 logo：吉他图标 + "FretPilot" 文字，品牌色
- 用户区：邮箱文字 + 头像 + 下拉菜单（Logout）

**2. WorkbenchPage（核心页面）— 左右分栏**

```
┌──────────────────────────────────────────────────────────┐
│  Repair Workbench                                         │
│  Project: tokyo_midnight.mid                              │
├──────────────┬───────────────────────────────────────────┤
│              │                                           │
│  参数面板     │  alphaTab 六线谱+标准谱                   │
│  ┌────────┐  │  ┌─────────────────────────────────────┐  │
│  │Fidelity│  │  │  ═════════════════════════════════  │  │
│  │ ──●──  │  │  │  T |-----------------|-------------| │  │
│  └────────┘  │  │  A |-----------------|-------------| │  │
│  Tuning ▾    │  │  B |-------0---------|-------------| │  │
│              │  │  G |-----0-----------|-------------| │  │
│  [Run Repair]│  │  D |-----------------|-------------| │  │
│              │  │  E |-----------------|-------------| │  │
│  ──────────  │  └─────────────────────────────────────┘  │
│  Cleanup     │                                           │
│  ▸ Tuning    │  ┌────────────┬────────────┐              │
│  ▸ Tempo     │  │ Cleanup    │ Rewrite    │              │
│  ▸ Velocity  │  │ Summary    │ Summary    │              │
│              │  └────────────┴────────────┘              │
│              │                                           │
│              │  [Transformation Table]                  │
│              │  [Go to Export →]                        │
└──────────────┴───────────────────────────────────────────┘
   左栏 320px              右栏 flex-1
```
- 修复未运行时：右栏显示空状态提示（"运行修复以查看谱面预览"）
- 修复运行中：右栏显示 PipelineProgress + 骨架屏占位
- 修复完成后：alphaTab + 摘要卡片 stagger 淡入

**3. ImportPage**

```
┌─────────────────────────────────────────────┐
│  Import MIDI                                │
│                                             │
│  ┌─────────────────────────────────────┐    │
│  │         🎵                          │    │
│  │    拖放 MIDI 文件到此处               │    │
│  │    或点击浏览                        │    │
│  │    支持 .mid / .midi (max 20MB)     │    │
│  └─────────────────────────────────────┘    │
│                                             │
│  Your Projects                              │
│  ┌─────────────────────────────────────┐    │
│  │ 🎸 tokyo_midnight  [repaired]  →  │    │
│  │    tokyo_midnight.mid · metal       │    │
│  ├─────────────────────────────────────┤    │
│  │ 🎸 solo_riff       [imported]   →  │    │
│  │    solo_riff.mid · unknown           │    │
│  └─────────────────────────────────────┘    │
└─────────────────────────────────────────────┘
```

**4. ExportPage**

```
┌─────────────────────────────────────────────┐
│  Export                                     │
│  Export repaired project "tokyo_midnight"   │
│                                             │
│  ┌──────────────┐  ┌──────────────┐         │
│  │ 📄 GP5       │  │ 🎵 Ample MIDI│         │
│  │ Notation     │  │ Performance  │         │
│  │ [Export GP5] │  │ [Export MIDI]│         │
│  └──────────────┘  └──────────────┘         │
│                                             │
│  Export History                             │
│  ┌─────────────────────────────────────┐    │
│  │ 📄 gp5 · 1,247 notes · 2min ago [↓]│    │
│  ├─────────────────────────────────────┤    │
│  │ 🎵 ample_midi · 1,247 notes · [↓]  │    │
│  └─────────────────────────────────────┘    │
└─────────────────────────────────────────────┘
```

---

### alphaTab 集成方案

#### 集成场景

alphaTab 在 **WorkbenchPage** 修复完成后自动渲染，以及 **ExportPage** 导出 GP5 后可选预览。

#### 数据流

```
用户点击 "Run Repair"
  │
  ▼
POST /api/projects/:id/repair  (同步返回 RepairResponse)
  │  → 后端执行 7-stage pipeline，保存 ir.json
  ▼
GET /api/projects/:id/report   (获取 RepairReport)
  │  → 展示 cleanup/rewrite 摘要 + 变更表格
  ▼
POST /api/projects/:id/export  (format: "gp5")
  │  → 后端 GP5Exporter 生成 output.gp5，创建 ExportRecord
  ▼
GET /api/projects/:id/exports/:exportId/download  (responseType: blob)
  │  → 获取 .gp5 二进制文件 (ArrayBuffer)
  ▼
alphaTab api.load(arrayBuffer)
  │  → alphaTab 解析 .gp5 格式
  ▼
渲染六线谱 + 标准谱到 DOM 容器
```

#### 技术要点

1. **依赖安装**：`npm install @coderline/alphatab`（alphaTab 官方 npm 包）
2. **组件封装**：创建 `<TabViewer />` 组件，接收 `projectId` prop，内部管理 GP5 生成→下载→加载的生命周期
3. **API 扩展**：在 `api/client.ts` 中新增 `projectsApi.generateGp5(projectId)` 方法 — 调用 export 接口生成 GP5 并返回 exportId，再调用 download 获取 blob
4. **alphaTab 初始化**：
   ```typescript
   import { AlphaTabApi } from "@coderline/alphatab";
   const api = new AlphaTabApi(containerEl, {
     core: { engine: "html5" },
     display: { layoutMode: "Horizontal" },
   });
   api.load(blob);  // blob = GP5 ArrayBuffer
   ```
5. **性能考量**：
   - GP5 生成+下载是额外网络请求（修复已完成，ir.json 已在磁盘），预计 <2s
   - alphaTab 渲染大型谱面时可能有延迟，需显示加载骨架屏
   - 可考虑修复完成后自动触发 GP5 生成（并行于 report 获取），减少用户等待
6. **生命周期管理**：组件卸载时调用 `api.destroy()` 释放资源，防止内存泄漏
7. **错误处理**：GP5 生成失败（如 ir.json 不存在）或 alphaTab 解析失败时显示降级提示

#### 复用策略

`<TabViewer />` 组件同时用于：
- WorkbenchPage：修复完成后自动渲染（只读预览）
- ExportPage：导出 GP5 后点击"预览"按钮渲染（可选）

---

### Open Questions（待确认问题）

1. **alphaTab 生成时机**：修复完成后是否自动触发 GP5 生成+渲染，还是需要用户手动点击"预览谱面"按钮？自动触发会增加 1 次网络请求但体验更流畅；手动触发更可控但多一步操作。**建议自动触发**（修复成功即生成 GP5 并渲染）。

2. **导航栏样式方向**：顶部水平导航栏（类似 Notion）还是左侧垂直侧边栏（类似 Linear）？用户说参考两者，但两者导航模式不同。**建议顶部导航**（FretPilot 页面数量少，6 个页面不需要侧边栏）。

3. **品牌主色调确认**：PRD 建议 `#6366F1`（靛蓝紫 / Tailwind indigo-500），是否认可？或者用户有其他品牌色偏好？此色值偏现代科技感，与吉他音乐工具的调性是否匹配？

4. **alphaTab 是否启用音频回放**：alphaTab 内置 MIDI 播放器，启用后用户可在浏览器试听修复结果。这属于 P2 功能，是否本期实现？启用会增加包体积（含 soundfont）。

5. **Tailwind 与 MUI 共存策略**：当前 Tailwind 已配置但 `preflight: false`（不覆盖 MUI baseline）。重设计后是否继续 MUI + Tailwind 混用，还是逐步用 Tailwind 替代 MUI 组件？**建议混合策略**：布局/间距/颜色用 Tailwind，复杂组件（Select/Slider/Table）继续用 MUI 但通过 theme 定制融入品牌风格。

6. **后端 API 是否需要新增端点**：当前 alphaTab 预览需要"先 export 再 download"两步调用。是否需要在后端新增 `GET /api/projects/:id/preview` 端点直接返回 GP5 blob（跳过 ExportRecord 持久化）？这能减少一次请求并避免预览产生的"幽灵导出记录"。**如不新增**，前端需在 export 后静默下载并在 UI 上区分"预览用导出"和"用户主动导出"。

7. **RegisterPage 是否重设计**：需求提到"全站重做"，RegisterPage 与 LoginPage 结构类似，是否同步重设计？**建议同步**。
