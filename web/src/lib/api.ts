import type {
  AssistantStatus,
  DailyInsight,
  Domain,
  DomainResponse,
  HomeResponse,
  NutritionDraft,
  Profile,
  RangeName,
  WeeklyReport,
} from "./types";

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
  ) {
    super(message);
  }
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(path, options);
  if (!response.ok) {
    let message = response.statusText;
    try {
      const body = (await response.json()) as { detail?: string };
      message = body.detail ?? message;
    } catch {
      message = response.statusText;
    }
    throw new ApiError(message, response.status);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export const api = {
  home: (date?: string) => request<HomeResponse>(`/api/home${date ? `?date=${date}` : ""}`),
  homeInsight: (date: string) =>
    request<DailyInsight>(`/api/home/insight?date=${date}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ disclosure_accepted: true }),
    }),
  sync: () => request<Record<string, unknown>>("/api/sync", { method: "POST" }),
  reports: () => request<{ generated_at: string; reports: WeeklyReport[] }>("/api/reports?limit=12"),
  domain: (domain: Domain, range: RangeName) =>
    request<DomainResponse>(`/api/${domain}?range=${range}`),
  profile: () => request<Profile>("/api/profile"),
  updateProfile: (profile: Profile) =>
    request<Profile>("/api/profile", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(profile),
    }),
  uploadMeal: (photo: File, note: string) => {
    const body = new FormData();
    body.append("photo", photo);
    if (note.trim()) body.append("note", note.trim());
    return request<NutritionDraft>("/api/nutrition/uploads", { method: "POST", body });
  },
  analyzeMeal: (id: string) =>
    request<NutritionDraft>(`/api/nutrition/drafts/${id}/analyze`, { method: "POST" }),
  confirmMeal: (draft: NutritionDraft) =>
    request<NutritionDraft>(`/api/nutrition/drafts/${draft.id}/confirm`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ eaten_at: new Date().toISOString(), analysis: draft.analysis }),
    }),
  discardMeal: (id: string) =>
    request<void>(`/api/nutrition/drafts/${id}`, { method: "DELETE" }),
  assistantStatus: () => request<AssistantStatus>("/api/assistant/status"),
  assistantLogin: () =>
    request<{ authUrl?: string; verificationUrl?: string; userCode?: string }>("/api/assistant/login", {
      method: "POST",
    }),
  createAssistantThread: (title?: string) =>
    request<{ id: string }>("/api/assistant/threads", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title, disclosure_accepted: true }),
    }),
  assistantTurn: (threadId: string, text: string) =>
    request<{ turn_id: string }>(`/api/assistant/threads/${threadId}/turns`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    }),
};
