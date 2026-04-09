<script setup>
import { computed, onMounted, onUnmounted, reactive, ref } from "vue";
import { useI18n } from "vue-i18n";

import { api } from "../api/client";

const { t } = useI18n();

const loadingSettings = ref(false);
const savingSettings = ref(false);
const loadingLibraries = ref(false);
const autoLoadingLibraries = ref(false);
const triggeringSync = ref(false);
const loadingSyncStatus = ref(false);
const syncPollingTimer = ref(null);
const message = ref("");
const error = ref("");

const form = reactive({
  embyBaseUrl: "",
  embyApiKey: "",
  embyUserId: "",
  webhookToken: "",
  selectedLibraries: [],
  excludedPathsText: "",
});

const availableLibraries = ref([]);
const syncStatus = reactive({
  state: "idle",
  last_started_at: null,
  last_finished_at: null,
  items_synced: 0,
  current_step: null,
  current_library: null,
  libraries_total: 0,
  libraries_completed: 0,
  items_discovered: 0,
  detail_requests_total: 0,
  detail_requests_completed: 0,
  current_page: 0,
  current_page_size: 0,
  current_library_total_items: 0,
  phase_started_at: null,
  timings: {},
  failed_items: 0,
  duration_seconds: null,
  last_result: null,
  last_analysis_at: null,
  analysis_groups: 0,
  analysis_error: null,
  error: null,
});

const excludedPaths = computed(() =>
  form.excludedPathsText
    .split(/\r?\n/)
    .map((x) => x.trim())
    .filter((x) => x.length > 0),
);

const isSyncRunning = computed(() => syncStatus.state === "running");
const syncProgressPercent = computed(() => {
  if (!isSyncRunning.value) return syncStatus.last_result === "success" ? 100 : 0;
  const step = String(syncStatus.current_step || "").trim().toLowerCase();
  if (step === "discover_libraries") return 8;
  if (step === "list_library_items") {
    const totalLibraries = Number(syncStatus.libraries_total || 0);
    const completedLibraries = Number(syncStatus.libraries_completed || 0);
    const libraryRatio = totalLibraries > 0 ? completedLibraries / totalLibraries : 0;
    return Math.min(45, Math.max(12, Math.round(12 + libraryRatio * 30)));
  }
  if (step === "normalize_items") {
    const total = Number(syncStatus.detail_requests_total || 0);
    const completed = Number(syncStatus.detail_requests_completed || 0);
    if (total > 0) {
      return Math.min(82, Math.max(48, Math.round(48 + (completed / total) * 34)));
    }
    return 55;
  }
  if (step === "rebuilding_media_items") return 90;
  if (step === "running_analysis") return 96;
  return 10;
});

function stateLabel(value) {
  const key = String(value || "").trim().toLowerCase();
  return t(`common.status.${key}`) === `common.status.${key}` ? (value || t("common.unknown")) : t(`common.status.${key}`);
}

function stepLabel(value) {
  const key = String(value || "").trim().toLowerCase();
  return t(`common.step.${key}`) === `common.step.${key}` ? (value || t("common.unknown")) : t(`common.step.${key}`);
}

function hasEmbyConnectionSettings() {
  return Boolean(form.embyBaseUrl?.trim() && form.embyApiKey?.trim() && form.embyUserId?.trim());
}

function formatUtcToLocal(ts) {
  const raw = String(ts || "").trim();
  if (!raw) return t("common.unknown");
  const normalized = raw.endsWith("Z") ? raw : `${raw}Z`;
  const date = new Date(normalized);
  if (Number.isNaN(date.getTime())) return raw;
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, "0");
  const d = String(date.getDate()).padStart(2, "0");
  const hh = String(date.getHours()).padStart(2, "0");
  const mm = String(date.getMinutes()).padStart(2, "0");
  const ss = String(date.getSeconds()).padStart(2, "0");
  return `${y}-${m}-${d} ${hh}:${mm}:${ss}`;
}

