# BandPilot — Mixed MIDI to Professional Score

| Field | Value |
|-------|-------|
| **Version** | 1.0 |
| **Date** | 2026-08-19 |
| **Status** | Draft |
| **Author** | BandPilot Team |

---

## 1. Product Vision

**BandPilot** 是一个混合 MIDI 自动修复系统。导入 AI 生成的混合 MIDI，自动分轨识别乐器（吉他、鼓、贝斯等），分别走对应子模块的修复 pipeline，最终合并导出为 Guitar Pro (.gp5) 文件。

```
Mixed MIDI ──▶ Auto-Detect & Separate ──┬──▶ FretPilot (Guitar) ──┐
                                          ├──▶ StickPilot (Drums)  ──┤
                                          ├──▶ BassPilot (future)  ──┤
                                          └──▶ ...                  ──┴──▶ Merge ──▶ .gp5
```

### 子模块

| Module | Instrument | Status | Pipeline |
|--------|-----------|--------|----------|
| **FretPilot** | Guitar (6-string) | ✅ Existing | 8-stage: Quantize → MeasureSplit → Tie → Voice → Separation → Fingering → Articulation → Assemble |
| **StickPilot** | Drums (kit) | 🆕 New | 8-stage: Quantize → MeasureSplit → DrumMap → PatternDetect → Velocity → Sticking → Notation → Assemble |
| BassPilot | Bass (4/5-string) | 🔜 Future | Reuse FretPilot with bass tuning |
| KeysPilot | Keyboards | 🔜 Future | Simple quantize + notation |

---

## 2. BandPilot Orchestration Layer

### 2.1 Import & Auto-Detect

```
Input: mixed .mid file
  ↓
1. Parse MIDI → NormalizedTimeline (existing midi/parser.py)
  ↓
2. Resolve logical streams (existing detection/streams.py)
  ↓
3. Classify each stream by instrument family:
   - Guitar/Bass → guitar family (existing detection/classifier.py)
   - Drums → drum family (NEW: drum/classifier.py)
   - Keys/Other → passthrough
  ↓
4. Route each stream to the appropriate sub-module pipeline
  ↓
5. Merge all pipeline outputs into a single GuitarProjectIR
  ↓
6. Export as .gp5 with multiple tracks
```

### 2.2 Drum Detection Criteria

MIDI drum detection signals (priority order):
1. **Channel 10** (MIDI standard drum channel) — strongest signal
2. **Track name keywords**: "drum", "perc", "beat", "kit", "sticks"
3. **Note pitch range**: drums use pitches 35-81 (GM drum map)
4. **No pitch variation / rapid repeats** on same pitch (drum hits vs melodic notes)

### 2.3 GM Drum Map (Standard MIDI Percussion)

| Pitch | Drum Piece | StickPilot Name |
|-------|-----------|-----------------|
| 35 | Acoustic Bass Drum | kick |
| 36 | Bass Drum 1 | kick |
| 38 | Acoustic Snare | snare |
| 40 | Electric Snare | snare |
| 42 | Closed Hi-Hat | hihat_closed |
| 44 | Pedal Hi-Hat | hihat_pedal |
| 46 | Open Hi-Hat | hihat_open |
| 47-50 | Toms (low-mid-high) | tom_low, tom_mid, tom_high, tom_floor |
| 49 | Crash Cymbal 1 | crash |
| 51 | Ride Cymbal 1 | ride |
| 52 | Chinese Cymbal | china |
| 53 | Ride Bell | ride_bell |
| 55 | Splash Cymbal | splash |
| 57 | Crash Cymbal 2 | crash_2 |
| 59 | Ride Cymbal 2 | ride_2 |

---

## 3. StickPilot — Drum Pipeline Architecture

### 3.1 Pipeline Stages (8-stage, mirroring FretPilot)

| Stage | Name | Input → Output | Guitar Equivalent | Description |
|-------|------|----------------|-------------------|-------------|
| S1 | **Quantize** | NormalizedNote → QuantizedNote | Quantize | Snap drum hit onsets to rhythmic grid (16th/32nd note) |
| S2 | **MeasureSplit** | QuantizedNote → SplitNote | MeasureSplit | Compute measure boundaries, split cross-boundary hits |
| S3 | **DrumMap** | SplitNote → MappedNote | (new, no guitar equiv) | Map MIDI pitches to drum pieces via GM drum map; detect kit type |
| S4 | **PatternDetect** | MappedNote → PatternNote | (new) | Classify measures as beat vs fill; detect groove pattern; identify repetitive patterns |
| S5 | **Velocity** | PatternNote → VelocityNote | (partial: velocity remap) | Normalize velocities per drum piece; dynamics optimization; ghost note detection |
| S6 | **Sticking** | VelocityNote → StickedNote | Fingering | Suggest R/L hand sticking; detect double-stroke rolls, flams, drags |
| S7 | **Notation** | StickedNote → NotatedNote | Articulation | Clean up notation: remove redundant hits, optimize rest placement, add repeat signs |
| S8 | **Assemble** | All → DrumProjectIR | Assemble | Assemble final DrumProjectIR with provenance |

