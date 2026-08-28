/** TypeScript types mirroring the FretPilot v2 backend API contracts. */

// ─── Auth ───

export interface UserResponse {
  id: number;
  email: string;
}

export interface AuthResponse {
  token: string;
  user: UserResponse;
}

// ─── BYOK ───

export interface ByokConfig {
  provider: string;
  api_key: string;
  base_url: string | null;
  model: string | null;
}

export interface ByokResponse {
  provider: string;
  key_masked: string;
  base_url: string | null;
  model: string | null;
}

export interface ByokTestResponse {
  ok: boolean;
  message: string;
}

// ─── Tunings ───

export interface TuningInfo {
  id: string;
  name: string;
  display_name: string;
  string_count: number;
  min_pitch: number;
  max_pitch: number;
}

// ─── Projects ───

export interface ProjectItem {
  id: number;
  title: string;
  source_filename: string;
  status: string;
  style_label: string;
  degraded_mode: boolean;
  instrument_family: string;
}

export interface ProjectDetail extends ProjectItem {
  tracks: TrackSummaryItem[];
}

export interface BlankProjectRequest {
  title: string;
  instrument_family: "guitar" | "drums" | "bass" | "keys" | "generic";
  bpm: number;
  numerator: number;
  denominator: 1 | 2 | 4 | 8 | 16 | 32;
}

export interface TrackSummaryItem {
  index: number;
  name: string;
  family: string;
  is_guitar: boolean;
  role: string;
  confidence: number;
  reason?: string;
  user_overridden?: boolean;
  note_count: number;
  is_drum?: boolean;
  kit_type?: string;
  detected_pieces?: string[];
}

// ─── Track Family (BandPilot multi-instrument) ───

export interface TrackFamilyInfo {
  family: string;
  is_drum: boolean;
  kit_type?: string;
  detected_pieces?: string[];
}

export interface CleanupInfo {
  tuning_id: string;
  tuning_display_name: string;
  tempo_dedup_count: number;
  out_of_range_count: number;
  velocity_remapped: boolean;
  overlaps_truncated: number;
  total_actions: number;
}

export interface RewriteInfo {
  degraded: boolean;
  deletions: number;
  transpositions: number;
  total: number;
  reasons: string[];
}

export interface SeparationSegmentInfo {
  start_measure: number;
  end_measure: number;
  split_pitch: number;
  low_note_count: number;
  high_note_count: number;
  confidence: number;
  reason: string;
}

export interface SeparationInfo {
  detected: boolean;
  total_confidence: number;
  segments: SeparationSegmentInfo[];
  warnings: string[];
}

export interface DrumReport {
  kit_type: string;
  style_detected: string;
  patterns: string[];
  sticking_suggested: boolean;
  velocity_normalized: boolean;
  piece_stats: DrumPieceStat[];
}

export interface DrumPieceStat {
  name: string;
  hit_count: number;
  avg_velocity: number;
}

export interface TrackRepairInfo {
  track_index: number;
  track_name: string;
  family: string;
  module: string;
  stages_completed: number;
  note_count: number;
  change_count: number;
  drum_report?: DrumReport;
  skipped: boolean;
  failed: boolean;
  error: string | null;
  warnings: string[];
}

export interface RepairResponse {
  project_id: number;
  job_id: number;
  status: string;
  style_label: string;
  degraded_mode: boolean;
  note_count: number;
  change_count: number;
  cleanup: CleanupInfo | null;
  rewrite: RewriteInfo | null;
  separation: SeparationInfo | null;
  tracks_repaired: TrackRepairInfo[];
  has_drums: boolean;
  arrangement_mode: ArrangementMode;
  validation_status: string;
  validation_issues: ValidationIssue[];
}

export interface RepairJob {
  id: number;
  run_id: string | null;
  status: string;
  progress: number;
  arrangement_mode: ArrangementMode;
  settings: Record<string, unknown>;
  result: RepairResponse | null;
  error_message: string | null;
  created_at: string;
  completed_at: string | null;
}

