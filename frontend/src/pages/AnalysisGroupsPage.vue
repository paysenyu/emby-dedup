
<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";
import { api } from "../api/client";

const { t } = useI18n();

const loading = ref(false);
const runningAnalysis = ref(false);
const busyCleanup = ref(false);
const busyDelete = ref(false);
const error = ref("");
const message = ref("");

const groups = ref([]);
const expanded = ref({});
const detailLoading = ref({});
const detailsByGroup = ref({});
const selectedRowIds = ref({});
const sizeIndexByItemId = ref({});

const analysisStatus = ref({ last_analysis_at: null, analysis_groups: 0, analysis_error: null });
const metadataIssuesCount = ref(null);

const rulesDrawerOpen = ref(false);
const rulesLoading = ref(false);
const rulesSaving = ref(false);
const rulesError = ref("");
const rulesMessage = ref("");
const rules = ref([]);
const rulesDebounceTimer = ref(null);

const draggedRuleId = ref("");
const showPriorityModal = ref(false);
const editingRuleIndex = ref(-1);
const modalPriority = ref([]);
const draggedPriorityIndex = ref(-1);

const logsModalOpen = ref(false);
const executionLogs = ref([]);
const logsPage = ref(1);
const queueRefreshTimer = ref(null);
const seriesExpanded = ref({});
const EXECUTION_LOGS_STORAGE_KEY = "dedup.execution.logs.v1";
const MAX_STORED_EXECUTION_LOGS = 20;
const LOGS_PAGE_SIZE = 10;

const RULE_LABELS = { subtitle: t("analysis.rules.ruleLabels.subtitle"), runtime: t("analysis.rules.ruleLabels.runtime"), effect: t("analysis.rules.ruleLabels.effect"), resolution: t("analysis.rules.ruleLabels.resolution"), bit_depth: t("analysis.rules.ruleLabels.bit_depth"), bitrate: t("analysis.rules.ruleLabels.bitrate"), codec: t("analysis.rules.ruleLabels.codec"), filesize: t("analysis.rules.ruleLabels.filesize"), date_added: t("analysis.rules.ruleLabels.date_added"), frame_rate: t("analysis.rules.ruleLabels.frame_rate") };
const CATEGORICAL_CHOICES = {
  codec: ["AV1", "HEVC", "H.264", "VP9"],
  resolution: ["4K", "1080p", "720p", "480p"],
  effect: ["DoVi P8", "DoVi P7", "DoVi P5", "DoVi (Other)", "HDR10+", "HDR", "SDR"],
  subtitle: ["Chinese", "None"],
};

const selectedCount = computed(() => Object.values(selectedRowIds.value).filter(Boolean).length);
const selectedKeepCount = computed(() => {
  let c = 0;
  for (const [k, v] of Object.entries(selectedRowIds.value)) {
    if (!v) continue;
    for (const rows of Object.values(detailsByGroup.value)) {
      const row = (rows || []).find((x) => Number(x.itemId) === Number(k));
      if (row && (row.action === "keep_recommended" || row.action === "keep_manual")) c += 1;
    }
  }
  return c;
});
const ruleSummaryText = computed(() => {
  const enabled = [...rules.value].filter((r) => r.enabled).sort((a, b) => a.order - b.order).map((r) => RULE_LABELS[r.id] || r.id);
  if (!enabled.length) return t("analysis.noRules");
  if (enabled.length <= 5) return enabled.join(" > ");
  return `${enabled.slice(0, 5).join(" > ")} ...`;
});
const lastExecutionSummary = computed(() => {
  const rows = executionLogs.value;
  if (!rows.length) return { success: 0, failed: 0, freed: 0 };
  return {
    success: rows.filter((x) => resolveLogStatus(x) === "success").length,
    failed: rows.filter((x) => resolveLogStatus(x) === "failed").length,
    freed: rows.filter((x) => resolveLogStatus(x) === "success").reduce((s, x) => s + (Number(x.freedSize || 0) || 0), 0),
  };
});
const pagedExecutionLogs = computed(() => {
  const start = (Math.max(1, Number(logsPage.value || 1)) - 1) * LOGS_PAGE_SIZE;
  return executionLogs.value.slice(start, start + LOGS_PAGE_SIZE);
});
const logsTotalPages = computed(() => Math.max(1, Math.ceil(executionLogs.value.length / LOGS_PAGE_SIZE)));
const hasRunningLogs = computed(() =>
  executionLogs.value.some((x) => resolveLogStatus(x) === "running")
);
const seriesBuckets = computed(() => {
  const byKey = new Map();
  for (const g of groups.value) {
    const key = `${String(g.mediaKind || "")}|${String(g.title || "")}`;
    const meta = parseEpisodeGroupMeta(g.groupId);
    if (!byKey.has(key)) {
      byKey.set(key, {
        key,
        title: String(g.title || t("analysis.group.unnamed")),
        mediaKind: String(g.mediaKind || ""),
        groups: [],
        itemCount: 0,
        deleteCount: 0,
      });
    }
    const bucket = byKey.get(key);
    bucket.groups.push({
      ...g,
      seasonNumber: meta.seasonNumber,
      episodeNumber: meta.episodeNumber,
      episodeLabel: meta.episodeLabel,
    });
    bucket.itemCount += Number(g.itemCount || 0);
    bucket.deleteCount += Number(g.deleteCount || 0);
  }
  return [...byKey.values()]
    .map((bucket) => ({
      ...bucket,
      groups: [...bucket.groups].sort((a, b) => {
        const s = Number(a.seasonNumber || 0) - Number(b.seasonNumber || 0);
        if (s !== 0) return s;
        const e = Number(a.episodeNumber || 0) - Number(b.episodeNumber || 0);
        if (e !== 0) return e;
        return String(a.groupId || "").localeCompare(String(b.groupId || ""));
      }),
    }))
    .sort((a, b) => String(a.title || "").localeCompare(String(b.title || ""), "zh-Hans-CN"));
});

function normalizeUiStatus(deleteStatus, status, message = "", statusCode = null) {
  const msg = String(message || "").toLowerCase();
  const ds = String(deleteStatus || "").toLowerCase();
  if (ds === "done") return "success";
  if (ds === "failed") return "failed";
  if (ds === "in_progress" || ds === "pending") return "running";
  if (msg.includes("webhook confirmed delete") || msg === "success" || msg.includes("删除确认") || msg.includes("成功")) {
    return "success";
  }
  if (msg.includes("retry limit") || msg.includes("failed") || msg.includes("失败")) return "failed";
  const code = Number(statusCode);
  if (code === 200 || code === 204) {
    if (msg.includes("waiting webhook")) return "running";
  }
  const s = String(status || "").toLowerCase();
  if (s === "success" || s === "failed" || s === "running") return s;
  return "running";
}

