# PRD — FretPilot 知识系统学习闭环

> **文档状态**: Draft v1.0
> **作者**: Xu（产品经理）
> **日期**: 2026-08-17
> **项目**: FretPilot v2 — 知识系统学习闭环（Learning Loop）

---

## 1. 项目信息

| 字段 | 值 |
|------|-----|
| **Language** | 中文 |
| **Programming Language** | Python 3.11+（后端 pipeline）、TypeScript（前端可视化） |
| **Project Name** | `fretpilot_learning_loop` |
| **原始需求** | 构建完整的学习闭环：从优质 GTP/GP 谱子导出 MIDI，经 Pipeline 还原为 GTP，与原始谱子对比评估偏差，并从专业谱子中学习指法规律以更新 KB2 priors |

### 需求复述

当前 FretPilot 输出的 GP5 谱子指法和弦选择不贴近真实人类演奏。KB2 priors（`open_string_bias`、`hand_position_stability` 等）是手工编写的静态权重，没有从真实专业谱子中学习。

Steven 的核心诉求：**构建一个完整的学习闭环**。通过用户提供的 2072 个吉他谱文件作为优质数据源，执行 `GTP/GP → MIDI 导出 → Pipeline 还原 → 对比评估` 流程来量化偏差。进一步从专业谱子中提取指法规律，更新知识库，让系统逐步学会"正确的编曲方式"。后续可扩充互联网爬取的数据。

**核心产品哲学**：脏 MIDI 只是参考。系统不是在"修复" MIDI，而是用正确的编曲方式、正确的分轨、正确的把位、正确的和弦、正确的 articulation 去**贴近**这个 MIDI——让创作出来的正确的东西无限贴近脏 MIDI。

---

## 2. 产品目标

### Goal 1: 建立可量化的评估基准线

> 将"指法质量"从主观感觉变成可测量、可追踪的数字指标。通过 2072 个专业谱子的 round-trip 对比，建立 baseline 准确率，让每一次 KB 调整的效果都可验证。

**衡量标准**: 对 ≥1587 个可解析谱子（GP3/GP4/GP5）完成全量 round-trip 评估，产出各指标的 baseline 数值。

### Goal 2: 实现从数据到知识的自动提取

> 从专业谱子中自动统计指法规律（弦选择偏好、把位分布、和弦指型频率等），将手工 priors 升级为经验 priors（`provenance.source_type = "empirical"`），并验证更新后准确率有提升。

**衡量标准**: 至少 3 个 KB2 风格的 priors 从 `hand_authored` 升级为 `empirical`，且对应风格的评估指标有可测量的提升。

### Goal 3: 构建可持续运转的学习飞轮

> 闭环不是一次性任务，而是一个可重复运行的系统：加入新数据 → 跑评估 → 提取知识 → 更新 KB → 再跑评估 → 验证提升。每次迭代都有版本追踪和回滚能力。

**衡量标准**: 支持 `知识快照版本管理`，每次 KB 更新生成新 snapshot_version，可对比任意两个版本之间的指标变化。

---

## 3. 用户故事

### Story 1: 评估当前系统表现
> 作为 Steven（产品创造者），我想对一批专业谱子跑 round-trip 评估，**以便**知道当前系统在弦选择、品选择、把位等方面的准确率到底是多少，找到最差的短板。

### Story 2: 从专业谱子学习指法规律
> 作为 Steven，我想系统自动从专业 GP 谱子中统计"真实吉他手是怎么选弦选品的"，**以便**用数据驱动的 priors 替代我手工拍脑袋写的权重。

### Story 3: 验证知识库更新的效果
> 作为 Steven，我想在更新 KB2 priors 后立即重新跑评估，**以便**对比更新前后的指标变化，确认调整是正向的还是负向的。

### Story 4: 定位具体失败案例
> 作为 Steven，我想查看准确率最低的谱子和具体偏差位置（哪个小节、哪个音符的弦/品选错了），**以便**手动分析原因并指导下一步优化方向。

### Story 5: 扩充数据源
> 作为 Steven，我想后续从互联网爬取更多谱子加入数据池，**以便**持续扩大学习样本量，覆盖更多风格和技巧组合。

---

## 4. 需求池

### P0 — 最小可用闭环（Must Have）

> 目标：跑通 `GP 谱子 → MIDI → Pipeline → GP5 → 对比评估` 全链路，产出第一批 baseline 数字。