export interface RepairAcceptedResponse {
  project_id: number;
  job: RepairJob;
  status_url: string;
}

export type ArrangementMode = "faithful" | "playable_arrangement" | "creative_rewrite";

export interface ValidationIssue {
  code: string;
  severity: string;
  message: string;
  track_id: string | null;
  note_ids: string[];
}

export interface TransformationRecord {
  id: string;
  stage: string;
  source_note_index: number;
  before: Record<string, unknown>;
  after: Record<string, unknown>;
  confidence: number;
  reason: string;
  knowledge_ref: string | null;
}

export interface RepairReport {
  changes: TransformationRecord[];
  summary: {
    total_changes: number;
    warnings: string[];
    style_label: string;
    degraded_mode: boolean;
    note_count: number;
    unresolved_note_count?: number;
    validation_status?: string;
    validation_issues?: ValidationIssue[];
    schema_version?: string;
    arrangement_mode?: ArrangementMode;
  };
}

// ─── Exports ───

export interface ExportResponse {
  download_url: string;
  format_id: string;
  note_count: number;
  revision_id: string | null;
  revision_hash: string | null;
}

export interface ExportRecord {
  id: number;
  format_id: string;
  note_count: number;
  revision_id: string | null;
  revision_hash: string | null;
  created_at: string | null;
}

// ─── ScoreDocument editor contract ───

export interface ScoreRational {
  numerator: number;
  denominator: number;
}

export interface ScoreInstrumentRealization {
  kind: string;
  string: number | null;
  fret: number | null;
  fretting_digit: number | null;
  hand_position: number | null;
  piece: string | null;
  sticking: string | null;
  hit_technique: string | null;
  hand: string | null;
  finger: number | null;
  pedal: string | null;
}

export interface ScoreNote {
  id: string;
  pitch: number;
  source: {
    source_track_index: number;
    source_note_index: number;
    origin: string;
  } | null;
  realization: ScoreInstrumentRealization;
  technique_ids: string[];
  properties: Record<string, unknown>;
}

export interface ScoreBeat {
  id: string;
  start: ScoreRational;
  duration: ScoreRational;
  voice: number;
  staff_id: string;
  kind: "notes" | "rest";
  notes: ScoreNote[];
  tie_in: boolean;
  tie_out: boolean;
  properties: Record<string, unknown>;
}

export interface ScoreMeasure {
  id: string;
  number: number;
  start: ScoreRational;
  duration: ScoreRational;
  numerator: number;
  denominator: number;
  beats: ScoreBeat[];
  annotations: Record<string, unknown>;
}

export interface ScoreStaff {
  id: string;
  order: number;
  kind: string;
  line_count: number;
}

export interface ScoreTrack {
  id: string;
  order: number;
  name: string;
  family: string;
  role: string;
  source_track_indices: number[];
  instrument: Record<string, unknown>;
  staves: ScoreStaff[];
  measures: ScoreMeasure[];
  notation_mode: string;
  mixer: ScoreTrackMixer;
}

export interface ScoreTrackMixer {
  volume: number;
  pan: number;
  mute: boolean;
  solo: boolean;
}

export interface ScorePerformanceEvent {
  id: string;
  note_id: string;
  start: ScoreRational;
  duration: ScoreRational;
  velocity: number;
  controls: Array<Record<string, unknown>>;
}

export interface ScorePerformanceLayer {
  profile_id: string;
  events: ScorePerformanceEvent[];
}

export interface ScoreTechnique {
  id: string;
  type: string;
  note_ids: string[];
  confidence: number;
  reason: string;
  parameters: Record<string, number>;
}

export interface ScoreTempoChange {
  id: string;
  position: ScoreRational;
  bpm: number;
}

export interface ScoreTimeSignatureChange {
  id: string;
  position: ScoreRational;
  numerator: number;
  denominator: number;
}