### 3.2 Drum-Specific Data Structures

```python
# drum/drumkit.py (NEW — mirrors guitar/instrument.py)

@dataclass(frozen=True)
class DrumPiece:
    name: str           # "kick", "snare", "hihat_closed", ...
    midi_pitches: tuple[int, ...]  # (36,) or (35, 36) for kick
    category: str       # "kick", "snare", "tom", "cymbal", "hihat"
    hand: str           # "both", "right", "left" — default sticking

@dataclass(frozen=True)
class DrumKit:
    name: str           # "standard_5pc", "standard_7pc", "extended"
    pieces: tuple[DrumPiece, ...]
    
STANDARD_5PC = DrumKit(
    name="standard_5pc",
    pieces=(
        DrumPiece("kick", (35, 36), "kick", "right"),
        DrumPiece("snare", (38, 40), "snare", "left"),
        DrumPiece("hihat_closed", (42,), "hihat", "right"),
        DrumPiece("hihat_open", (46,), "hihat", "right"),
        DrumPiece("crash", (49, 57), "cymbal", "right"),
        DrumPiece("ride", (51, 59), "cymbal", "right"),
        DrumPiece("tom_high", (48, 50), "tom", "right"),
        DrumPiece("tom_mid", (47, 45), "tom", "right"),
        DrumPiece("tom_low", (43, 41), "tom", "right"),
        DrumPiece("tom_floor", (45, 43), "tom", "right"),
    ),
)
```

```python
# ir/drum_models.py (NEW — mirrors ir/models.py)

@dataclass(frozen=True)
class DrumHitLocation:
    piece: str          # "kick", "snare", "hihat_closed", ...
    sticking: str       # "R", "L", "both", ""
    technique: str      # "normal", "ghost", "accent", "flam", "drag", "roll"

@dataclass(frozen=True)
class DrumNoteEvent:
    id: str
    source_note_index: int
    pitch: int
    piece: str                    # mapped drum piece
    score: ScoreTiming
    performance: PerformanceTiming
    location: DrumHitLocation
    confidence: NoteConfidence

@dataclass(frozen=True)
class DrumTrackIR:
    id: str
    name: str
    kit: str                      # drum kit name
    measures: list[DrumMeasure]
    
@dataclass(frozen=True)
class DrumProjectIR:
    title: str
    source: str
    tempo_map: list[IRTempoEvent]
    time_signatures: list[IRTimeSignatureEvent]
    tracks: list[DrumTrackIR]     # drum tracks
    knowledge: IRKnowledgeReference
    style_label: str
    changes: list[Transformation]
    warnings: list[str]
```

### 3.3 Drum Knowledge Base

```
knowledge/assets/
├── guitar_tunings.json        (existing)
├── kb1_arrangement.json       (existing — guitar)
├── kb2_performance.json       (existing — guitar)
├── kb3_notation.json          (existing — guitar)
├── kb4_instruments.json       (existing — guitar)
├── drum_kb1_arrangement.json  (NEW — drum style priors)
├── drum_kb2_sticking.json     (NEW — sticking pattern priors)
└── drum_kb3_notation.json     (NEW — drum notation conventions)
```

**drum_kb1_arrangement.json** — style-specific drum priors:
- `beat_density`: notes per beat (metal: 2-4, rock: 1-2, pop: 1, funk: 2-3)
- `kick_pattern_bias`: kick on downbeats vs syncopated
- `snare_backbeat_bias`: snare on 2 & 4
- `hihat_subdivision`: 8th vs 16th notes
- `fill_frequency`: fills per 8 bars

**drum_kb2_sticking.json** — sticking pattern priors:
- `right_hand_bias`: R hand dominance for single-stroke rolls
- `double_stroke_rate`: frequency of double-stroke rolls
- `flam_rate`: frequency of flams
- `hand_switch_pattern`: R-L-R-L vs R-R-L-L patterns

### 3.4 Drum Style Detection