| ID | 需求 | 描述 | 验收标准 |
|----|------|------|----------|
| P0-1 | **GP 谱子解析器** | 用 PyGuitarPro 的 `gp.parse()` 读取 GP3/GP4/GP5 文件，提取每个音符的 `string`/`fret`/`pitch`/`measure`/`beat` 作为 ground truth | 能解析 ≥1587 个 GP3/GP4/GP5 文件；输出结构化 `GroundTruthTab` 对象 |
| P0-2 | **GP → MIDI 导出** | 将 GP 谱子导出为 MIDI 文件（用 PyGuitarPro 写 MIDI，或用 Guitar Pro 软件批量导出） | 导出的 MIDI 能被 `load_midi()` 正常解析为 `NormalizedTimeline` |
| P0-3 | **Pipeline 还原** | 将导出的 MIDI 送入 `RepairPipeline.execute()`，产出重建后的 `GuitarProjectIR` | Pipeline 正常运行无异常，IR 中每个音符有 `string`/`fret` 赋值 |
| P0-4 | **音符对齐器** | 将 ground truth 谱子和重建 IR 的音符按 `measure` + `beat` + `pitch` 对齐，建立一一对应关系 | 对齐率 ≥95%（允许少量因 tie/split 导致的错位） |
| P0-5 | **偏差计算引擎** | 对每个对齐音符对，比较 `string`/`fret`/`hand_position`，计算各项 match rate | 输出 per-file 和 per-style 的指标 JSON |
| P0-6 | **批量评估脚本** | CLI 工具：`python -m fretpilot.elearning.evaluate --input-dir <谱子目录> --output <报告路径>` | 支持单文件和批量目录；输出结构化 JSON + 控制台摘要 |

### P1 — 知识提取与 KB 更新（Should Have）

> 目标：从专业谱子中学习指法规律，更新 KB2 priors，验证提升。

| ID | 需求 | 描述 | 验收标准 |
|----|------|------|----------|
| P1-1 | **指法规律统计器** | 从 ground truth 谱子中统计：弦选择分布、把位使用频率、和弦指型频率、open string 使用率、string skip 模式 | 按风格分组输出统计报告 |
| P1-2 | **Priors 反推引擎** | 从统计数据反推 KB2 priors 权重（如 `open_string_bias` 从实际 open string 使用率推导） | 输出新的 priors dict，`provenance.source_type = "empirical"` |
| P1-3 | **KB 快照版本管理** | 每次更新生成新 `snapshot_version`，保留旧版本；支持回滚到任意版本 | `KnowledgeRegistry` 支持加载指定版本；版本间可 diff |
| P1-4 | **A/B 评估对比** | 用旧版 KB 和新版 KB 分别跑全量评估，自动对比指标变化 | 输出 before/after 指标 delta 表；标注提升/退化 |
| P1-5 | **KB 写入器** | 将新的 empirical priors 写回 `kb2_performance.json`，更新 `provenance` 和 `evaluation` 字段 | 写入的 JSON 通过 `KnowledgeRegistry` 验证可正常加载 |

### P2 — 批量评估增强与数据扩充（Nice to Have）

> 目标：大规模评估的可视化和持续数据补充。

| ID | 需求 | 描述 |
|----|------|------|
| P2-1 | **可视化报告面板** | Web UI 展示评估结果：风格雷达图、指标趋势线、失败案例热力图 |
| P2-2 | **失败案例钻取** | 点击低分谱子查看逐音符对比视图（ground truth vs 重建，高亮偏差位置） |
| P2-3 | **互联网数据爬取** | 爬虫模块从公开谱子站点采集 GP 文件，自动分类后加入数据池 |
| P2-4 | **GTP v2.21 格式支持** | 485 个 .gtp 文件当前 PyGuitarPro 无法读取；研究二进制格式或用 Guitar Pro 软件批量转换为 GP5 |
| P2-5 | **CI 集成** | 将评估脚本接入 CI，每次 KB 变更自动跑评估，指标退化则阻止合并 |
| P2-6 | **多音轨支持** | 当前 Pipeline 是单 track 处理；扩展到多 track（lead + rhythm + bass）分别评估 |

---

## 5. 评估指标定义

### 5.1 核心指标