function formatDuration(value) {
  const n = Number(value);
  if (!Number.isFinite(n) || n < 0) return t("common.unknown");
  return `${n.toFixed(1)}s`;
}

function stopSyncPolling() {
  if (syncPollingTimer.value) {
    clearInterval(syncPollingTimer.value);
    syncPollingTimer.value = null;
  }
}

function startSyncPolling() {
  if (syncPollingTimer.value) return;
  syncPollingTimer.value = setInterval(() => {
    fetchSyncStatus({ silent: true, fromPoll: true });
  }, 1800);
}

async function fetchSettings() {
  loadingSettings.value = true;
  error.value = "";
  try {
    const data = await api.getSettings();
    form.embyBaseUrl = data?.emby?.base_url || "";
    form.embyApiKey = data?.emby?.api_key || "";
    form.embyUserId = data?.emby?.user_id || "";
    form.webhookToken = data?.webhook_token || "";
    form.selectedLibraries = Array.isArray(data?.libraries) ? [...data.libraries] : [];
    form.excludedPathsText = Array.isArray(data?.excluded_paths)
  ? data.excluded_paths.join("\n")
  : "";
  } catch (e) {
    error.value = t("settings.messages.loadSettingsFailed", { message: e.message });
  } finally {
    loadingSettings.value = false;
  }
}

async function fetchLibraries(options = {}) {
  const { isAuto = false } = options;
  loadingLibraries.value = true;
  autoLoadingLibraries.value = isAuto;
  if (!isAuto) {
    message.value = "";
    error.value = "";
  }

  try {
    const data = await api.getLibraries();
    availableLibraries.value = Array.isArray(data?.items) ? data.items : [];
    if (!isAuto) {
      message.value = t("settings.messages.loadedLibraries", { count: availableLibraries.value.length });
    }
  } catch (e) {
    error.value = isAuto
      ? t("settings.messages.autoLoadLibrariesFailed", { message: e.message })
      : t("settings.messages.loadLibrariesFailed", { message: e.message });
  } finally {
    loadingLibraries.value = false;
    autoLoadingLibraries.value = false;
  }
}

async function saveSettings() {
  savingSettings.value = true;
  message.value = "";
  error.value = "";
  try {
    await api.putSettings({
      emby: {
        base_url: form.embyBaseUrl,
        api_key: form.embyApiKey,
        user_id: form.embyUserId,
      },
      libraries: form.selectedLibraries,
      excluded_paths: excludedPaths.value,
      shenyi: {
        base_url: form.embyBaseUrl,
        api_key: form.embyApiKey,
      },
      webhook_token: form.webhookToken,
    });
    message.value = t("settings.messages.settingsSaved");
  } catch (e) {
    error.value = t("settings.messages.saveSettingsFailed", { message: e.message });
  } finally {
    savingSettings.value = false;
  }
}

async function fetchSyncStatus(options = {}) {
  const { silent = false, fromPoll = false } = options;
  if (!silent) loadingSyncStatus.value = true;
  try {
    const data = await api.getSyncStatus();
    syncStatus.state = data?.state || "idle";
    syncStatus.last_started_at = data?.last_started_at || null;
    syncStatus.last_finished_at = data?.last_finished_at || null;
    syncStatus.items_synced = Number(data?.items_synced || 0);
    syncStatus.current_step = data?.current_step || null;
    syncStatus.current_library = data?.current_library || null;
    syncStatus.libraries_total = Number(data?.libraries_total || 0);
    syncStatus.libraries_completed = Number(data?.libraries_completed || 0);
    syncStatus.items_discovered = Number(data?.items_discovered || 0);
    syncStatus.detail_requests_total = Number(data?.detail_requests_total || 0);
    syncStatus.detail_requests_completed = Number(data?.detail_requests_completed || 0);
    syncStatus.current_page = Number(data?.current_page || 0);
    syncStatus.current_page_size = Number(data?.current_page_size || 0);
    syncStatus.current_library_total_items = Number(data?.current_library_total_items || 0);
    syncStatus.phase_started_at = data?.phase_started_at || null;
    syncStatus.timings = typeof data?.timings === "object" && data?.timings ? data.timings : {};
    syncStatus.failed_items = Number(data?.failed_items || 0);
    syncStatus.duration_seconds = data?.duration_seconds == null ? null : Number(data?.duration_seconds);
    syncStatus.last_result = data?.last_result || null;
    syncStatus.last_analysis_at = data?.last_analysis_at || null;
    syncStatus.analysis_groups = Number(data?.analysis_groups || 0);
    syncStatus.analysis_error = data?.analysis_error || null;
    syncStatus.error = data?.error || null;

    if (syncStatus.state === "running") {
      startSyncPolling();
    } else {
      const wasPolling = Boolean(syncPollingTimer.value);
      stopSyncPolling();
      if (fromPoll && wasPolling) {
        await fetchSyncStatus({ silent: true, fromPoll: false });
      }
    }
  } catch (e) {
    syncStatus.error = t("settings.messages.fetchStatusFailed", { message: e.message });
    if (fromPoll) stopSyncPolling();
  } finally {
    if (!silent) loadingSyncStatus.value = false;
  }
}