function parseEpisodeGroupMeta(groupId) {
  const text = String(groupId || "");
  const match = text.match(/^episode:([^:]+):(\d+):(\d+)$/i);
  if (!match) {
    return {
      tmdbId: "",
      seasonNumber: 0,
      episodeNumber: 0,
      episodeLabel: "-",
    };
  }
  const seasonNumber = Number(match[2] || 0);
  const episodeNumber = Number(match[3] || 0);
  return {
    tmdbId: String(match[1] || ""),
    seasonNumber,
    episodeNumber,
    episodeLabel: `S${String(seasonNumber).padStart(2, "0")}E${String(episodeNumber).padStart(2, "0")}`,
  };
}

function persistExecutionLogs() {
  try {
    localStorage.setItem(EXECUTION_LOGS_STORAGE_KEY, JSON.stringify(executionLogs.value.slice(0, MAX_STORED_EXECUTION_LOGS)));
  } catch {}
}

function parseLogTimestampMs(ts) {
  const raw = String(ts || "").trim();
  if (!raw) return 0;
  const normalized = /^\d{4}-\d{2}-\d{2}T/.test(raw) && !/(Z|[+-]\d{2}:\d{2})$/i.test(raw) ? `${raw}Z` : raw;
  const v = Date.parse(normalized);
  return Number.isFinite(v) ? v : 0;
}

function logStatusRank(status) {
  if (status === "success") return 3;
  if (status === "failed") return 2;
  if (status === "running") return 1;
  return 0;
}

function logIdentityKey(log) {
  const groupId = String(log?.groupId || "");
  const target = String(log?.deleteTargetItemId || log?.embyItemId || "").trim();
  if (target) return `t:${groupId}|${target}`;
  const itemId = Number(log?.itemId || 0);
  const queueId = Number(log?.queueId || 0);
  if (itemId > 0) return `i:${groupId}|${itemId}`;
  if (queueId > 0) return `q:${queueId}`;
  return `f:${groupId}|${parseLogTimestampMs(log?.timestamp)}`;
}

function shouldReplaceLog(prev, next) {
  const prevTs = parseLogTimestampMs(prev?.timestamp);
  const nextTs = parseLogTimestampMs(next?.timestamp);
  if (nextTs !== prevTs) return nextTs > prevTs;
  const prevRank = logStatusRank(resolveLogStatus(prev));
  const nextRank = logStatusRank(resolveLogStatus(next));
  if (nextRank !== prevRank) return nextRank > prevRank;
  return String(next?.message || "").length > String(prev?.message || "").length;
}

function dedupeExecutionLogs(logs) {
  const map = new Map();
  for (const log of Array.isArray(logs) ? logs : []) {
    const key = logIdentityKey(log);
    const prev = map.get(key);
    if (!prev || shouldReplaceLog(prev, log)) {
      map.set(key, log);
    }
  }
  return [...map.values()].sort((a, b) => parseLogTimestampMs(b?.timestamp) - parseLogTimestampMs(a?.timestamp));
}

function setExecutionLogs(nextLogs) {
  executionLogs.value = dedupeExecutionLogs(nextLogs).slice(0, MAX_STORED_EXECUTION_LOGS);
  if (logsPage.value > logsTotalPages.value) logsPage.value = logsTotalPages.value;
  persistExecutionLogs();
}

function hydrateExecutionLogs() {
  try {
    const raw = localStorage.getItem(EXECUTION_LOGS_STORAGE_KEY);
    if (!raw) return;
    const parsed = JSON.parse(raw);
    if (Array.isArray(parsed)) {
      executionLogs.value = dedupeExecutionLogs(parsed).slice(0, MAX_STORED_EXECUTION_LOGS);
    }
  } catch {}
}

function queueRowToExecutionLog(row) {
  const deleteStatus = String(row?.delete_status || row?.deleteStatus || "pending");
  const message = row?.message || "";
  const statusCode = row?.status_code ?? row?.statusCode ?? null;
  const status = normalizeUiStatus(deleteStatus, "", message, statusCode);
  return {
    batchId: Number(row?.created_at ? Date.parse(row.created_at) : Date.now()),
    queueId: Number(row?.id || 0),
    timestamp: row?.updated_at || row?.updatedAt || row?.created_at || row?.createdAt || new Date().toISOString(),
    groupId: row?.group_id || row?.groupId || "",
    itemId: Number(row?.item_id || row?.itemId || 0),
    embyItemId: row?.emby_item_id || row?.embyItemId || "",
    deleteTargetItemId: row?.delete_target_item_id || row?.deleteTargetItemId || "",
    deleteStatus,
    status,
    statusCode,
    message,
    deletedPaths: Array.isArray(row?.deleted_paths) ? row.deleted_paths : (Array.isArray(row?.deletedPaths) ? row.deletedPaths : []),
    freedSize: status === "success" ? Number(sizeIndexByItemId.value[Number(row?.item_id || row?.itemId || 0)] || 0) : 0,
  };
}

async function refreshExecutionLogsFromQueue({ useRecent = false } = {}) {
  const ids = [...new Set(executionLogs.value.map((x) => Number(x.queueId || 0)).filter((x) => x > 0))];
  if (!ids.length && !useRecent) return;
  try {
    const data = await api.getDeleteQueueStatus(ids.length ? { ids } : { limit: MAX_STORED_EXECUTION_LOGS });
    const rows = Array.isArray(data?.items) ? data.items : [];
    if (!rows.length) return;

    if (!ids.length && useRecent) {
      const recentLogs = rows
        .slice()
        .reverse()
        .map((row) => queueRowToExecutionLog(row));
      setExecutionLogs(recentLogs);
      return;
    }

    const rowById = new Map(rows.map((r) => [Number(r?.id || 0), r]));
    const merged = executionLogs.value.map((log) => {
      const queueId = Number(log.queueId || 0);
      const row = rowById.get(queueId);
      if (!row) return log;
      const nextDeleteStatus = String(row?.delete_status || row?.deleteStatus || log.deleteStatus || "pending");
      const nextMessage = row?.message || log.message || "";
      const nextStatusCode = row?.status_code ?? row?.statusCode ?? log.statusCode ?? null;
      const nextStatus = normalizeUiStatus(nextDeleteStatus, log.status, nextMessage, nextStatusCode);
      return {
        ...log,
        deleteStatus: nextDeleteStatus,
        status: nextStatus,
        statusCode: nextStatusCode,
        message: nextMessage,
        deletedPaths: Array.isArray(row?.deleted_paths) ? row.deleted_paths : (Array.isArray(row?.deletedPaths) ? row.deletedPaths : log.deletedPaths),
        timestamp: row?.updated_at || row?.updatedAt || log.timestamp,
        freedSize: nextStatus === "success" ? Number(sizeIndexByItemId.value[Number(log.itemId || 0)] || log.freedSize || 0) : 0,
      };
    });
    setExecutionLogs(merged);
  } catch {}
}