| 指标 | 定义 | 计算方式 | 目标 |
|------|------|----------|------|
| **String Match Rate** | 弦选择准确率：重建谱与 ground truth 在同一音符上选择了相同弦的比例 | `匹配弦数 / 对齐音符总数` | P0 baseline ≥ 60%；迭代后 ≥ 75% |
| **Fret Match Rate** | 品选择准确率：同一音符选择了相同品的比例 | `匹配品数 / 对齐音符总数` | P0 baseline ≥ 55%；迭代后 ≥ 70% |
| **Position Deviation** | 把位偏差：重建谱 hand_position 与 ground truth 的平均绝对偏差 | `mean(\|reconstructed_hp - gt_hp\|)` | P0 baseline ≤ 3.0 frets；迭代后 ≤ 2.0 |
| **Chord Shape Match** | 和弦指型匹配率：同一 onset 的和弦，所有音符的 (string, fret) 组合完全匹配的比例 | `完全匹配和弦数 / 和弦总数` | P0 baseline ≥ 40%；迭代后 ≥ 60% |
| **Overall Fingering Accuracy** | 综合指法准确率：(string, fret) 同时匹配的音符比例 | `(弦+品同时匹配) / 对齐音符总数` | P0 baseline ≥ 50%；迭代后 ≥ 65% |

### 5.2 辅助指标

| 指标 | 定义 | 用途 |
|------|------|------|
| **Pitch Accuracy** | 音高匹配率（应接近 100%，用于验证对齐正确性） | 对齐质量校验 |
| **Note Count Match** | 重建谱与 ground truth 的音符总数比率 | 检测 pipeline 是否丢音/多音 |
| **Measure Alignment Rate** | 小节对齐率 | 评估 quantize/measure_split 的准确性 |
| **Style Breakdown** | 按风格分组的指标明细 | 定位哪个风格最需要优化 |

### 5.3 评估流程

```
原始 GP 谱子 (ground truth)
        │
        ▼
   导出 MIDI  ←─ PyGuitarPro / Guitar Pro
        │
        ▼
   load_midi()  ←─ midi/parser.py
        │
        ▼
   classify_timeline() + PipelineContext
        │
        ▼
   RepairPipeline.execute()  ←─ engine/pipeline.py (7 stages)
        │
        ▼
   GuitarProjectIR (重建结果)
        │
        ▼
   ┌─────────────────┐
   │  音符对齐器       │  ← 按 measure + beat + pitch 对齐
   │  NoteAligner     │
   └────────┬────────┘
            │
     ┌──────┴──────┐
     ▼              ▼
  ground truth    reconstructed
  (string/fret)   (string/fret)
     │              │
     └──────┬──────┘
            ▼
   偏差计算引擎 (DeviationCalculator)
            │
            ▼
   EvaluationReport (JSON)
   {
     "file": "...",
     "style": "metal",
     "metrics": {
       "string_match_rate": 0.72,
       "fret_match_rate": 0.68,
       "position_deviation": 2.3,
       "chord_shape_match": 0.55,
       "overall_fingering_accuracy": 0.61
     },
     "per_note": [...],
     "per_measure": [...]
   }
```

---

## 6. 核心设计原则

### 原则 1: 脏 MIDI 是参考，不是真相

> **"你实际上是用正确的编曲方式和正确的分轨，正确的把位，正确的和弦，正确的articulation去贴近这个midi，让你创作出来的正确的东西无限贴近脏midi。"**

系统不是在"修复" MIDI 的错误，而是在用吉他演奏的领域知识重新编排。MIDI 提供的是音高和时序信息，系统用正确的吉他编曲知识去生成一个"演奏上正确"的谱子。评估闭环的核心就是验证这个"正确的编排"是否真的接近专业吉他手的选择。

### 原则 2: 知识必须可溯源

当前 KB2 的 5 个风格 priors 全部是 `source_type: "hand_authored"`。学习闭环产出的新 priors 必须标记为 `source_type: "empirical"`，并记录 `source_ids`（来源谱子文件列表）和 `evaluation.confidence`。每条知识都能追溯到它来自哪些专业谱子。

### 原则 3: 每次变更必须可验证

KB 的任何调整（权重修改、新增条目）都必须通过评估闭环验证。禁止"盲调"——不能在没有评估数据支撑的情况下修改 priors。A/B 对比（旧版 vs 新版）是知识更新的必要门禁。

### 原则 4: 评估对齐以音高为锚点

对齐策略：同一小节、同一拍位、相同音高的音符视为同一个音符的 ground truth 和重建结果。当出现一对多（ground truth 有 tie/split 导致重建侧音符数不同）时，取最近邻匹配并标记 `alignment_confidence`。

### 原则 5: 渐进式覆盖

2072 个谱子中，485 个 .gtp（v2.21）当前无法解析。P0 先覆盖 1587 个可解析文件（GP3/GP4/GP5），P2 再解决 .gtp 格式。不因部分数据不可用而阻塞闭环建立。

---

## 7. 待确认问题