export interface ScoreDocument {
  id: string;
  schema_version: string;
  title: string;
  source: Record<string, unknown>;
  analysis: Record<string, unknown>;
  tracks: ScoreTrack[];
  tempo_map: ScoreTempoChange[];
  time_signatures: ScoreTimeSignatureChange[];
  techniques: ScoreTechnique[];
  performance: ScorePerformanceLayer;
  unresolved_events: Array<Record<string, unknown>>;
  validation: {
    status: string;
    issues: Array<Record<string, unknown>>;
  };
  pins: Record<string, unknown>;
  arrangement_mode: string;
  knowledge: Record<string, unknown> | null;
  transformations: Array<Record<string, unknown>>;
  warnings: string[];
}

export interface ScoreDocumentEnvelope {
  document: ScoreDocument;
  revision: {
    id: string;
    number: number;
    hash: string;
    is_current: boolean;
  };
}

export type ScoreOperation =
  | {
      kind: "set_note_pitch";
      note_id: string;
      pitch: number;
      expected_pitch: number | null;
    }
  | {
      kind: "set_beat_duration";
      beat_id: string;
      duration: ScoreRational;
      expected_duration: ScoreRational | null;
    }
  | {
      kind: "set_beat_tie";
      beat_id: string;
      tie_in: boolean;
      tie_out: boolean;
      expected_tie_in: boolean | null;
      expected_tie_out: boolean | null;
    }
  | {
      kind: "set_beat_dynamic";
      beat_id: string;
      dynamic: string | null;
      expected_dynamic: string | null;
    }
  | {
      kind: "set_performance_velocity";
      note_id: string;
      velocity: number;
      expected_velocity: number | null;
    }
  | {
      kind: "set_beat_voice";
      beat_id: string;
      voice: number;
      expected_voice: number | null;
    }
  | {
      kind: "set_note_fretting";
      note_id: string;
      string: number;
      fret: number;
      expected_string: number | null;
      expected_fret: number | null;
    }
  | {
      kind: "add_note";
      beat_id: string;
      note: ScoreNote;
      performance_event: ScorePerformanceEvent;
      expected_beat_kind: "notes" | "rest" | null;
    }
  | {
      kind: "delete_note";
      beat_id: string;
      note_id: string;
      expected_note_hash: string | null;
    }
  | {
      kind: "add_technique";
      technique: ScoreTechnique;
    }
  | {
      kind: "delete_technique";
      technique_id: string;
      expected_technique_hash: string | null;
    }
  | {
      kind: "insert_beat";
      track_id: string;
      measure_id: string;
      beat: ScoreBeat;
      performance_events: ScorePerformanceEvent[];
    }
  | {
      kind: "delete_beat";
      beat_id: string;
      note_ids: string[];
      expected_beat_hash: string | null;
    }
  | {
      kind: "insert_measure_group";
      entries: Array<{ track_id: string; measure: ScoreMeasure }>;
      performance_events: ScorePerformanceEvent[];
      techniques: ScoreTechnique[];
      tempo_changes: ScoreTempoChange[];
      time_signatures: ScoreTimeSignatureChange[];
    }
  | {
      kind: "delete_measure_group";
      measure_ids: string[];
      expected_measure_hashes: Record<string, string>;
    }
  | {
      kind: "set_track_name";
      track_id: string;
      name: string;
      expected_name: string | null;
    }
  | {
      kind: "set_track_instrument";
      track_id: string;
      instrument: Record<string, unknown>;
      expected_instrument: Record<string, unknown> | null;
    }
  | {
      kind: "set_track_notation_mode";
      track_id: string;
      notation_mode: string;
      expected_notation_mode: string | null;
    }
  | {
      kind: "set_track_mixer";
      track_id: string;
      mixer: ScoreTrackMixer;
      expected_mixer: ScoreTrackMixer | null;
    }
  | {
      kind: "reorder_tracks";
      track_ids: string[];
      expected_track_ids: string[] | null;
    }
  | {
      kind: "insert_track";
      track: ScoreTrack;
    }
  | {
      kind: "delete_track";
      track_id: string;
      expected_track_hash: string | null;
    };