function stopQueueRefreshTimer() {
  if (queueRefreshTimer.value) {
    clearTimeout(queueRefreshTimer.value);
    queueRefreshTimer.value = null;
  }
}

function scheduleQueueRefresh() {
  stopQueueRefreshTimer();
  if (!hasRunningLogs.value) return;
  queueRefreshTimer.value = setTimeout(async () => {
    await refreshExecutionLogsFromQueue();
    scheduleQueueRefresh();
  }, 3000);
}

function prevLogsPage() { logsPage.value = Math.max(1, logsPage.value - 1); }
function nextLogsPage() { logsPage.value = Math.min(logsTotalPages.value, logsPage.value + 1); }
function clearExecutionLogs() {
  executionLogs.value = [];
  logsPage.value = 1;
  persistExecutionLogs();
  stopQueueRefreshTimer();
}
function resolveLogStatus(log) {
  return normalizeUiStatus(log?.deleteStatus, log?.status, log?.message, log?.statusCode);
}

function formatLogGroupId(groupId) {
  const text = String(groupId || "");
  if (!text) return "-";
  const ep = text.match(/^episode:([^:]+):(\d+):(\d+)$/i);
  if (ep) {
    return String(ep[1]);
  }
  return text;
}

function formatLogEpisode(groupId) {
  const text = String(groupId || "");
  const ep = text.match(/^episode:([^:]+):(\d+):(\d+)$/i);
  if (!ep) return "-";
  return `S${String(ep[2]).padStart(2, "0")}E${String(ep[3]).padStart(2, "0")}`;
}

function localizeLogMessage(log) {
  const raw = String(log?.message || "");
  if (!raw) return "-";
  const status = resolveLogStatus(log);
  if (status === "success" && raw.includes("Webhook not received before retry limit")) return "";
  if (raw.includes("Webhook confirmed delete")) return "";
  if (raw.includes("DeleteVersion succeeded")) return "";
  if (raw.includes("Webhook not received before retry limit")) return "超过重试上限仍未收到Webhook回调";
  if (/^success$/i.test(raw.trim())) return "";
  if (/^failed$/i.test(raw.trim())) return "";
  return raw.replace(/\bsuccess\b/gi, "").replace(/\bfailed\b/gi, "").trim();
}

function toLocalTime(ts) {
  if (!ts) return "-";
  const raw = String(ts).trim();
  // Backend timestamps are UTC without timezone suffix.
  // Treat ISO strings without offset as UTC to avoid 8-hour skew.
  const normalized = /^\d{4}-\d{2}-\d{2}T/.test(raw) && !/(Z|[+-]\d{2}:\d{2})$/i.test(raw) ? `${raw}Z` : raw;
  const d = new Date(normalized);
  if (Number.isNaN(d.getTime())) return "-";
  const p = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
}
function formatFileSize(v) { const n = Number(v); if (!Number.isFinite(n) || n <= 0) return "-"; const u = ["B", "KB", "MB", "GB", "TB"]; let i = 0; let x = n; while (x >= 1024 && i < u.length - 1) { x /= 1024; i += 1; } return `${x.toFixed(x >= 10 || i === 0 ? 0 : 1)} ${u[i]}`; }
function formatBitrate(v) { const n = Number(v); if (!Number.isFinite(n) || n <= 0) return "-"; return n >= 1_000_000 ? `${(n / 1_000_000).toFixed(2)} Mbps` : `${(n / 1_000).toFixed(0)} Kbps`; }
function formatBitDepth(v) { const n = Number(v); if (!Number.isFinite(n) || n <= 0) return "-"; return `${n}bit`; }
function formatFrameRate(v) { const n = Number(v); if (!Number.isFinite(n) || n <= 0) return "-"; return `${n.toFixed(3).replace(/0+$/, "").replace(/\.$/, "")} fps`; }
function formatRuntime(v) { const n = Number(v); if (!Number.isFinite(n) || n <= 0) return "-"; const h = Math.floor(n / 3600); const m = Math.floor((n % 3600) / 60); const s = Math.floor(n % 60); return h > 0 ? `${h}h ${m}m ${s}s` : `${m}m ${s}s`; }
function subtitleLabel(meta) { return meta?.has_chinese_subtitle ? t("common.subtitle.chinese") : t("common.subtitle.none"); }
function mediaIcon(kind) { return kind === "movie" ? "🎬" : kind === "episode" ? "📺" : "🎞️"; }
function statusIcon(action) { return action === "keep_recommended" || action === "keep_manual" ? "✅" : action === "delete_candidate" ? "❌" : action === "protected" ? "🔒" : "•"; }
function rowClass(row) { return row.action === "keep_recommended" || row.action === "keep_manual" ? "row-keep" : row.action === "delete_candidate" ? "row-delete" : row.action === "protected" ? "row-protected" : ""; }
function isDeleteCandidate(row) { return row?.action === "delete_candidate"; }
function logStatusEmoji(status) { return status === "success" ? "✅" : status === "failed" ? "❌" : status === "running" ? "⏳" : "•"; }
function logStatusClass(status) { return status === "success" ? "ok" : status === "failed" ? "fail" : "space"; }
function normalizeGroup(raw) { const c = raw?.comparison || {}; return { groupId: raw?.group_id || "", title: raw?.title || t("analysis.group.unnamed"), itemCount: Number(raw?.item_count || 0), tmdbId: c?.tmdb_id || "", mediaKind: raw?.media_kind || "", deleteCount: Array.isArray(raw?.actions?.delete_candidate_item_ids) ? raw.actions.delete_candidate_item_ids.length : 0 }; }
function normalizeDetailRows(detail) { const toRow = (item) => ({ itemId: item?.item_id, embyItemId: item?.emby_item_id || "", deleteTargetItemId: item?.delete_target_item_id || item?.emby_item_id || "", path: item?.path || "", action: item?.action || "", metadata: item?.metadata || {} }); return [...(detail?.keep_item ? [toRow(detail.keep_item)] : []), ...(Array.isArray(detail?.delete_candidates) ? detail.delete_candidates.map(toRow) : []), ...(Array.isArray(detail?.protected_items) ? detail.protected_items.map(toRow) : [])]; }
async function ensureGroupRows(groupId) {
  if (detailsByGroup.value[groupId]) return detailsByGroup.value[groupId];
  detailLoading.value[groupId] = true;
  try {
    const detail = await api.getAnalysisGroup(groupId);
    const rows = normalizeDetailRows(detail);
    detailsByGroup.value[groupId] = rows;
    for (const row of rows) {
      const sz = Number(row?.metadata?.file_size || 0);
      if (row.itemId && sz > 0) sizeIndexByItemId.value[row.itemId] = sz;
      if (row.itemId && row.action === "delete_candidate" && selectedRowIds.value[row.itemId] === undefined) {
        selectedRowIds.value[row.itemId] = true;
      }
      if (row.itemId && !isRowSelectable(row)) {
        selectedRowIds.value[row.itemId] = false;
      }
    }
    return rows;
  } catch (e) {
    error.value = t("analysis.messages.detailsLoadFailed", { groupId, message: e.message });
    return [];
  } finally {
    detailLoading.value[groupId] = false;
  }
}