async function triggerSync() {
  triggeringSync.value = true;
  message.value = "";
  error.value = "";
  try {
    await api.triggerSync();
    message.value = t("settings.messages.syncTriggered");
    await fetchSyncStatus();
    if (syncStatus.state === "running") {
      startSyncPolling();
    }
  } catch (e) {
    error.value = t("settings.messages.triggerSyncFailed", { message: e.message });
  } finally {
    triggeringSync.value = false;
  }
}

function toggleLibrary(name) {
  if (form.selectedLibraries.includes(name)) {
    form.selectedLibraries = form.selectedLibraries.filter((x) => x !== name);
  } else {
    form.selectedLibraries = [...form.selectedLibraries, name];
  }
}

onMounted(async () => {
  await fetchSettings();
  if (hasEmbyConnectionSettings()) {
    await fetchLibraries({ isAuto: true });
  }
  await fetchSyncStatus();
});

onUnmounted(() => {
  stopSyncPolling();
});
</script>

<template>
  <section class="page">
    <header class="header">
      <h2>{{ t("settings.title") }}</h2>
      <div class="actions">
        <button type="button" @click="fetchLibraries()" :disabled="loadingLibraries">
          {{ loadingLibraries ? t("common.loading") : t("settings.buttons.loadLibraries") }}
        </button>
        <button type="button" @click="saveSettings" :disabled="savingSettings">
          {{ savingSettings ? t("common.loading") : t("settings.buttons.saveSettings") }}
        </button>
        <button type="button" @click="triggerSync" :disabled="triggeringSync || syncStatus.state === 'running'">
          {{ triggeringSync ? t("common.loading") : t("settings.buttons.triggerSync") }}
        </button>
      </div>
    </header>

    <p v-if="loadingSettings">{{ t("settings.messages.loadingSettings") }}</p>
    <p v-if="message" class="message">{{ message }}</p>
    <p v-if="error" class="error">{{ error }}</p>

    <div class="panel-grid">
      <article class="panel">
        <h3>{{ t("settings.sections.connection") }}</h3>
        <label>
          {{ t("settings.fields.embyBaseUrl") }}
          <input v-model="form.embyBaseUrl" type="text" :placeholder="t('settings.placeholders.embyBaseUrl')" />
        </label>
        <label>
          {{ t("settings.fields.embyApiKey") }}
          <input v-model="form.embyApiKey" type="password" :placeholder="t('settings.placeholders.embyApiKey')" />
        </label>
        <label>
          {{ t("settings.fields.embyUserId") }}
          <input v-model="form.embyUserId" type="text" :placeholder="t('settings.placeholders.embyUserId')" />
        </label>
        <label>
          {{ t("settings.fields.webhookToken") }}
          <input v-model="form.webhookToken" type="password" :placeholder="t('settings.placeholders.webhookToken')" />
        </label>
      </article>

      <article class="panel">
        <h3>{{ t("settings.sections.scope") }}</h3>
        <label>
          {{ t("settings.fields.selectedLibraries") }}
          <div class="library-list">
            <p v-if="autoLoadingLibraries" class="hint">{{ t("settings.messages.loadingLibrariesAuto") }}</p>
            <p v-else-if="availableLibraries.length === 0" class="hint">{{ t("settings.messages.librariesHint") }}</p>
            <label v-for="lib in availableLibraries" :key="lib.id" class="library-chip" :title="lib.name">
              <input type="checkbox" :checked="form.selectedLibraries.includes(lib.name)" @change="toggleLibrary(lib.name)" />
              <span class="library-name">{{ lib.name }}</span>
            </label>
          </div>
        </label>

        <label>
          {{ t("settings.fields.excludedPaths") }}
          <textarea v-model="form.excludedPathsText" rows="6" :placeholder="t('settings.placeholders.excludedPaths')" />
        </label>

      </article>

      <article class="panel">
        <h3>{{ t("settings.sections.syncStatus") }}</h3>

        <div v-if="isSyncRunning" class="running-indicator" aria-live="polite">
          <div class="running-bar"><span class="running-fill" :style="{ width: `${syncProgressPercent}%` }" /></div>
          <p class="running-text">
            {{ syncStatus.current_library
              ? t("settings.messages.runningLineWithLibrary", { step: stepLabel(syncStatus.current_step), library: syncStatus.current_library })
              : t("settings.messages.runningLine", { step: stepLabel(syncStatus.current_step) }) }}
          </p>
          <p class="running-sub">{{ t("settings.messages.runningSub", { synced: syncStatus.items_synced, failed: syncStatus.failed_items }) }}</p>
          <p class="running-sub">{{ t("settings.messages.runningDiscover", { librariesCompleted: syncStatus.libraries_completed, librariesTotal: syncStatus.libraries_total, discovered: syncStatus.items_discovered }) }}</p>
          <p class="running-sub">{{ t("settings.messages.runningFallback", { completed: syncStatus.detail_requests_completed, total: syncStatus.detail_requests_total, page: syncStatus.current_page, pageSize: syncStatus.current_page_size }) }}</p>
        </div>

        <p v-if="loadingSyncStatus">{{ t("settings.messages.refreshingStatus") }}</p>
        <dl class="status-grid">
          <dt>{{ t("settings.fields.state") }}</dt><dd>{{ stateLabel(syncStatus.state) }}</dd>
          <dt>{{ t("settings.fields.lastResult") }}</dt><dd>{{ stateLabel(syncStatus.last_result) }}</dd>
          <dt>{{ t("settings.fields.currentStep") }}</dt><dd>{{ stepLabel(syncStatus.current_step) }}</dd>
          <dt>{{ t("settings.fields.currentLibrary") }}</dt><dd>{{ syncStatus.current_library || t("common.unknown") }}</dd>
          <dt>{{ t("settings.fields.lastStarted") }}</dt><dd>{{ formatUtcToLocal(syncStatus.last_started_at) }}</dd>
          <dt>{{ t("settings.fields.lastFinished") }}</dt><dd>{{ formatUtcToLocal(syncStatus.last_finished_at) }}</dd>
          <dt>{{ t("settings.fields.duration") }}</dt><dd>{{ formatDuration(syncStatus.duration_seconds) }}</dd>
          <dt>{{ t("settings.fields.itemsSynced") }}</dt><dd>{{ syncStatus.items_synced }}</dd>
          <dt>{{ t("settings.fields.itemsDiscovered") }}</dt><dd>{{ syncStatus.items_discovered }}</dd>
          <dt>{{ t("settings.fields.librariesProgress") }}</dt><dd>{{ syncStatus.libraries_completed }} / {{ syncStatus.libraries_total }}</dd>
          <dt>{{ t("settings.fields.detailRequests") }}</dt><dd>{{ syncStatus.detail_requests_completed }} / {{ syncStatus.detail_requests_total }}</dd>
          <dt>{{ t("settings.fields.currentPage") }}</dt><dd>{{ syncStatus.current_page }} / {{ syncStatus.current_library_total_items || 0 }}</dd>
          <dt>{{ t("settings.fields.failedItems") }}</dt><dd>{{ syncStatus.failed_items }}</dd>
          <dt>{{ t("settings.fields.lastAnalysis") }}</dt><dd>{{ formatUtcToLocal(syncStatus.last_analysis_at) }}</dd>
          <dt>{{ t("settings.fields.analysisGroups") }}</dt><dd>{{ syncStatus.analysis_groups }}</dd>
          <dt>{{ t("settings.fields.phaseStartedAt") }}</dt><dd>{{ formatUtcToLocal(syncStatus.phase_started_at) }}</dd>
          <dt>{{ t("settings.fields.timings") }}</dt><dd>{{ JSON.stringify(syncStatus.timings || {}) }}</dd>
          <dt>{{ t("settings.fields.analysisError") }}</dt><dd class="error-inline">{{ syncStatus.analysis_error || t("common.unknown") }}</dd>
          <dt>{{ t("settings.fields.error") }}</dt><dd class="error-inline">{{ syncStatus.error || t("common.unknown") }}</dd>
        </dl>
        <button type="button" @click="fetchSyncStatus">{{ t("settings.buttons.refreshStatus") }}</button>
      </article>
    </div>
  </section>
