# FretPilot v2 — 文档索引

> 本目录收录 FretPilot / BandPilot 的产品 PRD、架构设计与 Mermaid 图。
> 文档按「产品需求（PRD）→ 架构设计（ARCH）→ 图表（Diagrams）」分层组织。

---

## 产品演进脉络

```
FretPilot v2（吉他 MIDI 修复）
  ├─ Stream Separation  — 低音 riff / 高音旋律分离（增量）
  ├─ Learning Loop      — 教材学习闭环（增量）
  └─ BandPilot          — 混合 MIDI 多轨（吉他 + 鼓）统一产品
        ├─ FretPilot   — 吉他 8 阶段修复
        └─ StickPilot  — 鼓 8 阶段修复（Quantize → … → Assemble）
```

前端经历了三轮迭代：v1（7 阶段/单轨/亮色）→ v2（8 阶段/Dark-first）→ **v3（当前）**。

---

## 一、产品 PRD（做什么）

| 文档 | 说明 | 状态 |
|------|------|------|
| [`BANDPILOT_PRD.md`](./BANDPILOT_PRD.md) | BandPilot 混合 MIDI → 多轨 .gp5 产品设计 | Draft |
| [`STREAM_SEPARATION_PRD.md`](./STREAM_SEPARATION_PRD.md) | 吉他声部分离 PRD（增量功能） | 已实现 |
| [`PRD-learning-loop.md`](./PRD-learning-loop.md) | 知识系统学习闭环 PRD | 已实现 |
| [`FRONTEND_REDESIGN_PRD_v3.md`](./FRONTEND_REDESIGN_PRD_v3.md) | 前端 v3 设计规格（**当前最新**） | 已实现 |
| [`FRONTEND_REDESIGN_PRD_v2.md`](./FRONTEND_REDESIGN_PRD_v2.md) | 前端 v2 PRD（8 阶段 + Dark-first） | ⚠️ 已被 v3 取代 |
| [`FRONTEND_PRD.md`](./FRONTEND_PRD.md) | 前端原始 PRD（7 阶段/单轨） | ⚠️ 已过时 |

## 二、架构设计（怎么做）

| 文档 | 说明 |
|------|------|
| [`STREAM_SEPARATION_ARCHITECTURE.md`](./STREAM_SEPARATION_ARCHITECTURE.md) | 声部分离技术方案 + 任务分解 |
| [`ARCH-learning-loop.md`](./ARCH-learning-loop.md) | 学习闭环系统设计 |
| [`FRONTEND_ARCHITECTURE.md`](./FRONTEND_ARCHITECTURE.md) | 前端整体架构（数据结构 / 调用流程 / 模块划分） |

## 三、Mermaid 图表（配套源文件）

| 图表 | 配套文档 | 说明 |
|------|----------|------|
| [`class-diagram.mermaid`](./class-diagram.mermaid) | FRONTEND_ARCHITECTURE §3.1 | 前端类图 |
| [`sequence-diagram.mermaid`](./sequence-diagram.mermaid) | FRONTEND_ARCHITECTURE §4.1 | 前端调用时序图 |
| [`stream-separation-class-diagram.mermaid`](./stream-separation-class-diagram.mermaid) | STREAM_SEPARATION_ARCHITECTURE | 声部分离类图 |
| [`stream-separation-sequence-diagram.mermaid`](./stream-separation-sequence-diagram.mermaid) | STREAM_SEPARATION_ARCHITECTURE | 声部分离时序图 |
| [`learning-loop-class-diagram.mermaid`](./learning-loop-class-diagram.mermaid) | ARCH-learning-loop | 学习闭环类图 |
| [`learning-loop-sequence-diagram.mermaid`](./learning-loop-sequence-diagram.mermaid) | ARCH-learning-loop | 学习闭环时序图 |

---

## 约定

- **命名**：`PRD-*.md` 为产品需求，`ARCH-*.md` 为架构设计，`*-class-diagram.mermaid` / `*-sequence-diagram.mermaid` 为配套图表。
- **版本演进**：被取代的文档在顶部标注 `⚠️ 已被 vN 取代` 并指向最新版；保留作历史记录，不删除。
- **图表维护**：Mermaid 源文件为 source of truth；架构文档内可内嵌副本，但修改时同步更新对应 `.mermaid` 文件。
