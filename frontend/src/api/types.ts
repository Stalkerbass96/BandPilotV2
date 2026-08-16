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

// ─── API envelope ───

export interface ApiEnvelope<T> {
  code: number;
  data: T;
  message: string;
}