| # | 问题 | 影响范围 | 建议 |
|---|------|----------|------|
| Q1 | **GP → MIDI 导出方式**：用 PyGuitarPro 代码导出，还是用 Guitar Pro 软件批量导出？PyGuitarPro 的 MIDI 导出能力是否完整保留音高和时序信息？ | P0-2 | 先验证 PyGuitarPro 的 MIDI 导出质量；若不理想，考虑用 Guitar Pro 软件脚本化批量导出 |
| Q2 | **风格标签来源**：2072 个谱子按目录分类（吉他练习/乐队/影视/木吉他/游戏动漫/电吉他/贝斯），但这些不是音乐风格（metal/rock/pop/funk）。如何将目录分类映射到 KB2 的 5 个 style？ | P1-1 | 建议建立映射表，或增加"unknown"风格作为兜底；也可考虑从谱子的 tempo/音域/技巧特征自动推断风格 |
| Q3 | **多 track 谱子处理**：很多专业谱子有多个 track（lead + rhythm + bass）。当前 `RepairPipeline` 是单 track 处理。评估时是否逐 track 独立跑？ | P0-3, P2-6 | P0 先只取每个谱子的第一个吉他 track 做 round-trip；P2 扩展多 track |
| Q4 | **弦编号约定一致性**：PyGuitarPro 的 string 编号与 FretPilot IR 的 string 编号（1=高音 E, 6=低音 E）是否一致？需验证，否则对比会全部错位。 | P0-4 | 写一个验证脚本，对几个已知谱子确认 string 编号映射 |
| Q5 | **和弦 onset 对齐容差**：当 ground truth 和重建谱的小节边界不完全对齐时（因 quantize 差异），beat 对齐的容差是多少？ | P0-4 | 建议容差 = 0.25 beat（16 分音符）；超出容差的音符标记为 `unmatched` |
| Q6 | **Priors 反推方法**：从统计数据到 priors 权重的映射关系如何确定？是简单线性回归、还是需要更复杂的优化（如 grid search 最小化评估误差）？ | P1-2 | P1 先用统计比例直接映射（如 `open_string_bias = 实际 open string 使用率 / 基准率`）；P2 考虑优化搜索 |
| Q7 | **评估基准的"正确性"**：专业谱子的指法是否一定是最优的？不同吉他手可能选择不同指法。如何处理"多个正确答案"的问题？ | 评估指标定义 | 建议引入"等价指法"概念：同音高同弦不同品但把位等价的情况视为匹配；P2 可引入演奏难度评分做加权 |
| Q8 | **.gtp v2.21 格式**：485 个文件占总量的 23%。是否值得投入精力逆向解析二进制格式？还是用 Guitar Pro 软件批量转 GP5 更经济？ | P2-4 | 建议后者——用 Guitar Pro 软件批量转换，不投入逆向工程 |

---

## 8. 技术架构概览

### 8.1 新增模块

```
backend/src/fretpilot/
├── elearning/                    ← 新增：学习闭环模块
│   ├── __init__.py
│   ├── gp_reader.py              ← P0-1: GP 谱子解析为 GroundTruthTab
│   ├── gp_to_midi.py             ← P0-2: GP → MIDI 导出
│   ├── note_aligner.py           ← P0-4: 音符对齐器
│   ├── deviation.py              ← P0-5: 偏差计算引擎
│   ├── evaluate.py               ← P0-6: 批量评估 CLI
│   ├── stats_extractor.py        ← P1-1: 指法规律统计器
│   ├── priors_deriver.py         ← P1-2: Priors 反推引擎
│   ├── kb_writer.py              ← P1-5: KB 写入器
│   └── models.py                 ← 数据模型：GroundTruthTab, EvaluationReport
├── knowledge/
│   ├── assets/                   ← 现有 KB JSON 文件
│   ├── versions/                 ← P1-3: 新增版本管理目录
│   └── ...
```

### 8.2 数据流

