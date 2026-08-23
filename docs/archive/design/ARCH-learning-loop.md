# FretPilot 知识系统学习闭环 — 系统设计文档

> **架构师**: 高见远（Gao）
> **日期**: 2026-08-18
> **项目**: FretPilot v2 — elearning 模块
> **上游 PRD**: `docs/PRD-learning-loop.md`
> **技术验证结论**: 已由主理人完成（PyGuitarPro gp.parse() 可用、弦编号一致、mido 可用、GP tuning 可读取）

---

## 目录

1. [实现方案与框架选型](#1-实现方案与框架选型)
2. [文件列表及相对路径](#2-文件列表及相对路径)
3. [数据结构与接口（类图）](#3-数据结构与接口类图)
4. [程序调用流程（时序图）](#4-程序调用流程时序图)
5. [任务列表](#5-任务列表)
6. [依赖包列表](#6-依赖包列表)
7. [共享知识（跨文件约定）](#7-共享知识跨文件约定)
8. [待明确事项](#8-待明确事项)

---

## 1. 实现方案与框架选型

### 1.1 整体架构概述

学习闭环（`elearning/`）作为**外部评估器**独立于现有 pipeline 代码存在。它通过调用现有 pipeline API（`create_pipeline()` → `PipelineContext` → `execute()` → `GuitarProjectIR`）完成重建，不修改 pipeline 本身。核心数据流：

```
GP 谱子 → GPReader → GroundTruthTab（ground truth）
                    ↓
              GPMidiConverter → MIDI 文件 → load_midi() → NormalizedTimeline
                                                              ↓
                                                    PipelineRunner.run()
                                                              ↓
                                                    GuitarProjectIR（重建结果）
                                                              ↓
GroundTruthTab ──→ NoteAligner.align(gt, ir) ←── GuitarProjectIR
                        ↓
                 AlignedNotePair[]
                        ↓
                 DeviationCalculator → EvaluationReport
                        ↓
                 (P1) StatsExtractor → StyleStats → PriorsDeriver → DerivedPriors
                        ↓
                 (P1) KBWriter → 新版本 kb2_performance.json (empirical)
```

### 1.2 核心技术挑战与解决方案

#### 挑战 1: GP → MIDI 转换（P0-2）

**问题**: PyGuitarPro 不能导出 MIDI，需要自建转换器。

**方案**: 用 `mido` 库（已是项目依赖）构建 MIDI 文件。转换器遍历 GP Song 的 measure → beat → note 层级，将每个非 tie 音符转为 `note_on`/`note_off` 事件对。

**关键技术点**:
- **Ticks per beat**: MIDI 文件使用 `ticks_per_beat=960`，与 PyGuitarPro 的 `gp.Duration.quarterTime` 一致，确保 tick 位置一一对应。
- **Tempo**: 从 `song.tempo` 读取 BPM，用 `mido.bpm2tempo()` 转换为 microseconds per beat，写入 meta track 的 `set_tempo` 事件。
- **Time signature**: 从第一个 measure 的 `timeSignature` 读取 numerator/denominator。
- **Tie notes**: `note.type == guitarpro.NoteType.tie` 的音符不重复发 `note_on`（延续前一个音符的发声），只在前一个音符的 `note_off` 位置结束。
- **多 track 处理**: 取音符数最多的吉他 track（或第一个 track），单 track 导出。
- **Delta time 转换**: GP 的 beat.start 是绝对 tick 位置，需转为 mido 要求的 delta time（相邻事件间的差值）。

```python
# 转换核心逻辑伪代码
events = []  # (abs_tick, is_on, pitch, velocity)
for measure in track.measures:
    for beat in measure.beats:
        for note in beat.notes:
            if note.type == NoteType.tie:
                continue  # tie 音符不重复触发
            pitch = note.realValue  # MIDI pitch
            on_tick = beat.start
            off_tick = beat.start + beat.duration.time
            events.append((on_tick, True, pitch, velocity))
            events.append((off_tick, False, pitch, 0))
events.sort(key=lambda e: (e[0], 0 if e[1] else 1))  # note_off 优先于同 tick 的 note_on
# 转为 delta time 写入 mido MidiTrack
```

#### 挑战 2: 对齐策略（P0-4）

**问题**: ground truth（GP 谱子）和重建结果（IR）的音符数量可能不完全一致（tie/split/quantize 差异），需要建立可靠的对应关系。

**方案**: 以 `(measure_number, pitch, beat_in_measure)` 为三级锚点进行对齐，beat 容差 0.25 beat（16 分音符）。

**对齐算法**:
1. 将 ground truth 和 IR 音符分别按 `(measure_number, pitch)` 分组。
2. 对每个 `(measure_number, pitch)` 组，在 ground truth 侧和 IR 侧之间做最近邻匹配。
3. beat 差距 ≤ 0.25 beat 的视为匹配成功，`alignment_confidence = 1.0 - (beat_diff / 0.25)`。
4. 超出容差的音符标记为 `unmatched`，不参与偏差计算但计入 `note_count_match` 指标。
5. 一对多时取最近邻（贪心），未被匹配的多余音符标记 `unmatched`。

```python
# 对齐核心逻辑
BEAT_TOLERANCE = 0.25

def align_measure(gt_notes, ir_notes):
    """在单个 measure + pitch 组内做最近邻匹配。"""
    pairs = []
    used_ir = set()
    for gt in gt_notes:
        best_ir = None
        best_diff = float('inf')
        for i, ir in enumerate(ir_notes):
            if i in used_ir:
                continue
            diff = abs(gt.beat_in_measure - ir.beat_in_measure)
            if diff < best_diff:
                best_diff = diff
                best_ir = i
        if best_ir is not None and best_diff <= BEAT_TOLERANCE:
            used_ir.add(best_ir)
            pairs.append(AlignedNotePair(gt, ir_notes[best_ir], 1.0 - best_diff / BEAT_TOLERANCE))
    return pairs, len(ir_notes) - len(used_ir)  # 返回未匹配数
```

#### 挑战 3: 偏差计算（P0-5）

**方案**: 对每个对齐音符对比较 `string`/`fret`/`hand_position`，计算 5 项核心指标 + 4 项辅助指标。

**hand_position 推算（ground truth 侧）**:
GP 谱子不直接存储 hand_position，需从 fret 推算。采用与 `FingeringStage` 相同的约定以确保比较公平：
- fretted 音符：`hand_position = max(1, fret)`（简化模型，与 pipeline 一致）
- open string 音符：`hand_position = 前一个 fretted 音符的 hand_position`（延续）

**指标计算**:

| 指标 | 计算方式 |
|------|----------|
| String Match Rate | `sum(gt.string == ir.string) / len(aligned_pairs)` |
| Fret Match Rate | `sum(gt.fret == ir.fret) / len(aligned_pairs)` |
| Position Deviation | `mean(abs(gt.hand_position - ir.hand_position))` |
| Chord Shape Match | 同一 onset 的所有音符 (string, fret) 组合完全匹配的 chord 数 / chord 总数 |
| Overall Fingering Accuracy | `sum(gt.string == ir.string and gt.fret == ir.fret) / len(aligned_pairs)` |
| Pitch Accuracy | `sum(gt.pitch == ir.pitch) / len(aligned_pairs)`（验证对齐质量，应≈100%） |
| Note Count Match | `len(ir_notes) / len(gt_notes)`（检测丢音/多音） |
| Measure Alignment Rate | `matched_measures / total_measures` |

#### 挑战 4: 知识提取与 Priors 反推（P1-1, P1-2）

**方案**: 从 ground truth 谱子集合中统计指法规律，按风格分组，反推 KB2 priors 权重。

**统计项 → Priors 映射**:

| 统计项 | 计算 | 映射到 Priors |
|--------|------|---------------|
| open string 使用率 | `fret==0 的音符比例` | `open_string_bias = empirical_rate / baseline_rate` |
| 把位分布 | `hand_position 的直方图` | `hand_position_stability = 1 / (1 + position_change_rate)` |
| 弦选择分布 | 各弦使用频率的熵 | `string_skip_penalty = 1 + avg_string_distance * weight` |
| 和弦指型频率 | 同 onset 的 (string, fret) 组合出现次数 | `shape_reuse = top_k_shape_frequency / total_chords` |
| 音符重叠率 | 相邻音符 duration 重叠比例 | `note_overlap = mean(overlap_ratio)` |
| staccato 比例 | duration < 0.25 beat 的比例 | `staccato = empirical_staccato_rate / baseline_rate` |

**反推方法（P1 先用简单统计映射）**:
- `baseline_rate` = 当前 hand_authored priors 对应的隐含比率（通过逆向推算或设为 0.5）
- `open_string_bias = clamp(empirical_rate / 0.15, 0.3, 2.0)`（以 15% 作为中性基准）
- 最终 priors 值 clamp 到合理范围 [0.3, 2.0]，避免极端值

**provenance 标记**: 所有反推出的 priors 标记 `source_type = "empirical"`，`source_ids` 记录来源谱子文件路径列表，`evaluation.confidence` 基于样本量计算。

#### 挑战 5: KB 版本管理（P1-3）

**方案**: 在 `knowledge/` 下新增 `versions/` 目录，每次 KB 更新生成新 snapshot。

```
knowledge/
├── assets/           ← 当前活跃版本（pipeline 默认加载）
│   └── kb2_performance.json
├── versions/         ← 历史版本快照
│   ├── 2026.08.3/    ← 原始 hand_authored 版本
│   │   └── kb2_performance.json
│   └── 2026.08.4/    ← 第一次 empirical 更新
│       └── kb2_performance.json
└── version_manifest.json  ← 版本元数据（时间、来源、指标变化）
```

`KnowledgeRegistry` 新增 `from_version_dir(version_dir)` 类方法，支持加载指定版本目录的 KB assets。A/B 评估时分别加载两个版本跑全量评估。

### 1.3 框架与库选型

| 库 | 用途 | 理由 |
|----|------|------|
| `PyGuitarPro` (guitarpro) | GP3/GP4/GP5 文件解析 | 已是项目依赖，主理人已验证 `gp.parse()` 可用 |
| `mido` | MIDI 文件写入 | 已是项目依赖，项目 `midi/parser.py` 已用它读 MIDI |
| `click` (可选) | CLI 参数解析 | 比 argparse 更友好；也可用 stdlib argparse 避免新增依赖 |
| `rich` (可选) | 控制台表格输出 | 批量评估摘要美化；可降级为纯文本 |

**决策**: CLI 使用 stdlib `argparse`（零新增依赖），控制台输出用纯文本表格。如后续需要更丰富的 CLI 体验，再引入 `click` + `rich`。

### 1.4 架构模式

- **外部评估器模式**: `elearning/` 不修改 pipeline，通过调用 `create_pipeline()` + `PipelineContext` + `execute()` 作为黑盒使用 pipeline。
- **管道-过滤器模式**: `GPReader → GPMidiConverter → load_midi → PipelineRunner → NoteAligner → DeviationCalculator`，每个环节输入上一步输出。
- **数据驱动模式**: 所有 priors 来源于 JSON 资产，`elearning/` 只产生新 JSON，不硬编码任何权重。
- **版本快照模式**: KB 变更通过写入新版本目录实现，不覆盖旧版本，支持回滚。

---

## 2. 文件列表及相对路径

所有路径相对于 `backend/src/fretpilot/`，测试相对于 `backend/tests/`。

### 2.1 新建文件

| # | 文件路径 | 职责 | 对应需求 |
|---|----------|------|----------|
| 1 | `elearning/__init__.py` | 模块初始化，导出公共 API | — |
| 2 | `elearning/models.py` | 核心数据模型：GroundTruthNote, GroundTruthTab, AlignedNotePair, EvaluationMetrics, EvaluationReport, StyleStats, DerivedPriors | P0 全局 |
| 3 | `elearning/style_mapper.py` | 目录分类 → KB2 风格映射 | Q2 |
| 4 | `elearning/gp_reader.py` | PyGuitarPro 解析 → GroundTruthTab | P0-1 |
| 5 | `elearning/gp_to_midi.py` | GP Song → MIDI 文件（mido） | P0-2 |
| 6 | `elearning/pipeline_runner.py` | 封装 pipeline 调用：MIDI → detect → cleanup → context → execute → IR | P0-3 |
| 7 | `elearning/note_aligner.py` | measure+beat+pitch 三级对齐 | P0-4 |
| 8 | `elearning/deviation.py` | 偏差计算引擎，产出 EvaluationReport | P0-5 |
| 9 | `elearning/evaluate.py` | 批量评估编排 + CLI 入口 | P0-6 |
| 10 | `elearning/__main__.py` | `python -m fretpilot.elearning` CLI 入口 | P0-6 |
| 11 | `elearning/stats_extractor.py` | 从 ground truth 统计指法规律 | P1-1 |
| 12 | `elearning/priors_deriver.py` | 从统计反推 KB2 priors | P1-2 |
| 13 | `elearning/kb_writer.py` | KB 写入 + 版本管理 + A/B 对比 | P1-3, P1-4, P1-5 |
| 14 | `tests/elearning/__init__.py` | 测试包初始化 | — |
| 15 | `tests/elearning/test_gp_reader.py` | GP 解析测试 | — |
| 16 | `tests/elearning/test_gp_to_midi.py` | MIDI 导出测试 | — |
| 17 | `tests/elearning/test_note_aligner.py` | 对齐器测试 | — |
| 18 | `tests/elearning/test_deviation.py` | 偏差计算测试 | — |
| 19 | `tests/elearning/test_evaluate.py` | 端到端评估测试 | — |
| 20 | `tests/elearning/test_stats_extractor.py` | 统计提取测试 | — |
| 21 | `tests/elearning/test_priors_deriver.py` | Priors 反推测试 | — |
| 22 | `tests/elearning/test_kb_writer.py` | KB 写入 + 版本管理测试 | — |

### 2.2 修改文件

| # | 文件路径 | 修改内容 | 对应需求 |
|---|----------|----------|----------|
| 1 | `knowledge/registry.py` | 新增 `from_version_dir(version_dir)` 类方法，支持加载指定版本目录 | P1-3 |
| 2 | `knowledge/models.py` | 新增 `KnowledgeEntry.to_dict()` 方法（KB 写入需要序列化回 JSON） | P1-5 |

### 2.3 新增资产目录

| # | 路径 | 说明 |
|---|------|------|
| 1 | `knowledge/versions/` | KB 版本快照目录 |
| 2 | `knowledge/version_manifest.json` | 版本元数据索引 |

---

## 3. 数据结构与接口（类图）

> 完整 Mermaid 类图见 `docs/learning-loop-class-diagram.mermaid`

### 3.1 核心数据模型

#### GroundTruthNote — ground truth 单个音符

```python
@dataclass(slots=True)
class GroundTruthNote:
    """GP 谱子中的单个音符（ground truth）。"""
    measure_number: int        # 小节号（从 1 开始）
    beat_in_measure: float     # 小节内拍位（beats，0.0 = 小节起点）
    pitch: int                 # MIDI pitch（来自 note.realValue）
    string: int                # 弦号（1=高音E, 6=低音E）
    fret: int                  # 品号（0 = 空弦）
    hand_position: int         # 推算的把位（max(1, fret) for fretted；延续 for open）
    duration_beats: float      # 持续拍数（beat.duration.time / 960）
    is_tie: bool               # 是否为 tie 音符
    velocity: int              # 力度（默认 80）
```

#### GroundTruthTab — 整个 GP 谱子的 ground truth

```python
@dataclass(slots=True)
class GroundTruthTab:
    """一个 GP 谱子解析后的完整 ground truth。"""
    file_path: str             # 原始 GP 文件路径
    title: str                 # 曲名
    style_label: str           # 风格标签（由 style_mapper 推断）
    tempo_bpm: float           # BPM
    time_signature: tuple[int, int]  # (numerator, denominator)
    tuning_pitches: list[int]  # 空弦音高列表（低→高，来自 track.strings）
    notes: list[GroundTruthNote]  # 所有非 tie 音符
    track_name: str            # 使用的 track 名称

    @property
    def note_count(self) -> int:
        return len(self.notes)

    @property
    def measure_count(self) -> int:
        return max((n.measure_number for n in self.notes), default=0)
```

#### AlignedNotePair — 对齐后的音符对

```python
@dataclass(slots=True)
class AlignedNotePair:
    """ground truth 音符与重建 IR 音符的对齐对。"""
    gt_note: GroundTruthNote
    ir_note: GuitarNoteEvent     # 来自 ir/models.py
    alignment_confidence: float  # 0.0-1.0，由 beat 差距计算
    beat_delta: float            # beat 差距绝对值（用于诊断）
```

#### EvaluationMetrics — 评估指标集

```python
@dataclass(slots=True)
class EvaluationMetrics:
    """单个文件或聚合的评估指标。"""
    # 核心指标
    string_match_rate: float          # 弦选择准确率
    fret_match_rate: float            # 品选择准确率
    position_deviation: float         # 把位平均绝对偏差
    chord_shape_match: float          # 和弦指型匹配率
    overall_fingering_accuracy: float # 综合指法准确率
    # 辅助指标
    pitch_accuracy: float             # 音高匹配率（验证对齐质量）
    note_count_match: float           # 音符总数比率
    measure_alignment_rate: float     # 小节对齐率
    # 统计基础
    total_aligned: int                # 对齐音符对总数
    total_gt_notes: int               # ground truth 音符总数
    total_ir_notes: int               # 重建 IR 音符总数
    total_unmatched: int              # 未匹配音符数
```

#### EvaluationReport — 单文件评估报告

```python
@dataclass(slots=True)
class EvaluationReport:
    """单个谱子的完整评估报告。"""
    file_path: str
    style_label: str
    metrics: EvaluationMetrics
    per_note: list[dict]       # 逐音符偏差明细
    per_measure: list[dict]    # 逐小节汇总
    warnings: list[str]        # 解析/对齐过程中的警告
    timestamp: str             # ISO 8601

    def to_dict(self) -> dict[str, Any]:
        """序列化为 JSON 兼容 dict。"""

    @classmethod
    def from_dict(cls, data: dict) -> "EvaluationReport":
        """从 dict 反序列化。"""
```

#### BatchEvaluationResult — 批量评估聚合结果

```python
@dataclass(slots=True)
class BatchEvaluationResult:
    """批量评估的聚合结果。"""
    total_files: int
    successful: int
    failed: int
    skipped: int  # .gtp v2.21 等不可解析文件
    overall_metrics: EvaluationMetrics  # 全量聚合
    per_style: dict[str, EvaluationMetrics]  # 按风格分组
    per_file: list[EvaluationReport]  # 逐文件报告
    worst_files: list[EvaluationReport]  # 准确率最低的 N 个文件
    timestamp: str
    kb_snapshot_version: str  # 使用的 KB 版本
```

#### StyleStats — 风格统计

```python
@dataclass(slots=True)
class StyleStats:
    """按风格分组的指法规律统计。"""
    style_label: str
    sample_count: int               # 来源谱子数
    total_notes: int                # 总音符数
    open_string_rate: float         # 空弦使用率
    hand_position_distribution: dict[int, float]  # {position: frequency}
    string_distribution: dict[int, float]          # {string_number: frequency}
    avg_string_skip: float          # 相邻音符平均弦距
    chord_shape_top_k: dict[str, int]  # top-K 和弦指型: "s1f0,s2f2,s3f2" → count
    note_overlap_rate: float        # 音符重叠率
    staccato_rate: float            # staccato 比例
    fret_distribution: dict[int, float]  # {fret: frequency}
```

#### DerivedPriors — 反推出的 priors

```python
@dataclass(slots=True)
class DerivedPriors:
    """从统计数据反推出的 KB2 priors。"""
    style_label: str
    knowledge_id: str               # 如 "kb2-metal-performance"
    payload: dict[str, float]       # priors dict（如 {"open_string_bias": 0.8, ...}）
    source_ids: list[str]           # 来源谱子文件路径列表
    confidence: float               # 基于样本量的置信度
    derivation_method: str          # "statistical_mapping"
    stats_snapshot: dict[str, Any]  # 统计快照（可追溯）
```

### 3.2 核心服务类

#### GPReader

```python
class GPReader:
    """P0-1: 用 PyGuitarPro 读取 GP3/GP4/GP5 文件，提取 ground truth。"""

    QUARTER_TICKS = 960  # gp.Duration.quarterTime

    def parse(self, path: str | Path, style_label: str = "unknown") -> GroundTruthTab:
        """解析 GP 文件为 GroundTruthTab。"""
        # 1. gp.parse(path) → Song
        # 2. 选第一个有音符的 track（或音符最多的 track）
        # 3. 提取 tuning from track.strings
        # 4. 遍历 measure → beat → note，构建 GroundTruthNote 列表
        # 5. 跳过 tie 音符（type == NoteType.tie）
        # 6. 推算 hand_position
        # 7. 组装 GroundTruthTab

    def _select_guitar_track(self, song) -> Track:
        """选择主吉他 track（音符最多的 track）。"""

    def _extract_tuning(self, track) -> list[int]:
        """从 track.strings 提取空弦音高（低→高排列）。"""

    def _compute_hand_position(self, notes: list[GroundTruthNote]) -> None:
        """按 pipeline 相同约定推算 hand_position（原地修改）。"""

    def _ticks_to_beats(self, ticks: int) -> float:
        """ticks → beats: ticks / 960。"""
```

#### GPMidiConverter

```python
class GPMidiConverter:
    """P0-2: 将 GP Song 转为 MIDI 文件（用 mido 写入）。"""

    TPB = 960  # ticks per beat，与 GP quarterTime 一致

    def convert(self, tab: GroundTruthTab, output_path: str | Path) -> Path:
        """将 GroundTruthTab 转为 MIDI 文件并保存。"""
        # 1. 创建 mido.MidiFile(ticks_per_beat=960, type=1)
        # 2. meta track: set_tempo + time_signature
        # 3. music track: program_change + note_on/note_off 事件
        # 4. 跳过 tie 音符
        # 5. 排序事件，转 delta time，写入 track
        # 6. midi.save(output_path)

    def _build_events(self, tab: GroundTruthTab) -> list[tuple[int, bool, int, int]]:
        """构建 (abs_tick, is_note_on, pitch, velocity) 事件列表。"""

    def _events_to_track(self, events, program: int = 30) -> mido.MidiTrack:
        """将绝对 tick 事件列表转为 mido MidiTrack（delta time）。"""
```

#### PipelineRunner

```python
class PipelineRunner:
    """P0-3: 封装 pipeline 调用，MIDI → IR。"""

    def __init__(self, knowledge_dir: str | None = None) -> None:
        """可选指定 KB 版本目录（用于 A/B 评估）。"""

    def run(
        self,
        midi_path: str | Path,
        style_label: str = "unknown",
        tuning_pitches: list[int] | None = None,
        midi_fidelity: float = 0.5,
    ) -> GuitarProjectIR:
        """执行完整 pipeline 重建流程。"""
        # 1. load_midi(midi_path) → NormalizedTimeline
        # 2. classify_timeline(timeline) → 找到吉他 track
        # 3. 构建 cleaned track（简化：直接取 primary guitar track）
        # 4. 解析 tuning（从 GP 传入或 auto_detect）
        # 5. create_pipeline() + PipelineContext(...)
        # 6. pipeline.execute(ctx) → GuitarProjectIR

    def _resolve_tuning(
        self, tuning_pitches: list[int] | None, timeline: NormalizedTimeline
    ) -> GuitarTuning | None:
        """从 GP tuning pitches 构建 GuitarTuning，或 auto_detect。"""
```

#### NoteAligner

```python
class NoteAligner:
    """P0-4: 按 measure + beat + pitch 对齐 ground truth 与重建 IR。"""

    BEAT_TOLERANCE = 0.25  # beat 容差

    def align(
        self, gt_tab: GroundTruthTab, ir: GuitarProjectIR
    ) -> list[AlignedNotePair]:
        """对齐 ground truth 音符与 IR 音符。"""
        # 1. 从 IR 提取所有 GuitarNoteEvent（flatten measures → events）
        # 2. 按 (measure_number, pitch) 分组两侧音符
        # 3. 每组内做贪心最近邻匹配
        # 4. 返回 AlignedNotePair 列表

    def _extract_ir_notes(self, ir: GuitarProjectIR) -> list[GuitarNoteEvent]:
        """从 IR 的所有 track/measure 中展平所有音符事件。"""

    def _align_group(
        self, gt_notes: list[GroundTruthNote], ir_notes: list[GuitarNoteEvent]
    ) -> list[AlignedNotePair]:
        """在单个 (measure, pitch) 组内做最近邻匹配。"""
```

#### DeviationCalculator

```python
class DeviationCalculator:
    """P0-5: 对对齐音符对计算偏差指标。"""

    def calculate(
        self,
        pairs: list[AlignedNotePair],
        gt_tab: GroundTruthTab,
        ir: GuitarProjectIR,
    ) -> EvaluationReport:
        """计算完整评估报告。"""
        # 1. 逐对比较 string/fret/hand_position
        # 2. 按 onset 分组计算 chord shape match
        # 3. 聚合为 EvaluationMetrics
        # 4. 构建 per_note 和 per_measure 明细
        # 5. 组装 EvaluationReport

    def _compute_metrics(
        self, pairs: list[AlignedNotePair], gt_count: int, ir_count: int
    ) -> EvaluationMetrics:
        """计算核心 + 辅助指标。"""

    def _compute_chord_match(self, pairs: list[AlignedNotePair]) -> float:
        """按 onset 分组，计算和弦指型完全匹配率。"""
```

#### BatchEvaluator

```python
class BatchEvaluator:
    """P0-6: 批量评估编排器。"""

    def __init__(self, knowledge_dir: str | None = None) -> None:
        self._reader = GPReader()
        self._converter = GPMidiConverter()
        self._runner = PipelineRunner(knowledge_dir)
        self._aligner = NoteAligner()
        self._calculator = DeviationCalculator()

    def evaluate_file(self, gp_path: str | Path) -> EvaluationReport:
        """评估单个 GP 文件（完整 round-trip）。"""

    def evaluate_dir(
        self,
        input_dir: str | Path,
        output_path: str | Path | None = None,
        max_files: int | None = None,
    ) -> BatchEvaluationResult:
        """批量评估目录下所有 GP 文件。"""
        # 1. 扫描 .gp3/.gp4/.gp5 文件（跳过 .gtp）
        # 2. 逐文件 evaluate_file
        # 3. 聚合为 BatchEvaluationResult
        # 4. 可选写入 JSON 报告

    def _aggregate_metrics(
        self, reports: list[EvaluationReport]
    ) -> tuple[EvaluationMetrics, dict[str, EvaluationMetrics]]:
        """聚合全量 + 按风格指标。"""
```

#### StatsExtractor

```python
class StatsExtractor:
    """P1-1: 从 ground truth 谱子集合统计指法规律。"""

    def extract(
        self, tabs: list[GroundTruthTab]
    ) -> dict[str, StyleStats]:
        """按风格分组统计，返回 {style_label: StyleStats}。"""

    def _compute_open_string_rate(self, notes: list[GroundTruthNote]) -> float:
        """空弦使用率。"""

    def _compute_hand_position_dist(self, notes: list[GroundTruthNote]) -> dict[int, float]:
        """把位分布直方图。"""

    def _compute_string_distribution(self, notes: list[GroundTruthNote]) -> dict[int, float]:
        """弦选择分布。"""

    def _compute_chord_shapes(
        self, notes: list[GroundTruthNote], top_k: int = 20
    ) -> dict[str, int]:
        """和弦指型频率 top-K。"""

    def _compute_avg_string_skip(self, notes: list[GroundTruthNote]) -> float:
        """相邻音符平均弦距。"""
```

#### PriorsDeriver

```python
class PriorsDeriver:
    """P1-2: 从统计数据反推 KB2 priors。"""

    # KB2 中 5 个风格的 knowledge_id 映射
    STYLE_TO_KB_ID = {
        "metal": "kb2-metal-performance",
        "rock": "kb2-rock-lead-performance",  # 默认用 lead
        "pop": "kb2-pop-performance",
        "funk": "kb2-funk-performance",
    }

    # Priors clamp 范围
    PRIOR_RANGE = (0.3, 2.0)

    def derive(
        self, style_stats: dict[str, StyleStats], source_ids_map: dict[str, list[str]]
    ) -> list[DerivedPriors]:
        """从风格统计反推 priors。"""

    def _derive_open_string_bias(self, stats: StyleStats) -> float:
        """open_string_bias = clamp(rate / 0.15, 0.3, 2.0)。"""

    def _derive_hand_position_stability(self, stats: StyleStats) -> float:
        """hand_position_stability = clamp(1 / (1 + change_rate), 0.3, 2.0)。"""

    def _derive_shape_reuse(self, stats: StyleStats) -> float:
        """shape_reuse = clamp(top_shape_freq / 0.1, 0.3, 2.0)。"""

    def _derive_note_overlap(self, stats: StyleStats) -> float:
        """note_overlap = clamp(empirical_rate, 0.3, 2.0)。"""

    def _compute_confidence(self, sample_count: int, total_notes: int) -> float:
        """基于样本量的置信度。"""
```

#### KBWriter

```python
class KBWriter:
    """P1-3, P1-5: 将 empirical priors 写回 KB，支持版本管理。"""

    def __init__(self, knowledge_root: str | Path) -> None:
        """指定 knowledge 根目录（含 assets/ 和 versions/）。"""

    def write(
        self,
        derived_priors: list[DerivedPriors],
        snapshot_version: str | None = None,
    ) -> str:
        """写入新版本 KB，返回 snapshot_version。"""
        # 1. 生成 snapshot_version（如未指定，用日期）
        # 2. 加载当前 kb2_performance.json
        # 3. 用 derived priors 替换对应 style 的 payload + provenance
        # 4. 写入 versions/<version>/kb2_performance.json
        # 5. 更新 version_manifest.json
        # 6. 可选：更新 assets/ 活跃版本

    def list_versions(self) -> list[dict[str, Any]]:
        """列出所有 KB 版本及其元数据。"""

    def load_version(self, version: str) -> KnowledgeRegistry:
        """加载指定版本的 KB。"""

    def rollback(self, target_version: str) -> None:
        """回滚到指定版本（将目标版本复制为活跃版本）。"""

    def diff_versions(
        self, version_a: str, version_b: str
    ) -> dict[str, Any]:
        """对比两个版本的 priors 差异。"""
```

#### ABComparator

```python
class ABComparator:
    """P1-4: A/B 评估对比器。"""

    def compare(
        self,
        input_dir: str | Path,
        version_a: str,
        version_b: str,
    ) -> dict[str, Any]:
        """用两个 KB 版本分别跑全量评估，对比指标变化。"""
        # 1. 用 version_a 跑 BatchEvaluator → result_a
        # 2. 用 version_b 跑 BatchEvaluator → result_b
        # 3. 逐风格对比指标 delta
        # 4. 标注提升/退化

    def _compute_delta(
        self, metrics_a: EvaluationMetrics, metrics_b: EvaluationMetrics
    ) -> dict[str, float]:
        """计算指标 delta（b - a）。"""
```

---

## 4. 程序调用流程（时序图）

> 完整 Mermaid 时序图见 `docs/learning-loop-sequence-diagram.mermaid`

### 4.1 P0 核心流程：单文件 Round-Trip 评估

```
User → CLI (evaluate.py)
  → BatchEvaluator.evaluate_file(gp_path)
    → GPReader.parse(gp_path) → GroundTruthTab
    → GPMidiConverter.convert(tab) → midi_path
    → PipelineRunner.run(midi_path, style, tuning) → GuitarProjectIR
      → load_midi(midi_path) → NormalizedTimeline
      → classify_timeline(timeline) → GuitarDetectionReport
      → create_pipeline(knowledge_dir) → RepairPipeline
      → PipelineContext(timeline, track, ...)
      → pipeline.execute(ctx) → GuitarProjectIR
    → NoteAligner.align(gt_tab, ir) → AlignedNotePair[]
    → DeviationCalculator.calculate(pairs, gt_tab, ir) → EvaluationReport
  → 输出 JSON
```

### 4.2 P0 批量评估流程

```
User → CLI --input-dir <dir> --output <report.json>
  → BatchEvaluator.evaluate_dir(input_dir)
    → 扫描 .gp3/.gp4/.gp5 文件（跳过 .gtp）
    → for each file:
        evaluate_file(file) → EvaluationReport
        （失败/跳过单独记录）
    → 聚合 → BatchEvaluationResult
      → overall_metrics
      → per_style metrics
      → worst_files
    → 写入 JSON 报告
    → 控制台打印摘要表格
```

### 4.3 P1 知识提取与 KB 更新流程

```
User → CLI --learn --input-dir <dir> --kb-root <knowledge_dir>
  → BatchEvaluator.evaluate_dir(input_dir) → BatchEvaluationResult
    （同时保留所有 GroundTruthTab）
  → StatsExtractor.extract(all_gt_tabs) → {style: StyleStats}
  → PriorsDeriver.derive(style_stats, source_ids) → [DerivedPriors]
  → KBWriter.write(derived_priors) → new_snapshot_version
  → ABComparator.compare(input_dir, old_version, new_version) → delta report
  → 输出：baseline metrics + empirical priors + A/B delta
```

---

## 5. 任务列表

### 5.1 所需包

```
- guitarpro>=0.9.0: GP3/GP4/GP5 文件解析（已是项目依赖）
- mido>=1.3.0: MIDI 文件写入（已是项目依赖）
```

**无新增第三方依赖。** 所有功能基于现有项目依赖实现。

### 5.2 任务分解

---

#### T01: 项目基础设施与数据模型

**Source Files**:
- `elearning/__init__.py` (新建)
- `elearning/models.py` (新建)
- `elearning/style_mapper.py` (新建)
- `tests/elearning/__init__.py` (新建)

**Dependencies**: 无

**Priority**: P0

**描述**: 搭建 `elearning/` 模块骨架，定义所有核心数据模型（`GroundTruthNote`, `GroundTruthTab`, `AlignedNotePair`, `EvaluationMetrics`, `EvaluationReport`, `BatchEvaluationResult`, `StyleStats`, `DerivedPriors`），实现目录分类→KB2 风格的映射工具。

**验收标准**:
- `from fretpilot.elearning.models import GroundTruthTab, EvaluationReport` 可正常导入
- `style_mapper.map_directory_to_style("电吉他")` 返回合理的 KB2 风格标签
- `EvaluationReport.to_dict()` / `from_dict()` 可正确序列化/反序列化
- 所有数据模型使用 `@dataclass(slots=True)` 与项目风格一致
- `tests/elearning/__init__.py` 存在，pytest 可发现测试包

---

#### T02: GP 读取与 MIDI 导出

**Source Files**:
- `elearning/gp_reader.py` (新建)
- `elearning/gp_to_midi.py` (新建)
- `tests/elearning/test_gp_reader.py` (新建)
- `tests/elearning/test_gp_to_midi.py` (新建)

**Dependencies**: T01

**Priority**: P0

**描述**: 实现 P0-1（GP 解析器）和 P0-2（GP→MIDI 转换器）。`GPReader` 用 `guitarpro.parse()` 读取 GP3/GP4/GP5 文件，提取每个音符的 string/fret/pitch/measure/beat 作为 ground truth。`GPMidiConverter` 用 `mido` 将 GP 谱子转为 MIDI 文件，正确处理 tempo、time signature、tie notes。

**关键技术点**:
- 弦编号 1=高音E, 6=低音E（与 FretPilot 一致，无需转换）
- tick→beat 转换：`ticks / 960`
- tie 音符跳过（不重复 note_on）
- tuning 从 `track.strings` 提取
- hand_position 推算与 pipeline 约定一致

**验收标准**:
- `GPReader.parse("test.gp5")` 返回 `GroundTruthTab`，notes 非空
- GroundTruthNote 的 string/fret/pitch 值正确（与 Guitar Pro 软件中一致）
- tie 音符被跳过（不在 notes 列表中）
- `GPMidiConverter.convert(tab, "output.mid")` 生成的 MIDI 可被 `load_midi()` 正常解析
- 导出的 MIDI 音符数 = ground truth 非 tie 音符数
- 测试覆盖：单音符、和弦、tie、多小节场景

---

#### T03: 对齐、偏差计算与评估闭环

**Source Files**:
- `elearning/pipeline_runner.py` (新建)
- `elearning/note_aligner.py` (新建)
- `elearning/deviation.py` (新建)
- `elearning/evaluate.py` (新建)
- `elearning/__main__.py` (新建)
- `tests/elearning/test_note_aligner.py` (新建)
- `tests/elearning/test_deviation.py` (新建)
- `tests/elearning/test_evaluate.py` (新建)

**Dependencies**: T01, T02

**Priority**: P0

**描述**: 实现 P0-3 到 P0-6 的完整评估闭环。`PipelineRunner` 封装现有 pipeline 调用（不修改 pipeline 本身）。`NoteAligner` 按 measure+beat+pitch 三级对齐，容差 0.25 beat。`DeviationCalculator` 计算 5 项核心指标 + 4 项辅助指标。`BatchEvaluator` + CLI 支持单文件和批量目录评估。

**关键技术点**:
- `PipelineRunner` 复用 `create_pipeline()` + `PipelineContext` + `execute()`，advisor=None（degraded mode，不调 LLM）
- tuning 从 GP 文件传入（确保 pipeline 用正确定弦）
- 对齐：先按 (measure, pitch) 分组，组内贪心最近邻匹配
- chord shape match：按 onset 分组，组内所有 (string, fret) 完全匹配才算
- CLI: `python -m fretpilot.elearning evaluate --input-dir <dir> --output <report.json>`

**验收标准**:
- `PipelineRunner.run(midi_path)` 返回 `GuitarProjectIR`，每个音符有 string/fret 赋值
- `NoteAligner.align(gt, ir)` 对齐率 ≥95%（在正常 GP 文件上）
- `DeviationCalculator.calculate()` 输出包含全部 5 项核心指标
- `python -m fretpilot.elearning evaluate --input-dir ./test_songs --output report.json` 正常运行
- 批量评估能正确跳过 .gtp 文件
- 报告 JSON 结构与 PRD 中定义的 EvaluationReport 格式一致
- 测试覆盖：完美对齐、一对多、未匹配、空小节场景

---

#### T04: 知识提取与 Priors 反推

**Source Files**:
- `elearning/stats_extractor.py` (新建)
- `elearning/priors_deriver.py` (新建)
- `tests/elearning/test_stats_extractor.py` (新建)
- `tests/elearning/test_priors_deriver.py` (新建)

**Dependencies**: T01, T02

**Priority**: P1

**描述**: 实现 P1-1（指法规律统计器）和 P1-2（Priors 反推引擎）。`StatsExtractor` 从 ground truth 谱子集合按风格分组统计：open string 使用率、把位分布、弦选择分布、和弦指型频率、string skip 模式、音符重叠率。`PriorsDeriver` 从统计数据反推 KB2 priors 权重，标记 `source_type="empirical"`。

**关键技术点**:
- 统计按 `style_label` 分组（来自 `style_mapper`）
- open_string_bias = clamp(empirical_rate / 0.15, 0.3, 2.0)
- hand_position_stability 从把位变化频率推导
- 所有 priors 值 clamp 到 [0.3, 2.0] 避免极端值
- DerivedPriors 包含 source_ids 和 confidence（基于样本量）

**验收标准**:
- `StatsExtractor.extract(tabs)` 返回按风格分组的 `StyleStats`
- open_string_rate 计算正确（fret==0 的比例）
- chord_shape_top_k 正确识别常见和弦指型
- `PriorsDeriver.derive(stats)` 输出 `DerivedPriors`，payload 包含合理的 priors 值
- 所有 priors 值在 [0.3, 2.0] 范围内
- provenance.source_type = "empirical"
- confidence 基于样本量合理计算
- 测试覆盖：单风格、多风格、空数据场景

---

#### T05: KB 版本管理与写入

**Source Files**:
- `elearning/kb_writer.py` (新建)
- `knowledge/registry.py` (修改：新增 `from_version_dir()`)
- `knowledge/models.py` (修改：新增 `KnowledgeEntry.to_dict()`)
- `tests/elearning/test_kb_writer.py` (新建)

**Dependencies**: T01, T04

**Priority**: P1

**描述**: 实现 P1-3（KB 快照版本管理）、P1-4（A/B 评估对比）、P1-5（KB 写入器）。`KBWriter` 将 empirical priors 写回 `kb2_performance.json`，生成新 snapshot_version，保留旧版本。支持回滚和版本间 diff。`ABComparator` 用两个 KB 版本分别跑评估，对比指标变化。修改 `KnowledgeRegistry` 新增 `from_version_dir()` 支持加载指定版本。

**关键技术点**:
- 版本目录结构：`knowledge/versions/<version>/kb2_performance.json`
- version_manifest.json 记录每个版本的元数据
- `from_version_dir()` 复用 `_build_snapshot_from_assets()` 逻辑
- `KnowledgeEntry.to_dict()` 是 `from_dict()` 的逆操作（序列化回 JSON）
- A/B 对比：同一批文件用两个 KB 版本各跑一遍 BatchEvaluator
- 写入时保留原 entries 中未被 empirical 覆盖的条目

**验收标准**:
- `KBWriter.write(derived_priors)` 生成新版本目录和 manifest 条目
- 写入的 JSON 通过 `KnowledgeRegistry.from_version_dir()` 可正常加载
- `KBWriter.list_versions()` 返回所有历史版本
- `KBWriter.rollback(version)` 可将活跃版本恢复到指定版本
- `KnowledgeRegistry.from_version_dir(path)` 能正确加载指定版本目录
- `KnowledgeEntry.to_dict()` 输出与原 JSON 格式一致
- A/B 对比输出 before/after 指标 delta 表
- 测试覆盖：写入、加载、回滚、diff 场景

---

### 5.3 任务依赖图

```mermaid
graph LR
    T01[T01: 基础设施与数据模型]
    T02[T02: GP读取与MIDI导出]
    T03[T03: 对齐·偏差·评估闭环]
    T04[T04: 知识提取与Priors反推]
    T05[T05: KB版本管理与写入]

    T01 --> T02
    T01 --> T03
    T02 --> T03
    T01 --> T04
    T02 --> T04
    T04 --> T05

    style T01 fill:#4CAF50,color:#fff
    style T02 fill:#2196F3,color:#fff
    style T03 fill:#FF9800,color:#fff
    style T04 fill:#9C27B0,color:#fff
    style T05 fill:#F44336,color:#fff
```

### 5.4 任务总览

| Task | 名称 | 优先级 | 依赖 | 文件数 |
|------|------|--------|------|--------|
| T01 | 项目基础设施与数据模型 | P0 | — | 4 |
| T02 | GP 读取与 MIDI 导出 | P0 | T01 | 4 |
| T03 | 对齐、偏差计算与评估闭环 | P0 | T01, T02 | 8 |
| T04 | 知识提取与 Priors 反推 | P1 | T01, T02 | 4 |
| T05 | KB 版本管理与写入 | P1 | T01, T04 | 4 |

---

## 6. 依赖包列表

### 6.1 新增依赖

**无新增第三方依赖。** 学习闭环模块完全基于现有项目依赖实现。

### 6.2 使用的现有依赖

| 包 | 版本要求 | 用途 |
|----|----------|------|
| `guitarpro` (PyGuitarPro) | `>=0.9.0` | GP3/GP4/GP5 文件解析（`gp.parse()`） |
| `mido` | `>=1.3.0` | MIDI 文件写入（`MidiFile`, `MidiTrack`, `Message`, `MetaMessage`） |
| `pydantic` | `>=2.6.0` | 数据模型验证（可选，dataclass 已够用） |

### 6.3 CLI 依赖

CLI 使用 Python 标准库 `argparse`，无需额外依赖。

---

## 7. 共享知识（跨文件约定）

### 7.1 弦编号约定

**所有模块统一使用 1=高音E, 6=低音E 的弦编号约定。**

- PyGuitarPro 的 `note.string` 与 FretPilot IR 的 `fingering.string` 编号一致
- **无需任何转换** — 这是主理人技术验证确认的结论
- `guitar/instrument.py` 中 `STANDARD_TUNING.open_strings` 也是此约定：`(1, 64)` = 高音E4
- `guitar/fretboard.py` 中 `candidate_positions()` 返回的 `FretPosition.string` 也是此约定

### 7.2 Tick → Beat 转换

```
beats = ticks / 960
```

- `gp.Duration.quarterTime` = 960 ticks per quarter note
- 假设 4/4 拍号下，quarter note = 1 beat
- 因此 `ticks / 960 = beats`
- 此约定适用于：
  - `GPReader`：`beat_in_measure = (beat.start - measure.start) / 960`
  - `GPMidiConverter`：MIDI ticks_per_beat = 960
  - `NoteAligner`：beat 容差 0.25 beat = 240 ticks

### 7.3 GP Tuning 读取与传递

```python
# GPReader 从 track.strings 提取 tuning
# track.strings 是 list[GuitarString]，每个有 .number 和 .value
# .value 是空弦 MIDI pitch
# 转为 list[int]（低→高排列）传入 GroundTruthTab.tuning_pitches

# PipelineRunner 用 tuning_pitches 构建 GuitarTuning
# 需要从 knowledge.tunings.GuitarTuning 格式转换：
#   string_pitches (低→高) ← tuning_pitches
# 然后传入 PipelineContext.tuning

# GPMidiConverter 不需要 tuning（pitch 直接来自 note.realValue）
```

### 7.4 对齐容差

```python
BEAT_TOLERANCE = 0.25  # beat，等于 16 分音符
```

- 超出容差的音符标记为 `unmatched`
- `alignment_confidence = 1.0 - (beat_diff / BEAT_TOLERANCE)`
- 容差选择理由：GP 谱子的 beat 位置是精确的，但 pipeline 的 quantize 阶段可能引入最多 1/16 音符的偏移

### 7.5 Hand Position 推算约定

ground truth 的 hand_position 按以下规则推算（与 `FingeringStage` 完全一致）：

```python
# fretted 音符 (fret > 0):
hand_position = max(1, fret)

# open string (fret == 0):
hand_position = prev_fretted_note.hand_position  # 延续前一个把位
# 如果没有前一个 fretted 音符: hand_position = 1
```

### 7.6 Tie Note 处理约定

- `GPReader`：跳过 `note.type == guitarpro.NoteType.tie` 的音符（不加入 notes 列表）
- `GPMidiConverter`：tie 音符不生成 `note_on` 事件（延续前一个音符的发声）
- `NoteAligner`：ground truth 侧和 IR 侧都不包含 tie 音符（pipeline 的 TieStage 已处理）

### 7.7 风格映射约定

目录分类 → KB2 风格的映射表（`style_mapper.py`）：

| 目录分类 | 映射风格 | 理由 |
|----------|----------|------|
| 电吉他 | rock | 电吉他以 rock 为主 |
| 国内外乐队 | rock | 乐队曲谱以 rock/metal 为主 |
| 木吉他 | pop | 木吉他以 pop/folk 为主 |
| 吉他练习系列 | unknown | 练习曲风格不定 |
| 影视插曲 | pop | 影视配乐以 pop 为主 |
| 游戏动漫曲谱 | unknown | 风格不定 |
| 贝斯 | unknown | KB2 无 bass 专用 priors |

> **注**: 此映射为 P0 初始版本，后续可通过谱子的 tempo/音域/技巧特征自动推断更精确的风格。`unknown` 风格在 pipeline 中使用默认 priors。

### 7.8 KB JSON 格式约定

`kb2_performance.json` 的结构（学习闭环写入时必须保持兼容）：

```json
{
  "snapshot_version": "2026.08.4",
  "schema_version": "1",
  "status": "approved",
  "entries": [
    {
      "knowledge_id": "kb2-metal-performance",
      "domain": "kb2_performance",
      "kind": "fingering_priors",
      "schema_version": "1",
      "knowledge_version": "2026.08.4",
      "status": "approved",
      "payload": {
        "open_string_bias": 0.8,
        "hand_position_stability": 1.2,
        ...
      },
      "scope": { "style": ["metal"] },
      "provenance": {
        "source_type": "empirical",
        "source_ids": ["song1.gp5", "song2.gp5", ...],
        "authored_by": "elearning/learning_loop",
        "notes": "Derived from N ground truth tabs"
      },
      "evaluation": {
        "status": "evaluated",
        "confidence": 0.82,
        "tested_against": ["song1.gp5", ...]
      }
    }
  ]
}
```

### 7.9 评估报告 JSON 格式约定

```json
{
  "file": "/path/to/song.gp5",
  "style": "rock",
  "timestamp": "2026-08-18T12:00:00Z",
  "metrics": {
    "string_match_rate": 0.72,
    "fret_match_rate": 0.68,
    "position_deviation": 2.3,
    "chord_shape_match": 0.55,
    "overall_fingering_accuracy": 0.61,
    "pitch_accuracy": 1.0,
    "note_count_match": 0.98,
    "measure_alignment_rate": 0.96,
    "total_aligned": 234,
    "total_gt_notes": 240,
    "total_ir_notes": 238,
    "total_unmatched": 6
  },
  "per_note": [
    {
      "measure": 1,
      "beat": 0.0,
      "pitch": 64,
      "gt_string": 1,
      "gt_fret": 0,
      "ir_string": 1,
      "ir_fret": 0,
      "string_match": true,
      "fret_match": true,
      "alignment_confidence": 1.0
    }
  ],
  "per_measure": [
    {
      "measure": 1,
      "note_count": 8,
      "string_match_rate": 0.875,
      "fret_match_rate": 0.75
    }
  ],
  "warnings": []
}
```

### 7.10 Pipeline 调用约定

学习闭环调用 pipeline 时使用以下参数：

```python
ctx = PipelineContext(
    timeline=timeline,           # 从 GP→MIDI 导出的 MIDI 加载
    track=cleaned_track,         # classify_timeline 选出的吉他 track
    knowledge=pipeline.registry, # 从 create_pipeline() 获取
    style_label=style_label,     # 从 style_mapper 推断
    midi_fidelity=0.5,           # 固定 0.5（评估基准一致性）
    advisor=None,                # 不使用 LLM（degraded mode）
    track_role="unknown",        # 评估时不区分 lead/rhythm
    source_track_index=0,
    degraded_mode=True,          # 标记 degraded（无 LLM）
    tuning=tuning,               # 从 GP 文件提取的 tuning
)
```

---

## 8. 待明确事项

### 8.1 已明确（主理人技术验证已确认）

| # | 事项 | 结论 |
|---|------|------|
| — | PyGuitarPro `gp.parse()` 支持 GP3/GP4/GP5 | ✅ 1587 个可用 |
| — | 弦编号一致性 | ✅ 1=高音E, 6=低音E，无需转换 |
| — | Note 对象属性 | ✅ `string`, `value`(fret), `realValue`(MIDI pitch) |
| — | Beat 对象属性 | ✅ `start`(abs tick), `duration.time`(duration ticks) |
| — | quarterTime | ✅ 960 ticks/quarter note |
| — | Tempo | ✅ `song.tempo` (BPM) |
| — | Measure | ✅ `m.start`, `m.end`, `m.timeSignature` |
| — | PyGuitarPro 不能导出 MIDI | ✅ 需自建 GP→MIDI 转换器（用 mido） |
| — | mido 可用 | ✅ 已是项目依赖 |
| — | GP tuning | ✅ `track.strings` 包含弦号和空弦 pitch |

### 8.2 设计假设（需后续验证）

| # | 假设 | 风险 | 缓解措施 |
|---|------|------|----------|
| A1 | `gp.Duration.quarterTime` 恒为 960 | 低 — 如非 960，tick→beat 转换会出错 | `GPReader` 动态读取 `gp.Duration.quarterTime` 而非硬编码 |
| A2 | tie 音符的 `note.type` 可靠区分 | 中 — PyGuitarPro 的 NoteType 枚举可能因版本不同 | 测试中验证多种 GP 文件的 tie 标记 |
| A3 | GP 文件的 measure.start 是绝对 tick（非 delta） | 低 — 已由技术验证确认 | — |
| A4 | pipeline 在 degraded mode（advisor=None）下能正常运行 | 中 — 某些 stage 可能依赖 advisor | `PipelineRunner` 先用简单 MIDI 跑通验证 |
| A5 | hand_position 推算约定（`max(1, fret)`）与 pipeline 完全一致 | 低 — 直接阅读了 `FingeringStage` 源码确认 | — |
| A6 | 风格映射表（目录→KB2 风格）足够准确 | 中 — 练习曲/游戏音乐可能映射错误 | P0 用 `unknown` 兜底，P2 考虑自动风格推断 |

### 8.3 待确认问题（沿用 PRD Q1-Q8）

| # | 问题 | 设计决策 | 后续行动 |
|---|------|----------|----------|
| Q1 | GP→MIDI 导出方式 | **已决定**: 自建 mido 转换器（不依赖 Guitar Pro 软件） | T02 实现并验证导出质量 |
| Q2 | 风格标签来源 | **已决定**: P0 用目录→风格映射表 + unknown 兜底 | `style_mapper.py` 实现；P2 考虑自动推断 |
| Q3 | 多 track 谱子处理 | **已决定**: P0 取音符最多的 track | `GPReader._select_guitar_track()` 实现 |
| Q4 | 弦编号约定一致性 | **已验证**: 一致，无需转换 | — |
| Q5 | 和弦 onset 对齐容差 | **已决定**: 0.25 beat（16 分音符） | `NoteAligner.BEAT_TOLERANCE = 0.25` |
| Q6 | Priors 反推方法 | **已决定**: P1 用统计比例直接映射；P2 考虑优化搜索 | `PriorsDeriver` 实现简单映射 |
| Q7 | 评估基准的"正确性" | **已决定**: P0 视专业谱子为唯一正确答案；P2 考虑等价指法 | 偏差计算为严格匹配 |
| Q8 | .gtp v2.21 格式 | **已决定**: P0 跳过，P2 用 Guitar Pro 软件批量转换 | `BatchEvaluator` 跳过 .gtp 扩展名 |

### 8.4 后续可优化方向（不在当前范围）

1. **等价指法匹配**: 同音高同弦不同品但把位等价的情况视为匹配（Q7 的深入）
2. **自动风格推断**: 从谱子的 tempo/音域/技巧特征自动推断风格（替代目录映射）
3. **优化搜索 priors**: 用 grid search 或贝叶斯优化最小化评估误差（替代简单统计映射）
4. **多 track 评估**: 逐 track 独立跑 round-trip（P2-6）
5. **CI 集成**: KB 变更自动触发评估，指标退化阻止合并（P2-5）
6. **可视化报告面板**: Web UI 展示评估结果（P2-1, P2-2）

---

## 附录 A: 与现有架构的集成点

| 现有模块 | 集成方式 | 是否修改 |
|----------|----------|----------|
| `midi/parser.py` → `load_midi()` | `PipelineRunner` 直接调用 | ❌ 不修改 |
| `engine/pipeline.py` → `create_pipeline()` + `execute()` | `PipelineRunner` 直接调用 | ❌ 不修改 |
| `engine/context.py` → `PipelineContext` | `PipelineRunner` 构建 context | ❌ 不修改 |
| `detection/classifier.py` → `classify_timeline()` | `PipelineRunner` 调用找吉他 track | ❌ 不修改 |
| `knowledge/engine.py` → `get_fingering_priors()` | pipeline 内部调用，接口不变 | ❌ 不修改 |
| `knowledge/registry.py` → `KnowledgeRegistry` | 新增 `from_version_dir()` 方法 | ✅ 修改（T05） |
| `knowledge/models.py` → `KnowledgeEntry` | 新增 `to_dict()` 方法 | ✅ 修改（T05） |
| `guitar/fretboard.py` → `candidate_positions()` | 评估时验证 GT 合法性（可选） | ❌ 不修改 |
| `guitar/instrument.py` → `GuitarTuning` | `PipelineRunner` 构建 tuning | ❌ 不修改 |
| `ir/models.py` → `GuitarProjectIR` | `NoteAligner` 读取 IR 音符 | ❌ 不修改 |
| `exporters/gp5.py` → `GP5Exporter` | 重建结果可选导出 GP5 供人工检查 | ❌ 不修改 |

## 附录 B: CLI 使用示例

```bash
# P0: 批量评估
python -m fretpilot.elearning evaluate \
    --input-dir /data/guitar_songs \
    --output /tmp/baseline_report.json \
    --max-files 100  # 可选：限制评估文件数

# P0: 单文件评估
python -m fretpilot.elearning evaluate \
    --input /data/guitar_songs/song.gp5 \
    --output /tmp/single_report.json

# P1: 知识提取 + KB 更新 + A/B 对比
python -m fretpilot.elearning learn \
    --input-dir /data/guitar_songs \
    --kb-root backend/src/fretpilot/knowledge \
    --output /tmp/learning_report.json

# P1: KB 版本管理
python -m fretpilot.elearning kb list-versions
python -m fretpilot.elearning kb rollback --version 2026.08.3
python -m fretpilot.elearning kb diff --a 2026.08.3 --b 2026.08.4
```
