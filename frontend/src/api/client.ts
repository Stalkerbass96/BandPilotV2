/** Axios HTTP client with JWT interceptor and typed API functions. */

import axios, { type AxiosInstance } from "axios";
import { useAuthStore } from "../store/auth";
import type {
  ApiEnvelope,
  AuthResponse,
  ByokConfig,
  ByokResponse,
  ByokTestResponse,
  ExportRecord,
  ExportResponse,
  LearnResponse,
  ProjectDetail,
  ProjectItem,
  RepairReport,
  RepairResponse,
  TuningInfo,
  VersionDiff,
  VersionsResponse,
} from "./types";

const BASE_URL = "/api";

/** Shared axios instance. The JWT token is injected on every request. */
const http: AxiosInstance = axios.create({
  baseURL: BASE_URL,
  timeout: 60_000,
  headers: { "Content-Type": "application/json" },
});

http.interceptors.request.use((config) => {
  const token = useAuthStore.getState().token;
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

http.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      useAuthStore.getState().logout();
    }
    return Promise.reject(error);
  },
);

function unwrap<T>(response: { data: ApiEnvelope<T> | T }): T {
  const body = response.data as ApiEnvelope<T> | T;
  if (
    typeof body === "object" &&
    body !== null &&
    "code" in body &&
    "data" in body
  ) {
    return (body as ApiEnvelope<T>).data;
  }
  return body as T;
}

// ─── Auth API ───

export const authApi = {
  async register(email: string, password: string): Promise<AuthResponse> {
    const res = await http.post("/auth/register", { email, password });
    return res.data as AuthResponse;
  },

  async login(email: string, password: string): Promise<AuthResponse> {
    const res = await http.post("/auth/login", { email, password });
    return res.data as AuthResponse;
  },

  async me(): Promise<{ id: number; email: string }> {
    const res = await http.get("/auth/me");
    return res.data as { id: number; email: string };
  },
};

// ─── BYOK API ───

export const byokApi = {
  async get(): Promise<ByokResponse | null> {
    const res = await http.get("/byok");
    return (res.data as ByokResponse | null) ?? null;
  },

  async save(config: ByokConfig): Promise<ByokResponse> {
    const res = await http.post("/byok", config);
    return res.data as ByokResponse;
  },

  async test(config: ByokConfig): Promise<ByokTestResponse> {
    const res = await http.post("/byok/test", config);
    return res.data as ByokTestResponse;
  },

  async remove(): Promise<void> {
    await http.delete("/byok");
  },
};

// ─── Projects API ───

export const projectsApi = {
  async list(): Promise<{ items: ProjectItem[]; total: number }> {
    const res = await http.get("/projects");
    return unwrap(res.data) as { items: ProjectItem[]; total: number };
  },

  async create(file: File, title?: string): Promise<ProjectItem> {
    const form = new FormData();
    form.append("file", file);
    if (title) form.append("title", title);
    const res = await http.post("/projects", form, {
      headers: { "Content-Type": "multipart/form-data" },
    });
    return unwrap(res.data) as ProjectItem;
  },

  async get(id: number): Promise<ProjectDetail> {
    const res = await http.get(`/projects/${id}`);
    return unwrap(res.data) as ProjectDetail;
  },

  async repair(
    id: number,
    fidelity: number,
    tuningId?: string | null,
  ): Promise<RepairResponse> {
    const res = await http.post(`/projects/${id}/repair`, {
      midi_fidelity: fidelity,
      tuning_id: tuningId ?? null,
    });
    return unwrap(res.data) as RepairResponse;
  },

  async report(id: number): Promise<RepairReport> {
    const res = await http.get(`/projects/${id}/report`);
    return unwrap(res.data) as RepairReport;
  },
};

// ─── Tunings API ───

export const tuningsApi = {
  async list(): Promise<TuningInfo[]> {
    const res = await http.get("/tunings");
    return (unwrap(res.data) as { items: TuningInfo[] }).items;
  },
};

// ─── Exports API ───

export const exportsApi = {
  async export(id: number, format: string): Promise<ExportResponse> {
    const res = await http.post(`/projects/${id}/export`, { format });
    return unwrap(res.data) as ExportResponse;
  },

  async list(id: number): Promise<{ items: ExportRecord[] }> {
    const res = await http.get(`/projects/${id}/exports`);
    return unwrap(res.data) as { items: ExportRecord[] };
  },

  async download(
    id: number,
    exportId: number,
    fallbackFilename = "download",
  ): Promise<{ blob: Blob; filename: string }> {
    const res = await http.get(`/projects/${id}/exports/${exportId}/download`, {
      responseType: "blob",
    });
    // Prefer the filename from Content-Disposition. The backend FileResponse
    // sets `attachment; filename="output.gp5"` / `"output_ample.mid"`, but the
    // header may be hidden by CORS if it is not exposed — fall back to the
    // caller-provided name in that case.
    const disposition = res.headers["content-disposition"] as
      | string
      | undefined;
    let filename = fallbackFilename;
    if (disposition) {
      const match = /filename\*?=(?:UTF-8'')?"?([^";]+)"?/i.exec(disposition);
      if (match && match[1]) {
        try {
          filename = decodeURIComponent(match[1]);
        } catch {
          filename = match[1];
        }
      }
    }
    return { blob: res.data as Blob, filename };
  },

  /**
   * Convenience wrapper: trigger an export, then fetch and download the
   * resulting blob in a single call.
   *
   * Chain: export(id, format) → list(id) to find the newest record →
   * download(id, exportId) → return { blob, filename }.
   */
  async exportAndDownload(
    id: number,
    format: string,
  ): Promise<{ blob: Blob; filename: string }> {
    await this.export(id, format);
    const list = await this.list(id);
    // The backend orders records by created_at DESC, so the newest export
    // (the one we just created) is at index 0 — not the last item.
    const items = list.items;
    const latest = items.length > 0 ? items[0] : null;
    if (!latest) {
      throw new Error("Export was created but no export record was found.");
    }
    const fallbackFilename =
      format === "gp5" ? "output.gp5" : "output_ample.mid";
    return this.download(id, latest.id, fallbackFilename);
  },
};

// ─── E-Learning API ───

export const elearningApi = {
  async learn(
    files: File[],
    style?: string,
    promote = true,
  ): Promise<LearnResponse> {
    const form = new FormData();
    for (const f of files) form.append("files", f);
    if (style) form.append("style", style);
    form.append("promote", String(promote));
    // Learning can take a while for large archives.
    const res = await http.post("/elearning/learn", form, {
      headers: { "Content-Type": "multipart/form-data" },
      timeout: 600_000,
    });
    return unwrap(res.data) as LearnResponse;
  },

  async versions(): Promise<VersionsResponse> {
    const res = await http.get("/elearning/versions");
    return unwrap(res.data) as VersionsResponse;
  },

  async rollback(version: string): Promise<{ active_version: string }> {
    const res = await http.post("/elearning/rollback", { version });
    return unwrap(res.data) as { active_version: string };
  },

  async diff(a: string, b: string): Promise<VersionDiff> {
    const res = await http.get("/elearning/diff", { params: { a, b } });
    return unwrap(res.data) as VersionDiff;
  },
};

export { http };