```
┌──────────────┐     ┌──────────┐     ┌───────────┐     ┌──────────────┐
│ 2072 GP 文件  │────▶│ GP Reader│────▶│ GP→MIDI   │────▶│ load_midi()  │
│ (GP3/4/5/GTP) │     │ (P0-1)   │     │ (P0-2)    │     │ (现有)       │
└──────────────┘     └────┬─────┘     └───────────┘     └──────┬───────┘
                          │                                      │
                   GroundTruthTab                         NormalizedTimeline
                          │                                      │
                          │                              ┌───────▼───────┐
                          │                              │ Pipeline      │
                          │                              │ (现有, P0-3)  │
                          │                              └───────┬───────┘
                          │                                      │
                          │                              GuitarProjectIR
                          │                                      │
                   ┌──────▼──────────────────────────────────────▼──────┐
                   │              NoteAligner (P0-4)                     │
                   │  按 measure + beat + pitch 对齐 ground truth 与 IR   │
                   └──────────────────────┬──────────────────────────────┘
                                          │
                   ┌──────────────────────▼──────────────────────────────┐
                   │           DeviationCalculator (P0-5)                │
                   │  计算 string/fret/position/chord 偏差               │
                   └──────────────────────┬──────────────────────────────┘
                                          │
                                 EvaluationReport (JSON)
                                          │
                          ┌───────────────┴───────────────┐
                          │                               │
                   ┌──────▼──────┐               ┌────────▼────────┐
                   │ StatsExtract │               │ 可视化报告 (P2) │
                   │ (P1-1)       │               │                 │
                   └──────┬───────┘               └─────────────────┘
                          │
                   ┌──────▼──────┐
                   │ PriorsDeriv │
                   │ (P1-2)      │
                   └──────┬──────┘
                          │
                   ┌──────▼──────┐
                   │ KB Writer   │
                   │ (P1-5)      │
                   └──────┬──────┘
                          │
                   ┌──────▼──────┐
                   │ 更新后的     │
                   │ kb2_perf.json│
                   │ (empirical)  │
                   └─────────────┘
```

### 8.3 与现有架构的集成点

| 现有模块 | 集成方式 |
|----------|----------|
| `midi/parser.py` → `load_midi()` | 学习闭环直接调用，无需修改 |
| `engine/pipeline.py` → `RepairPipeline.execute()` | 学习闭环直接调用，传入 `PipelineContext` |
| `knowledge/registry.py` → `KnowledgeRegistry` | 支持加载指定版本目录；新增 `from_version_dir()` |
| `knowledge/models.py` → `KnowledgeEntry.provenance` | 新 priors 标记 `source_type="empirical"`，`source_ids` 记录来源谱子 |
| `knowledge/engine.py` → `get_fingering_priors()` | 无需修改；priors 来源变了但接口不变 |
| `guitar/fretboard.py` → `candidate_positions()` | 评估时用于验证 ground truth 的 (string, fret) 是否合法 |
| `exporters/gp5.py` → `GP5Exporter` | 重建结果可导出 GP5 供人工检查 |

---

## 9. 里程碑

| 里程碑 | 内容 | 交付物 |
|--------|------|--------|
| **M1: Baseline 评估** | P0-1 ~ P0-6 全部完成 | 对 1587 个可解析谱子的 baseline 评估报告 JSON |
| **M2: 知识提取** | P1-1 ~ P1-2 完成 | 各风格的指法规律统计报告 + 反推的 empirical priors |
| **M3: KB 更新闭环** | P1-3 ~ P1-5 完成 | KB 版本管理 + A/B 评估对比 + 自动写入；验证至少 1 个风格准确率有提升 |
| **M4: 可视化与扩充** | P2-1 ~ P2-6 选择性完成 | Web 报告面板 + 失败案例钻取 + 数据扩充管道 |

---

## 附录 A: 参考数据概况

| 格式 | 数量 | PyGuitarPro 支持 | P0 覆盖 |
|------|------|-------------------|---------|
| .gp5 | 860 | ✅ | ✅ |
| .gp4 | 298 | ✅ | ✅ |
| .gp3 | 429 | ✅ | ✅ |
| .gtp (v2.21) | 485 | ❌ | ❌ (P2-4) |
| **合计** | **2072** | **1587 可解析** | **1587** |

目录分类：【吉他练习系列】【国内外乐队】【影视插曲】【木吉他】【游戏动漫曲谱】【电吉他】【贝斯】

## 附录 B: 现有 KB2 Priors 结构

当前 `kb2_performance.json` 包含 5 个风格，全部 `source_type: "hand_authored"`：

```json
{
  "knowledge_id": "kb2-metal-performance",
  "payload": {
    "shape_reuse": 1.5,
    "hand_position_stability": 1.4,
    "palm_mute": 1.6,
    "staccato": 1.35,
    "downpicking_bias": 1.35,
    "note_overlap": 0.7,
    "timing_looseness": 0.65,
    "open_string_bias": 0.6
  },
  "provenance": {
    "source_type": "hand_authored"    // ← 学习闭环后改为 "empirical"
  }
}
```

学习闭环后，这些 priors 的 `provenance.source_type` 应从 `hand_authored` 升级为 `empirical`，并填充 `source_ids`（来源谱子文件 ID 列表）和 `evaluation`（置信度 + 测试过的谱子 ID）。