export interface ScoreSelectionAnchor {
  scope: string;
  track_ids: string[];
  measure_ids?: string[];
  beat_ids: string[];
  note_ids: string[];
  start: ScoreRational | null;
  end: ScoreRational | null;
}

export interface ScoreCommandRequest {
  schema_version?: "1.0";
  command_id: string;
  base_revision: number;
  origin?: "manual";
  intent: string;
  operations: ScoreOperation[];
  selection?: ScoreSelectionAnchor | null;
  created_at?: string;
}

export interface ScoreCommandResult {
  command_id: string;
  revision_id: string;
  revision: number;
  document_hash: string;
  rebased: boolean;
  idempotent_replay: boolean;
}

export interface AcceptedScoreCommand {
  command_id: string;
  base_revision: number;
  accepted_revision: number;
  rebased: boolean;
  status: "accepted";
  transaction: Record<string, unknown>;
}

export interface ScoreCommandCatchup {
  items: AcceptedScoreCommand[];
  after: number;
  current_revision: number;
  has_more: boolean;
}

// ─── E-Learning ───

export interface StyleStatsInfo {
  style: string;
  sample_count: number;
  total_notes: number;
  open_string_rate: number;
  avg_string_skip: number;
  note_overlap_rate: number;
  staccato_rate: number;
  top_chord_shapes: Record<string, number>;
}

/** A scalar prior weight, or a nested mapping (e.g. chord_shapes). */
export type PriorValue = number | Record<string, number>;

export interface DerivedPriorsInfo {
  style: string;
  knowledge_id: string;
  payload: Record<string, PriorValue>;
  confidence: number;
  source_count: number;
  derivation_method: string;
}

export interface LearnResponse {
  parsed_files: number;
  total_files: number;
  failed_files: { file: string; error: string }[];
  style_stats: StyleStatsInfo[];
  derived_priors: DerivedPriorsInfo[];
  new_version: string;
  promoted: boolean;
  total_notes: number;
}

/** Per-style statistics returned by the drum learning loop (StickPilot). */
export interface DrumStyleStatsInfo {
  style: string;
  sample_count: number;
  total_notes: number;
  total_measures: number;
  hit_density: number;
  avg_inter_hit_gap_beats: number;
  velocity_mean: number;
  accent_rate: number;
  ghost_note_rate: number;
  flam_rate: number;
  double_stroke_rate: number;
  right_hand_rate: number;
  hand_switch_pattern: string;
  top_pieces: Record<string, number>;
  quarter_or_shorter_rate: number;
  voice_two_rate: number;
  foot_voice_two_rate: number;
  top_written_durations: Record<string, number>;
}

/** Response of POST /api/elearning/learn/drum (mirrors LearnResponse). */
export interface DrumLearnResponse {
  parsed_files: number;
  total_files: number;
  failed_files: { file: string; error: string }[];
  style_stats: DrumStyleStatsInfo[];
  derived_priors: DerivedPriorsInfo[];
  new_version: string;
  promoted: boolean;
  total_notes: number;
}

export interface KbVersion {
  version: string;
  timestamp: string;
  source_type: string;
  styles_updated: string[];
  styles_present?: string[];
  knowledge_ids_updated: string[];
  total_sources: number;
  avg_confidence: number;
  status?: "candidate" | "evaluated" | "promoted";
}

export interface VersionsResponse {
  items: KbVersion[];
  active_version: string;
}

export interface VersionDiff {
  version_a: string;
  version_b: string;
  entry_diffs: Record<
    string,
    {
      payload_diff: Record<string, { a: PriorValue | null; b: PriorValue | null; delta: number | null }>;
      source_type_a: string;
      source_type_b: string;
    }
  >;
}

// ─── API envelope ───

export interface ApiEnvelope<T> {
  code: number;
  data: T;
  message: string;
}
