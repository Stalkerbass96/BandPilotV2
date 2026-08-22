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
  instrument_family?: string;
}

export interface ProjectDetail extends ProjectItem {
  tracks: TrackSummaryItem[];
}

export interface TrackSummaryItem {
  index: number;
  name: string;
  family: string;
  is_guitar: boolean;
  role: string;
  confidence: number;
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
}

export interface TrackRepairInfo {
  track_index: number;
  module: string;
  stages_completed: number;
  note_count: number;
  change_count: number;
  drum_report?: DrumReport;
}

export interface RepairResponse {
  project_id: number;
  status: string;
  style_label: string;
  degraded_mode: boolean;
  note_count: number;
  change_count: number;
  cleanup: CleanupInfo | null;
  rewrite: RewriteInfo | null;
  separation: SeparationInfo | null;
  tracks_repaired?: TrackRepairInfo[];
  has_drums?: boolean;
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
  };
}

// ─── Exports ───

export interface ExportResponse {
  download_url: string;
  format_id: string;
  note_count: number;
}

export interface ExportRecord {
  id: number;
  format_id: string;
  note_count: number;
  created_at: string | null;
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