function isExpanded(groupId) { return !!expanded.value[groupId]; }
async function toggleGroup(groupId) { expanded.value[groupId] = !expanded.value[groupId]; if (expanded.value[groupId]) await ensureGroupRows(groupId); }
function isSeriesExpanded(seriesKey) { return !!seriesExpanded.value[seriesKey]; }
function toggleSeries(seriesKey) { seriesExpanded.value[seriesKey] = !isSeriesExpanded(seriesKey); }
async function ensureSeriesRows(series) {
  for (const group of series?.groups || []) {
    await ensureGroupRows(group.groupId);
  }
}
function isRowChecked(itemId) { return !!selectedRowIds.value[itemId]; }
function isRowSelectable(row) { return row?.action === "delete_candidate"; }
function toggleRowSelection(row, checked) { if (!isRowSelectable(row)) return; selectedRowIds.value[row.itemId] = !!checked; }
function isGroupCheckedSync(groupId) { const rows = (detailsByGroup.value[groupId] || []).filter(isDeleteCandidate); return rows.length > 0 && rows.every((r) => isRowChecked(r.itemId)); }
function isGroupIndeterminateSync(groupId) { const rows = (detailsByGroup.value[groupId] || []).filter(isDeleteCandidate); if (!rows.length) return false; const checked = rows.filter((r) => isRowChecked(r.itemId)).length; return checked > 0 && checked < rows.length; }
async function toggleGroupSelection(group, checked) { const rows = await ensureGroupRows(group.groupId); for (const row of rows) if (isDeleteCandidate(row)) selectedRowIds.value[row.itemId] = !!checked; }
function isSeriesCheckedSync(series) {
  const rows = (series?.groups || []).flatMap((g) => (detailsByGroup.value[g.groupId] || []).filter(isDeleteCandidate));
  return rows.length > 0 && rows.every((r) => isRowChecked(r.itemId));
}
function isSeriesIndeterminateSync(series) {
  const rows = (series?.groups || []).flatMap((g) => (detailsByGroup.value[g.groupId] || []).filter(isDeleteCandidate));
  if (!rows.length) return false;
  const checked = rows.filter((r) => isRowChecked(r.itemId)).length;
  return checked > 0 && checked < rows.length;
}
async function toggleSeriesSelection(series, checked) {
  await ensureSeriesRows(series);
  for (const group of series?.groups || []) {
    const rows = detailsByGroup.value[group.groupId] || [];
    for (const row of rows) {
      if (isDeleteCandidate(row)) selectedRowIds.value[row.itemId] = !!checked;
    }
  }
}
function clearSelection() { selectedRowIds.value = {}; }
function selectedItemIds() { return Object.entries(selectedRowIds.value).filter(([, v]) => !!v).map(([k]) => Number(k)).filter((x) => Number.isInteger(x) && x > 0); }
function selectedKeepWarningText() { return t("analysis.messages.manualKeepWarn", { count: selectedKeepCount.value }); }

async function loadAnalysisStatus() {
  try { const d = await api.getSyncStatus(); analysisStatus.value = { last_analysis_at: d?.last_analysis_at || null, analysis_groups: Number(d?.analysis_groups || 0), analysis_error: d?.analysis_error || null }; } catch {}
}
async function loadGroups() {
  loading.value = true; error.value = "";
  try {
    const d = await api.getAnalysisGroups();
    groups.value = (Array.isArray(d?.items) ? d.items : []).map(normalizeGroup);
    for (const bucket of seriesBuckets.value) {
      if (seriesExpanded.value[bucket.key] === undefined) seriesExpanded.value[bucket.key] = true;
    }
    message.value = t("analysis.messages.groupsLoaded", { count: groups.value.length });
  }
  catch (e) { error.value = t("analysis.messages.groupsLoadFailed", { message: e.message }); }
  finally { loading.value = false; }
}
async function loadMetadataIssuesCount() { try { const d = await api.getMetadataIssues(); metadataIssuesCount.value = Number(d?.total || 0); } catch { metadataIssuesCount.value = null; } }

async function runAnalysis() {
  runningAnalysis.value = true; error.value = "";
  try {
    const r = await api.runAnalysis();
    message.value = t("analysis.messages.scanDone", { groups: r?.groups ?? 0, items: r?.items ?? 0 });
    detailsByGroup.value = {}; clearSelection();
    await Promise.all([loadAnalysisStatus(), loadGroups(), loadMetadataIssuesCount()]);
  } catch (e) { error.value = t("analysis.messages.scanFailed", { message: e.message }); }
  finally { runningAnalysis.value = false; }
}

async function primeSizeIndexForItems(itemIds) {
  const targets = new Set(itemIds.map((x) => Number(x)).filter((x) => x > 0));
  if (!targets.size) return;
  const grpIds = groups.value.map((g) => g.groupId);
  try {
    const preview = await api.getDeletePreview({ group_ids: grpIds });
    for (const g of Array.isArray(preview?.groups) ? preview.groups : []) {
      for (const r of Array.isArray(g?.delete_candidates) ? g.delete_candidates : []) {
        const id = Number(r?.item_id || 0);
        if (targets.has(id)) {
          const size = Number(r?.metadata?.file_size || 0);
          if (size > 0) sizeIndexByItemId.value[id] = size;
        }
      }
    }
  } catch {}
}

async function executeDelete(payload, label) {
  const ids = Array.isArray(payload?.item_ids) ? payload.item_ids : [];
  if (ids.length) await primeSizeIndexForItems(ids);

  const d = await api.executeDelete(payload);
  const batchId = Date.now();
  const now = new Date().toISOString();
  const rows = (Array.isArray(d?.results) ? d.results : []).map((r) => {
    const itemId = Number(r?.item_id || 0);
    const deleteStatus = String(r?.delete_status || "pending");
    const statusCode = r?.status_code ?? null;
    const rawMessage = r?.message || "";
    const uiStatus = normalizeUiStatus(deleteStatus, r?.status || "", rawMessage, statusCode);
    return {
      batchId,
      queueId: Number(r?.id || 0),
      timestamp: now,
      groupId: r?.group_id || "",
      itemId,
      embyItemId: r?.emby_item_id || "",
      deleteTargetItemId: r?.delete_target_item_id || r?.emby_item_id || "",
      deleteStatus,
      status: uiStatus,
      statusCode,
      message: rawMessage,
      deletedPaths: Array.isArray(r?.deleted_paths) ? r.deleted_paths : [],
      freedSize: uiStatus === "success" ? Number(sizeIndexByItemId.value[itemId] || 0) : 0,
    };
  });

  setExecutionLogs([...rows, ...executionLogs.value]);
  logsPage.value = 1;
  scheduleQueueRefresh();
  logsModalOpen.value = true;
  message.value = t("analysis.messages.deleteResult", { label, success: d?.success_count || 0, failed: d?.failed_count || 0 });

  const deleted = new Set(rows.filter((x) => x.status === "success").map((x) => x.itemId));
  if (deleted.size) {
    const next = { ...selectedRowIds.value };
    for (const id of deleted) delete next[id];
    selectedRowIds.value = next;
  }

  detailsByGroup.value = {};
  await Promise.all([loadGroups(), loadAnalysisStatus(), loadMetadataIssuesCount()]);
}