| Style | Kick Pattern | Snare | Hi-Hat | Fills |
|-------|-------------|-------|--------|-------|
| Metal | Double bass, 16th notes | Strong backbeat + ghost | 16th note, ride bell | Frequent, tom-heavy |
| Rock | 1 & 3, occasional syncopation | Strong 2 & 4 | 8th notes | Moderate |
| Pop | Simple 1 & 3 | Light 2 & 4 | 8th/quarter | Sparse |
| Funk | Syncopated, ghost notes | Ghost notes + accents | 16th notes | Moderate, syncopated |
| Jazz | Swing, ride cymbal | Brush/light | Ride pattern | Fills with brush/sticks |

---

## 4. BandPilot API Design

### 4.1 New Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/projects` | Import mixed MIDI (existing, enhanced auto-detect) |
| GET | `/api/projects/{id}/tracks` | List detected tracks with instrument family |
| POST | `/api/projects/{id}/repair` | Run BandPilot orchestration (auto-routes to sub-modules) |
| GET | `/api/projects/{id}/drum-report` | StickPilot-specific repair report |
| GET | `/api/projects/{id}/sticking` | Drum sticking visualization data |

### 4.2 Enhanced Track Detection Response

```json
{
  "tracks": [
    {
      "index": 0,
      "name": "Guitar",
      "family": "guitar",
      "is_guitar": true,
      "role": "lead",
      "confidence": 0.95,
      "note_count": 420
    },
    {
      "index": 1,
      "name": "Drums",
      "family": "drums",
      "is_drum": true,
      "role": "kit",
      "confidence": 0.98,
      "note_count": 380,
      "kit_type": "standard_5pc",
      "detected_pieces": ["kick", "snare", "hihat_closed", "crash", "tom_high"]
    }
  ]
}
```

### 4.3 Repair Response (Enhanced)

```json
{
  "project_id": 1,
  "status": "repaired",
  "tracks_repaired": [
    {
      "track_index": 0,
      "module": "fretpilot",
      "stages_completed": 8,
      "note_count": 420,
      "change_count": 35
    },
    {
      "track_index": 1,
      "module": "stickpilot",
      "stages_completed": 8,
      "note_count": 380,
      "change_count": 28,
      "drum_report": {
        "kit_type": "standard_5pc",
        "style_detected": "metal",
        "patterns": ["beat", "beat", "fill", "beat"],
        "sticking_suggested": true,
        "velocity_normalized": true
      }
    }
  ]
}
```

---

## 5. BandPilot Frontend Design

### 5.1 Import Flow

```
Import Page (existing, enhanced)
  ↓
Upload mixed MIDI
  ↓
Auto-detect shows track list with instrument family icons:
  🎸 Guitar (lead) — 420 notes, 95% confidence
  🥁 Drums (kit) — 380 notes, 98% confidence, standard 5-piece
  ↓
Click "Repair All" → BandPilot orchestration
  ↓
Workbench shows parallel pipeline progress:
  Track 1 (Guitar): Quantize ✓ → MeasureSplit ✓ → ... → Assemble ✓
  Track 2 (Drums):  Quantize ✓ → DrumMap ✓ → ... → Assemble ✓
  ↓
Export → .gp5 with both guitar + drum tracks
```

### 5.2 Workbench (Enhanced)

- **Left panel**: Track list with instrument family icons; per-track config (fidelity, tuning for guitar; kit type, sticking style for drums)
- **Center**: Tabbed score preview (guitar tab / drum notation)
- **Right panel**: Per-track repair reports

### 5.3 Drum Visualization (NEW)

- **DrumKit Diagram**: SVG showing kit layout with hit heatmap
- **Pattern Timeline**: Beat vs fill regions across measures
- **Sticking Notation**: R/L hand annotations on drum hits
- **Velocity Heatmap**: Color-coded velocity per drum piece over time

---

## 6. Implementation Plan

### Phase 1: Core StickPilot Backend (Week 1-2)

| Task | Description | Dependencies |
|------|-------------|-------------|
| S1 | `drum/drumkit.py` — DrumPiece, DrumKit, GM drum map | None |
| S2 | `drum/classifier.py` — drum track detection | S1 |
| S3 | `ir/drum_models.py` — DrumProjectIR data structures | S1 |
| S4 | `engine/stages/drum_map.py` — S3 stage: pitch → drum piece | S1, S3 |
| S5 | `engine/stages/pattern_detect.py` — S4 stage: beat/fill classification | S4 |
| S6 | `engine/stages/velocity.py` — S5 stage: velocity normalization | S5 |
| S7 | `engine/stages/sticking.py` — S6 stage: R/L hand suggestion | S6 |
| S8 | `engine/stages/drum_notation.py` — S7 stage: notation cleanup | S7 |
| S9 | `engine/stages/drum_assemble.py` — S8 stage: assemble DrumProjectIR | S8 |
| S10 | Drum pipeline orchestration + context | S4-S9 |
| S11 | Drum knowledge base JSON assets | S1 |
| S12 | BandPilot orchestrator: auto-detect + route + merge | S10, existing FretPilot |