</template>

<style scoped>
.page { display: flex; flex-direction: column; gap: 16px; }
.header { display: flex; justify-content: space-between; align-items: center; gap: 12px; }
.actions { display: flex; gap: 8px; flex-wrap: wrap; }
.panel-grid { display: grid; grid-template-columns: repeat(3, minmax(220px, 1fr)); gap: 12px; }
.panel { background: #fff; border: 1px solid #cbd5e1; border-radius: 10px; padding: 14px; display: flex; flex-direction: column; gap: 10px; }
label { display: flex; flex-direction: column; gap: 6px; font-size: 14px; }
input, textarea, button { font: inherit; }
input, textarea { border: 1px solid #94a3b8; border-radius: 8px; padding: 8px; }
button { border: 1px solid #334155; background: #334155; color: #fff; border-radius: 8px; padding: 8px 12px; cursor: pointer; }
button:disabled { opacity: 0.6; cursor: not-allowed; }
.message { color: #166534; }
.error, .error-inline { color: #b91c1c; }
.hint { color: #64748b; margin: 0; }
.library-list { display: flex; flex-wrap: wrap; gap: 8px; padding: 2px 0; }
.library-chip { display: inline-flex; flex-direction: row; align-items: center; gap: 6px; border: 1px solid #cbd5e1; border-radius: 999px; padding: 6px 10px; background: #f8fafc; max-width: 260px; }
.library-name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.status-grid { display: grid; grid-template-columns: 120px 1fr; gap: 4px 8px; margin: 0; }
.status-grid dt { font-weight: 600; }
.status-grid dd { margin: 0; }
.running-indicator { border: 1px solid #bfdbfe; background: #eff6ff; border-radius: 8px; padding: 10px; display: flex; flex-direction: column; gap: 6px; }
.running-bar { width: 100%; height: 6px; border-radius: 999px; overflow: hidden; background: #dbeafe; }
.running-fill { display: block; height: 100%; border-radius: 999px; background: linear-gradient(90deg, #60a5fa, #2563eb, #60a5fa); animation: pulse 1.2s ease-in-out infinite; transition: width 0.25s ease; }
.running-text { margin: 0; color: #1e3a8a; font-weight: 600; }
.running-sub { margin: 0; color: #334155; font-size: 13px; }
@keyframes pulse {
  0% { filter: brightness(0.95); }
  50% { filter: brightness(1.1); }
  100% { filter: brightness(0.95); }
}
@media (max-width: 1100px) { .panel-grid { grid-template-columns: 1fr; } }
</style>