async function oneClickCleanup() {
  if (busyCleanup.value) return;
  busyCleanup.value = true; error.value = "";
  try { const ids = selectedItemIds(); if (ids.length) await executeDelete({ item_ids: ids }, t("analysis.top.oneClickCleanup")); else await executeDelete({}, t("analysis.top.oneClickCleanup")); }
  catch (e) { error.value = t("analysis.messages.cleanupFailed", { message: e.message }); }
  finally { busyCleanup.value = false; }
}

async function executeSelectedDelete() {
  if (busyDelete.value) return;
  const ids = selectedItemIds();
  if (!ids.length) { error.value = t("analysis.messages.needPick"); return; }
  busyDelete.value = true; error.value = "";
  try { await executeDelete({ item_ids: ids }, t("analysis.top.executeDelete")); }
  catch (e) { error.value = t("analysis.messages.deleteFailed", { message: e.message }); }
  finally { busyDelete.value = false; }
}
function isCategoricalRule(rule) { return Array.isArray(CATEGORICAL_CHOICES[rule.id]); }
function normalizeRule(rule, index) {
  const n = { id: rule.id, enabled: !!rule.enabled, order: Number(rule.order || index + 1), priority: rule.priority };
  if (isCategoricalRule(n)) {
    const choices = CATEGORICAL_CHOICES[n.id];
    const incoming = Array.isArray(rule.priority) ? rule.priority : [];
    const ordered = [];
    for (const v of incoming) if (choices.includes(v) && !ordered.includes(v)) ordered.push(v);
    for (const c of choices) if (!ordered.includes(c)) ordered.push(c);
    n.priority = ordered;
  }
  return n;
}
function resetRuleOrders() { rules.value.forEach((r, i) => { r.order = i + 1; }); }
function scheduleAnalysisRerun() { if (rulesDebounceTimer.value) clearTimeout(rulesDebounceTimer.value); rulesDebounceTimer.value = setTimeout(() => runAnalysis(), 700); }
function openRulesDrawer() { rulesDrawerOpen.value = true; if (!rules.value.length) loadRules(); }

async function loadRules() {
  rulesLoading.value = true; rulesError.value = "";
  try { const d = await api.getRules(); rules.value = (Array.isArray(d?.rules) ? d.rules : []).map(normalizeRule).sort((a, b) => a.order - b.order); resetRuleOrders(); }
  catch (e) { rulesError.value = t("analysis.rules.loadFailed", { message: e.message }); }
  finally { rulesLoading.value = false; }
}

async function saveRules() {
  rulesSaving.value = true; rulesError.value = ""; rulesMessage.value = "";
  try {
    resetRuleOrders();
    await api.putRules({ rules: rules.value.map((r) => ({ id: r.id, enabled: !!r.enabled, order: r.order, priority: r.priority })) });
    rulesMessage.value = t("analysis.rules.savedRerun");
    scheduleAnalysisRerun();
  } catch (e) { rulesError.value = t("analysis.rules.saveFailed", { message: e.message }); }
  finally { rulesSaving.value = false; }
}

function onRuleDragStart(event, id) {
  const el = event.target;
  if (el.closest("button") || el.closest("input") || el.closest("label")) {
    event.preventDefault();
    return;
  }
  draggedRuleId.value = id;
}
function onRuleDrop(targetId) {
  if (!draggedRuleId.value || draggedRuleId.value === targetId) { draggedRuleId.value = ""; return; }
  const from = rules.value.findIndex((r) => r.id === draggedRuleId.value);
  const to = rules.value.findIndex((r) => r.id === targetId);
  if (from < 0 || to < 0) { draggedRuleId.value = ""; return; }
  const [moved] = rules.value.splice(from, 1); rules.value.splice(to, 0, moved); resetRuleOrders(); draggedRuleId.value = "";
}

function openPriorityModal(index) { const rule = rules.value[index]; if (!rule || !isCategoricalRule(rule)) return; editingRuleIndex.value = index; modalPriority.value = [...rule.priority]; showPriorityModal.value = true; }
function closePriorityModal() { showPriorityModal.value = false; editingRuleIndex.value = -1; modalPriority.value = []; }
function onPriorityDragStart(index) { draggedPriorityIndex.value = index; }
function onPriorityDrop(targetIndex) { const from = draggedPriorityIndex.value; if (from < 0 || from === targetIndex) { draggedPriorityIndex.value = -1; return; } const [moved] = modalPriority.value.splice(from, 1); modalPriority.value.splice(targetIndex, 0, moved); draggedPriorityIndex.value = -1; }
function savePriorityModal() { if (editingRuleIndex.value < 0) return; rules.value[editingRuleIndex.value].priority = [...modalPriority.value]; closePriorityModal(); }
function ruleLabel(ruleId) { return RULE_LABELS[ruleId] || ruleId; }
async function openLogsModal() {
  logsModalOpen.value = true;
  await refreshExecutionLogsFromQueue({ useRecent: executionLogs.value.length === 0 });
  scheduleQueueRefresh();
}
async function closeLogsModal() {
  logsModalOpen.value = false;
  await Promise.all([loadGroups(), loadAnalysisStatus(), loadMetadataIssuesCount()]);
}

onMounted(async () => {
  hydrateExecutionLogs();
  await Promise.all([loadAnalysisStatus(), loadGroups(), loadRules(), loadMetadataIssuesCount()]);
  await refreshExecutionLogsFromQueue({ useRecent: executionLogs.value.length === 0 });
  scheduleQueueRefresh();
});
onBeforeUnmount(() => {
  stopQueueRefreshTimer();
});
</script>