### Phase 2: API + Frontend (Week 2-3)

| Task | Description | Dependencies |
|------|-------------|-------------|
| F1 | Enhanced track detection API (family: guitar/drums) | S2 |
| F2 | BandPilot repair API (parallel pipeline execution) | S12 |
| F3 | Drum repair report API | S10 |
| F4 | Frontend: track list with instrument family icons | F1 |
| F5 | Frontend: parallel pipeline progress (guitar + drums) | F2 |
| F6 | Frontend: drum visualization (kit diagram, pattern timeline) | F3 |
| F7 | Frontend: sticking notation display | F3 |
| F8 | Frontend: multi-track score preview (guitar tab + drum notation) | F2 |
| F9 | Export: merge guitar + drum IRs into single .gp5 | S12 |

### Phase 3: Polish & Knowledge (Week 3-4)

| Task | Description | Dependencies |
|------|-------------|-------------|
| P1 | Drum style detection (metal/rock/pop/funk/jazz) | S5 |
| P2 | Drum learning loop (upload drum tabs, extract sticking priors) | S11 |
| P3 | Drum KB versioning (reuse existing KBWriter) | P2 |
| P4 | Frontend: BandPilot branding + sidebar with both modules | F8 |
| P5 | Integration tests: mixed MIDI → multi-track .gp5 | S12, F9 |

---

## 7. Architecture Reuse Matrix

| FretPilot Component | Reuse for StickPilot | Notes |
|---------------------|---------------------|-------|
| `midi/parser.py` | ✅ Direct reuse | Generic MIDI parsing |
| `midi/models.py` | ✅ Direct reuse | NormalizedNote etc. |
| `midi/gm.py` | ✅ Extend | Add drum program detection |
| `detection/streams.py` | ✅ Direct reuse | Stream resolution |
| `detection/separation.py` | ✅ Direct reuse | Pitch separation algorithm |
| `engine/pipeline.py` | ✅ Direct reuse | Pipeline orchestrator |
| `engine/context.py` | 🔄 Extend | Add drum-specific intermediate types |
| `engine/stages/quantize.py` | ✅ Direct reuse | Generic quantization |
| `engine/stages/measure_split.py` | ✅ Direct reuse | Generic measure splitting |
| `engine/stages/tie.py` | ❌ Skip | Drum notes don't tie |
| `engine/stages/voice.py` | ❌ Skip | Drums don't have voices |
| `engine/stages/separation.py` | ❌ Skip | No riff/melody split for drums |
| `engine/stages/fingering.py` | 🔄 Replace | → `sticking.py` (R/L hand instead of string/fret) |
| `engine/stages/articulation.py` | 🔄 Replace | → `drum_notation.py` (ghost/accent instead of palm_mute/hammer_on) |
| `engine/stages/assemble.py` | 🔄 New | `drum_assemble.py` — assemble DrumProjectIR |
| `guitar/fretboard.py` | ❌ Not needed | Drums have no fretboard |
| `guitar/instrument.py` | 🔄 Replace | → `drum/drumkit.py` (DrumKit instead of GuitarTuning) |
| `ir/models.py` | 🔄 New file | `ir/drum_models.py` — DrumProjectIR |
| `ir/serde.py` | 🔄 Extend | Add drum IR serialization |
| `knowledge/registry.py` | ✅ Direct reuse | Generic KB framework |
| `knowledge/engine.py` | ✅ Direct reuse | Generic rule engine |
| `exporters/gp5.py` | 🔄 Extend | Add drum track writing to GP5 |
| `db/models.py` | 🔄 Extend | Add drum-specific fields to projects |

---

## 8. Product Brand

**BandPilot** — "Your band's MIDI, perfectly scored."

- FretPilot (🎸 Guitar) + StickPilot (🥁 Drums) = BandPilot
- Logo: stylized pick + drumstick crossed
- Brand color: amber `#E8A24B` (shared with FretPilot)
- Drum accent color: `#4FD1C5` (cyan, currently Lead color)

---

## 9. Success Metrics

- Drum detection accuracy: >95% on channel-10 drums, >85% on non-standard mappings
- Sticking suggestion accuracy: >80% agreement with human drummers
- Pattern detection: >90% correct beat vs fill classification
- End-to-end: mixed MIDI → multi-track .gp5 in <10 seconds for typical song
