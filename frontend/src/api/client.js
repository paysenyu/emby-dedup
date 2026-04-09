const rawBase = import.meta.env.VITE_API_BASE_URL;
const API_BASE_URL = typeof rawBase === "string" ? rawBase.trim().replace(/\/$/, "") : "";
const API_PREFIX = "/api";

function buildUrl(path) {
  const normalized = path.startsWith("/") ? path : `/${path}`;
  const prefixed = normalized.startsWith(`${API_PREFIX}/`) ? normalized : `${API_PREFIX}${normalized}`;
  if (API_BASE_URL) {
    return `${API_BASE_URL}${prefixed}`;
  }
  return prefixed;
}

async function request(path, options = {}) {
  const response = await fetch(buildUrl(path), {
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
    ...options,
  });

  const contentType = response.headers.get("content-type") || "";
  const isJson = contentType.includes("application/json");
  const body = isJson ? await response.json().catch(() => null) : await response.text();

  if (!response.ok) {
    const detail = isJson ? body?.detail || body?.message || JSON.stringify(body || {}) : body;
    throw new Error(detail || `Request failed: ${response.status}`);
  }

  if (response.status === 204) {
    return null;
  }

  return isJson ? body : null;
}

export const api = {
  health: () => request("/health"),
  getDashboardStats: () => request("/dashboard/stats"),
  getSettings: () => request("/settings"),
  putSettings: (payload) => request("/settings", { method: "PUT", body: JSON.stringify(payload) }),
  getLibraries: () => request("/libraries"),
  triggerSync: () => request("/sync", { method: "POST" }),
  getSyncStatus: () => request("/sync/status"),
  getRules: () => request("/rules"),
  putRules: (payload) => request("/rules", { method: "PUT", body: JSON.stringify(payload) }),
  runAnalysis: () => request("/analysis/run", { method: "POST" }),
  getAnalysisGroups: (params = {}) => {
    const query = new URLSearchParams(params).toString();
    return request(`/analysis/groups${query ? `?${query}` : ""}`);
  },
  getAnalysisGroup: (groupId) => request(`/analysis/groups/${encodeURIComponent(groupId)}`),
  overrideAnalysisGroup: (groupId, keepItemId) =>
    request(`/analysis/groups/${encodeURIComponent(groupId)}/override`, {
      method: "PUT",
      body: JSON.stringify({ keep_item_id: keepItemId }),
    }),
  getMetadataIssues: () => request("/metadata/issues"),
  getDeletePreview: (payload) => request("/delete/preview", { method: "POST", body: JSON.stringify(payload) }),
  executeDelete: (payload) => request("/delete/execute", { method: "POST", body: JSON.stringify(payload) }),
  getDeleteQueueStatus: (params = {}) => {
    const sp = new URLSearchParams();
    if (Array.isArray(params.ids)) {
      for (const id of params.ids) {
        if (id != null) sp.append("ids", String(id));
      }
    }
    if (params.limit != null) sp.set("limit", String(params.limit));
    if (params.latest_only != null) sp.set("latest_only", String(Boolean(params.latest_only)));
    const query = sp.toString();
    return request(`/delete/queue/status${query ? `?${query}` : ""}`);
  },
  postDeleteWebhook: (payload, token = "") =>
    request(`/webhook/emby${token ? `?token=${encodeURIComponent(token)}` : ""}`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
};