<template>
  <section class="workspace">
    <header class="workspace-header">
      <div>
        <h2>{{ t("analysis.title") }}</h2>
        <p class="muted">{{ t("analysis.ruleSummaryPrefix") }}：{{ ruleSummaryText }}</p>
      </div>
      <div class="top-actions">
        <span class="batch-pill">{{ t("analysis.top.selectedCount", { count: selectedCount }) }}</span>
        <button type="button" @click="oneClickCleanup" :disabled="busyCleanup">{{ busyCleanup ? t("analysis.top.cleaning") : t("analysis.top.oneClickCleanup") }}</button>
        <button type="button" @click="openRulesDrawer">{{ t("analysis.top.rulesSettings") }}</button>
        <button type="button" @click="runAnalysis" :disabled="runningAnalysis">{{ runningAnalysis ? t("analysis.top.scanning") : t("analysis.top.scanDuplicates") }}</button>
        <button type="button" class="danger" @click="executeSelectedDelete" :disabled="busyDelete">{{ busyDelete ? t("analysis.top.deleting") : t("analysis.top.executeDelete") }}</button>
        <button type="button" @click="openLogsModal">{{ t("analysis.top.viewLogs") }}</button>
      </div>
    </header>

    <article class="status-line">
      <span>{{ t("analysis.statusBar.groups", { count: groups.length }) }}</span>
      <span>{{ t("analysis.statusBar.lastAnalysis", { time: toLocalTime(analysisStatus.last_analysis_at) }) }}</span>
      <span>{{ t("analysis.statusBar.lastGroupCount", { count: analysisStatus.analysis_groups }) }}</span>
      <span v-if="metadataIssuesCount != null">{{ t("analysis.statusBar.metadataIssues", { count: metadataIssuesCount }) }}</span>
      <button type="button" class="text-btn" @click="clearSelection">{{ t("analysis.statusBar.resetSelection") }}</button>
      <button type="button" class="text-btn" @click="loadGroups" :disabled="loading">{{ t("analysis.statusBar.reload") }}</button>
    </article>

    <p v-if="selectedKeepCount > 0" class="warn">{{ selectedKeepWarningText() }}</p>
    <p v-if="message" class="message">{{ message }}</p>
    <p v-if="error" class="error">{{ error }}</p>
    <p v-if="analysisStatus.analysis_error" class="error">{{ analysisStatus.analysis_error }}</p>

    <p v-if="loading">{{ t("analysis.messages.loadingGroups") }}</p>

    <section v-else class="groups-list">
      <article v-for="series in seriesBuckets" :key="series.key" class="group-card series-card">
        <header class="group-header">
          <button class="expand-btn" type="button" @click="toggleSeries(series.key)">{{ isSeriesExpanded(series.key) ? "▾" : "▸" }}</button>
          <input type="checkbox" :checked="isSeriesCheckedSync(series)" :class="{ indeterminate: isSeriesIndeterminateSync(series) }" @change="toggleSeriesSelection(series, $event.target.checked)" />
          <span class="media-icon">{{ mediaIcon(series.mediaKind) }}</span>
          <div class="group-main">
            <div class="group-title-row">
              <strong class="group-title">{{ series.title }}</strong>
              <span class="group-chip">{{ t("analysis.group.itemCount", { count: series.itemCount }) }}</span>
              <span class="group-chip">{{ series.groups.length }} 集</span>
            </div>
          </div>
        </header>

        <section v-if="isSeriesExpanded(series.key)" class="group-body series-body">
          <article v-for="group in series.groups" :key="group.groupId" class="episode-card">
            <header class="group-header episode-header">
              <button class="expand-btn" type="button" @click="toggleGroup(group.groupId)">{{ isExpanded(group.groupId) ? "▾" : "▸" }}</button>
              <input type="checkbox" :checked="isGroupCheckedSync(group.groupId)" :class="{ indeterminate: isGroupIndeterminateSync(group.groupId) }" @change="toggleGroupSelection(group, $event.target.checked)" />
              <span class="media-icon">{{ mediaIcon(group.mediaKind) }}</span>
              <div class="group-main">
                <div class="group-title-row">
                  <strong class="group-title">{{ group.episodeLabel }}</strong>
                  <span class="group-chip">{{ t("analysis.group.itemCount", { count: group.itemCount }) }}</span>
                  <span class="group-chip">TMDb: {{ group.tmdbId || "-" }}</span>
                </div>
              </div>
            </header>

            <section v-if="isExpanded(group.groupId)" class="group-body">
              <p v-if="detailLoading[group.groupId]" class="muted">{{ t("analysis.messages.loadingDetails") }}</p>
              <div v-else class="table-wrap">
                <table class="compare-table">
                  <thead>
                    <tr>
                      <th>{{ t("analysis.table.pick") }}</th><th>{{ t("analysis.table.status") }}</th><th>{{ t("analysis.table.id") }}</th><th>{{ t("analysis.table.resolution") }}</th><th>{{ t("analysis.table.effect") }}</th><th>{{ t("analysis.table.codec") }}</th><th>{{ t("analysis.table.subtitle") }}</th><th>{{ t("analysis.table.bitrate") }}</th><th>{{ t("analysis.table.bitDepth") }}</th><th>{{ t("analysis.table.frameRate") }}</th><th>{{ t("analysis.table.runtime") }}</th><th>{{ t("analysis.table.fileSize") }}</th><th>{{ t("analysis.table.path") }}</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="row in detailsByGroup[group.groupId] || []" :key="`${group.groupId}-${row.itemId}`" :class="rowClass(row)">
                      <td class="pick-cell"><input type="checkbox" :checked="isRowChecked(row.itemId)" :disabled="!isRowSelectable(row)" @change="toggleRowSelection(row, $event.target.checked)" /></td>
                      <td><span class="status-icon">{{ statusIcon(row.action) }}</span><span v-if="row.action === 'keep_manual'" class="mini-badge">{{ t("analysis.statusBadge.manual") }}</span></td>
                      <td>{{ row.deleteTargetItemId || row.embyItemId || "-" }}</td>
                      <td><span class="field-tag tag-resolution">{{ row.metadata.resolution_label || "-" }}</span></td>
                      <td><span class="field-tag tag-effect">{{ row.metadata.effect_label || "-" }}</span></td>
                      <td><span class="field-tag tag-codec">{{ row.metadata.codec_label || row.metadata.video_codec || "-" }}</span></td>
                      <td><span class="field-tag tag-subtitle">{{ subtitleLabel(row.metadata) }}</span></td>
                      <td><span class="field-tag tag-bitrate">{{ formatBitrate(row.metadata.bitrate) }}</span></td>
                      <td><span class="field-tag tag-depth">{{ formatBitDepth(row.metadata.bit_depth) }}</span></td>
                      <td><span class="field-tag tag-fps">{{ formatFrameRate(row.metadata.frame_rate) }}</span></td>
                      <td><span class="field-tag tag-runtime">{{ formatRuntime(row.metadata.runtime_seconds) }}</span></td>
                      <td><span class="field-tag tag-size">{{ formatFileSize(row.metadata.file_size) }}</span></td>
                      <td><span class="path-text" :title="row.path || '-'">{{ row.path || "-" }}</span></td>
                    </tr>
                    <tr v-if="(detailsByGroup[group.groupId] || []).length === 0"><td colspan="13" class="muted">{{ t("analysis.messages.loadedRowsEmpty") }}</td></tr>
                  </tbody>
                </table>
              </div>
            </section>
          </article>
        </section>
      </article>
      <p v-if="seriesBuckets.length === 0" class="muted">{{ t("analysis.messages.noGroups") }}</p>
    </section>

    <div v-if="rulesDrawerOpen" class="drawer-backdrop" @click.self="rulesDrawerOpen = false">
      <aside class="rules-drawer">
        <header class="drawer-header"><h3>{{ t("analysis.rules.drawerTitle") }}</h3><button type="button" @click="rulesDrawerOpen = false">{{ t("common.close") }}</button></header>
        <div class="drawer-actions">
          <button type="button" @click="loadRules" :disabled="rulesLoading">{{ rulesLoading ? t("common.loading") : t("common.reload") }}</button>
          <button type="button" @click="saveRules" :disabled="rulesSaving || rulesLoading">{{ rulesSaving ? t("analysis.rules.saving") : t("analysis.rules.saveRules") }}</button>
        </div>
        <p v-if="rulesMessage" class="message">{{ rulesMessage }}</p>
        <p v-if="rulesError" class="error">{{ rulesError }}</p>

        <div class="rules-list">
          <article v-for="rule in rules" :key="rule.id" class="rule-card" draggable="true" @dragstart="onRuleDragStart($event, rule.id)" @dragover.prevent @drop="onRuleDrop(rule.id)">
            <div class="rule-head"><span class="drag">⋮⋮</span><strong>{{ rule.order }}. {{ ruleLabel(rule.id) }}</strong></div>
            <label class="switch"><input v-model="rule.enabled" type="checkbox" /><span>{{ t("analysis.rules.enable") }}</span></label>
            <button v-if="isCategoricalRule(rule)" type="button" @click="openPriorityModal(rules.findIndex((x) => x.id === rule.id))" class="icon-btn" :title="t('analysis.rules.editPriority')" draggable="false" @dragstart.stop>⚙</button>
            <p v-else class="muted">{{ t("analysis.rules.priority", { value: rule.priority }) }}</p>
            <div v-if="isCategoricalRule(rule)" class="chips"><span v-for="tag in rule.priority" :key="`${rule.id}-${tag}`" class="chip">{{ tag }}</span></div>
          </article>
        </div>
      </aside>
    </div>

    <div v-if="showPriorityModal" class="modal-backdrop" @click.self="closePriorityModal">
      <section class="modal small">
        <h3>{{ t("analysis.rules.priorityModalTitle") }}</h3>
        <p class="muted">{{ t("analysis.rules.priorityModalDesc") }}</p>
        <ul class="priority-list">
          <li v-for="(item, index) in modalPriority" :key="item" class="priority-item" draggable="true" @dragstart="onPriorityDragStart(index)" @dragover.prevent @drop="onPriorityDrop(index)"><span class="drag">⋮⋮</span><span>{{ item }}</span></li>
        </ul>
        <div class="modal-actions"><button type="button" @click="closePriorityModal">{{ t("common.cancel") }}</button><button type="button" @click="savePriorityModal">{{ t("common.save") }}</button></div>
      </section>
    </div>

    <div v-if="logsModalOpen" class="modal-backdrop" @click.self="closeLogsModal">
      <section class="modal">
        <header class="modal-head"><h3>{{ t("analysis.logs.title") }}</h3><button type="button" @click="closeLogsModal">{{ t("common.close") }}</button></header>
        <article class="log-summary"><span class="ok">{{ t("analysis.logs.success", { count: lastExecutionSummary.success }) }}</span><span class="fail">{{ t("analysis.logs.failed", { count: lastExecutionSummary.failed }) }}</span><span class="space">{{ t("analysis.logs.freed", { size: formatFileSize(lastExecutionSummary.freed) }) }}</span></article>
        <article class="log-meta">
          <span>{{ t("analysis.logs.recentLimit", { count: MAX_STORED_EXECUTION_LOGS }) }}</span>
          <button type="button" class="clear-logs-btn" @click="clearExecutionLogs" :disabled="executionLogs.length === 0">{{ t("analysis.logs.clear") }}</button>
        </article>
        <table class="log-table"><thead><tr><th>{{ t("analysis.logs.time") }}</th><th>{{ t("analysis.logs.tmdb") }}</th><th>{{ t("analysis.logs.episode") }}</th><th>{{ t("analysis.logs.status") }}</th><th>{{ t("analysis.logs.code") }}</th><th>{{ t("analysis.logs.message") }}</th></tr></thead>
          <tbody>
            <tr v-if="executionLogs.length === 0"><td colspan="6" class="muted">{{ t("analysis.logs.empty") }}</td></tr>
            <tr v-for="(log, idx) in pagedExecutionLogs" :key="`log-${log.queueId || 'na'}-${log.itemId || 'na'}-${log.timestamp || idx}`">
              <td>{{ toLocalTime(log.timestamp) }}</td>
              <td :title="log.groupId">{{ formatLogGroupId(log.groupId) }}</td>
              <td :title="log.groupId">{{ formatLogEpisode(log.groupId) }}</td>
              <td :class="logStatusClass(resolveLogStatus(log))">{{ logStatusEmoji(resolveLogStatus(log)) }}</td>
              <td>{{ log.statusCode ?? '-' }}</td>
              <td>
                <div v-if="localizeLogMessage(log)" class="log-message-text">{{ localizeLogMessage(log) }}</div>
                <div v-if="Array.isArray(log.deletedPaths) && log.deletedPaths.length" class="deleted-paths">
                  <div v-for="path in log.deletedPaths" :key="`${log.itemId}-${path}`" class="deleted-path-line" :title="path">{{ path }}</div>
                </div>
              </td>
            </tr>
          </tbody></table>
        <footer v-if="executionLogs.length > LOGS_PAGE_SIZE" class="log-pager">
          <button type="button" @click="prevLogsPage" :disabled="logsPage <= 1">{{ t("analysis.logs.prevPage") }}</button>
          <span>{{ t("analysis.logs.page", { current: logsPage, total: logsTotalPages }) }}</span>
          <button type="button" @click="nextLogsPage" :disabled="logsPage >= logsTotalPages">{{ t("analysis.logs.nextPage") }}</button>
        </footer>
      </section>
    </div>
  </section>
</template>
<style scoped>
.workspace { display: flex; flex-direction: column; gap: 12px; }
.workspace-header { display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; }
.top-actions { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
.batch-pill { background: #e2e8f0; color: #334155; border-radius: 999px; padding: 4px 10px; font-size: 12px; }
.status-line { display: flex; gap: 10px; flex-wrap: wrap; align-items: center; color: #334155; }
.text-btn { border: none; background: transparent; color: #1d4ed8; padding: 0; }
button, input { font: inherit; }
button { border: 1px solid #334155; background: #334155; color: #fff; border-radius: 8px; padding: 8px 12px; cursor: pointer; }
button:disabled { opacity: 0.6; cursor: not-allowed; }
button.danger { border-color: #b91c1c; background: #b91c1c; }
.groups-list { display: flex; flex-direction: column; gap: 8px; }
.group-card { background: #fff; border: 1px solid #cbd5e1; border-radius: 10px; }
.series-card { border-color: #bfdbfe; }
.group-header { display: grid; grid-template-columns: 26px 22px 24px 1fr; align-items: center; gap: 8px; padding: 8px 10px; }
.series-body { display: flex; flex-direction: column; gap: 8px; }
.episode-card { border: 1px solid #dbeafe; border-radius: 10px; background: #f8fbff; }
.episode-header { background: #f8fbff; border-radius: 10px 10px 0 0; }
.expand-btn { width: 24px; height: 24px; border-radius: 4px; padding: 0; line-height: 1; background: #f1f5f9; color: #0f172a; border: 1px solid #cbd5e1; }
.media-icon { font-size: 16px; }
.group-title-row { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.group-title { font-size: 14px; }
.group-chip { border: 1px solid #cbd5e1; border-radius: 999px; padding: 2px 8px; font-size: 12px; color: #475569; }
.group-body { border-top: 1px solid #e2e8f0; padding: 8px 10px 10px; }
.table-wrap { overflow: auto; }
.compare-table { width: 100%; border-collapse: collapse; }
.compare-table th, .compare-table td { border-bottom: 1px solid #e2e8f0; padding: 8px; text-align: left; white-space: nowrap; }
.pick-cell { width: 48px; }
.status-icon { font-size: 16px; }
.mini-badge { margin-left: 4px; font-size: 10px; border: 1px solid #16a34a; color: #166534; background: #dcfce7; border-radius: 999px; padding: 1px 6px; }
.row-keep { background: #f0fdf4; }
.row-delete { background: #fff7ed; }
.row-protected { background: #fffbeb; }
.field-tag { border-radius: 999px; padding: 2px 8px; font-size: 12px; display: inline-block; }
.tag-resolution { background: #e0f2fe; color: #075985; }
.tag-effect { background: #ede9fe; color: #5b21b6; }
.tag-codec { background: #ecfccb; color: #365314; }
.tag-subtitle { background: #fef3c7; color: #92400e; }
.tag-bitrate { background: #fee2e2; color: #991b1b; }
.tag-depth { background: #cffafe; color: #155e75; }
.tag-fps { background: #fce7f3; color: #9d174d; }
.tag-runtime { background: #e2e8f0; color: #334155; }
.tag-size { background: #dcfce7; color: #166534; }
.path-text { max-width: 320px; display: inline-block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; vertical-align: bottom; }
.drawer-backdrop, .modal-backdrop { position: fixed; inset: 0; background: rgba(15, 23, 42, 0.45); display: flex; z-index: 40; }
.drawer-backdrop { justify-content: flex-end; }
.rules-drawer { width: min(460px, 95vw); height: 100%; background: #fff; border-left: 1px solid #cbd5e1; padding: 14px; display: flex; flex-direction: column; gap: 10px; }
.drawer-header, .modal-head { display: flex; justify-content: space-between; align-items: center; }
.drawer-actions { display: flex; gap: 8px; }
.rules-list { display: flex; flex-direction: column; gap: 8px; overflow: auto; }
.rule-card { border: 1px solid #cbd5e1; border-radius: 8px; padding: 10px; display: flex; flex-direction: column; gap: 6px; }
.rule-head { display: flex; gap: 8px; align-items: center; }
.drag { color: #64748b; cursor: grab; }
.switch { display: inline-flex; align-items: center; gap: 6px; }
.icon-btn { width: 30px; height: 30px; padding: 0; border-radius: 999px; display: inline-flex; align-items: center; justify-content: center; }
.chips { display: flex; gap: 6px; flex-wrap: wrap; }
.chip { border-radius: 999px; border: 1px solid #bfdbfe; background: #eff6ff; padding: 2px 8px; font-size: 12px; }
.modal { margin: auto; width: min(960px, 96vw); max-height: 92vh; overflow: auto; background: #fff; border: 1px solid #cbd5e1; border-radius: 12px; padding: 14px; display: flex; flex-direction: column; gap: 10px; }
.modal.small { width: min(500px, 95vw); }
.priority-list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 6px; }
.priority-item { border: 1px solid #cbd5e1; border-radius: 8px; padding: 8px; display: flex; gap: 8px; align-items: center; }
.modal-actions { display: flex; justify-content: flex-end; gap: 8px; }
.log-summary { display: flex; gap: 12px; flex-wrap: wrap; }
.log-meta { font-size: 12px; color: #64748b; display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.clear-logs-btn { border: 1px solid #cbd5e1; background: #f8fafc; color: #334155; padding: 4px 8px; border-radius: 6px; }
.log-table { width: 100%; border-collapse: collapse; table-layout: fixed; }
.log-table th, .log-table td { border-bottom: 1px solid #e2e8f0; padding: 8px; text-align: left; vertical-align: top; white-space: nowrap; }
.log-table th:nth-child(1), .log-table td:nth-child(1) { width: 170px; }
.log-table th:nth-child(2), .log-table td:nth-child(2) { width: 90px; }
.log-table th:nth-child(3), .log-table td:nth-child(3) { width: 90px; }
.log-table th:nth-child(4), .log-table td:nth-child(4) { width: 70px; }
.log-table th:nth-child(5), .log-table td:nth-child(5) { width: 70px; }
.log-table th:nth-child(6), .log-table td:nth-child(6) { width: auto; }
.log-pager { display: flex; align-items: center; justify-content: flex-end; gap: 10px; }
.log-message-text { color: #334155; overflow: hidden; text-overflow: ellipsis; }
.deleted-paths { margin-top: 4px; display: flex; flex-direction: column; gap: 2px; }
.deleted-path-line { line-height: 1.35; color: #334155; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.warn { color: #92400e; background: #fffbeb; border: 1px solid #f59e0b; border-radius: 8px; padding: 8px 10px; }
.message { color: #166534; }
.error, .fail { color: #b91c1c; }
.ok { color: #166534; }
.space, .muted { color: #64748b; }
@media (max-width: 980px) { .workspace-header { flex-direction: column; align-items: stretch; } .top-actions { justify-content: flex-start; } }
</style>











