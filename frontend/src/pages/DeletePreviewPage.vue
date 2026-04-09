<script setup>
import { onMounted, ref } from "vue";

import { api } from "../api/client";

const loading = ref(false);
const executing = ref(false);
const error = ref("");
const message = ref("");
const groups = ref([]);
const summary = ref({ delete_count: 0, protected_count: 0 });
const execution = ref({ success_count: 0, failed_count: 0, results: [] });

function normalizeItem(item) {
  const meta = item?.metadata || {};
  return {
    itemId: item?.item_id ?? null,
    title: item?.title || "(untitled)",
    path: item?.path || "",
    hasChineseSubtitle: meta?.has_chinese_subtitle ?? false,
    runtime: meta?.runtime_seconds ?? null,
    effect: meta?.effect_label ?? "",
    resolution: meta?.resolution_label ?? "",
    bitDepth: meta?.bit_depth ?? null,
    bitrate: meta?.bitrate ?? null,
    codec: meta?.video_codec ?? "",
    frameRate: meta?.frame_rate ?? null,
    fileSize: meta?.file_size ?? null,
  };
}

function normalizeGroup(group) {
  return {
    groupId: group?.group_id || "",
    title: group?.title || "(untitled)",
    mediaKind: group?.media_kind || "",
    tmdbId: group?.comparison?.tmdb_id || "",
    seasonNumber: group?.comparison?.season_number ?? null,
    episodeNumber: group?.comparison?.episode_number ?? null,
    keepItem: group?.keep_item ? normalizeItem(group.keep_item) : null,
    deleteCandidates: Array.isArray(group?.delete_candidates)
      ? group.delete_candidates.map(normalizeItem)
      : [],
    protectedItems: Array.isArray(group?.protected_items)
      ? group.protected_items.map(normalizeItem)
      : [],
  };
}

function formatEpisode(season, episode) {
  if (season == null || episode == null) return "-";
  return `S${season}E${episode}`;
}

function formatNumber(value) {
  return value == null || value === "" ? "-" : String(value);
}

function formatRuntime(seconds) {
  if (seconds == null) return "-";
  const total = Math.max(0, Number(seconds));
  if (!Number.isFinite(total)) return "-";
  const mins = Math.floor(total / 60);
  const secs = Math.floor(total % 60);
  return `${mins}m ${secs}s`;
}

async function loadPreview() {
  loading.value = true;
  error.value = "";
  message.value = "";

  try {
    const data = await api.getDeletePreview({ group_ids: [] });
    groups.value = Array.isArray(data?.groups) ? data.groups.map(normalizeGroup) : [];
    summary.value = {
      delete_count: Number(data?.delete_count || 0),
      protected_count: Number(data?.protected_count || 0),
    };
    message.value = `Loaded preview for ${groups.value.length} group(s).`;
  } catch (e) {
    groups.value = [];
    error.value = `Failed to load delete preview: ${e.message}`;
  } finally {
    loading.value = false;
  }
}

async function executeDelete() {
  executing.value = true;
  error.value = "";
  message.value = "";
  execution.value = { success_count: 0, failed_count: 0, results: [] };

  try {
    const groupIds = groups.value.map((g) => g.groupId).filter(Boolean);
    const data = await api.executeDelete({ group_ids: groupIds });
    execution.value = {
      success_count: Number(data?.success_count || 0),
      failed_count: Number(data?.failed_count || 0),
      results: Array.isArray(data?.results) ? data.results : [],
    };
    message.value = "Delete execution finished.";
    await loadPreview();
  } catch (e) {
    error.value = `Delete execution failed: ${e.message}`;
  } finally {
    executing.value = false;
  }
}

onMounted(loadPreview);
</script>

<template>
  <section class="page">
    <header class="header">
      <h2>Delete Preview</h2>
      <div class="actions">
        <button type="button" @click="loadPreview" :disabled="loading || executing">
          {{ loading ? "Loading..." : "Reload Preview" }}
        </button>
        <button
          type="button"
          class="danger"
          @click="executeDelete"
          :disabled="executing || loading || summary.delete_count === 0"
        >
          {{ executing ? "Executing..." : "Execute Delete Candidates" }}
        </button>
      </div>
    </header>

    <p v-if="message" class="message">{{ message }}</p>
    <p v-if="error" class="error">{{ error }}</p>

    <article class="summary">
      <p><strong>Total Groups:</strong> {{ groups.length }}</p>
      <p><strong>Total Delete Candidates:</strong> {{ summary.delete_count }}</p>
      <p><strong>Total Protected Items:</strong> {{ summary.protected_count }}</p>
    </article>

    <article v-if="execution.results.length > 0" class="execution">
      <h3>Execution Results</h3>
      <p>
        <strong>Success:</strong> {{ execution.success_count }} |
        <strong>Failed:</strong> {{ execution.failed_count }}
      </p>
      <table class="results-table">
        <thead>
          <tr>
            <th>Group</th>
            <th>Item ID</th>
            <th>Emby ID</th>
            <th>Status</th>
            <th>Status Code</th>
            <th>Message</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in execution.results" :key="`${row.group_id}-${row.item_id}`">
            <td>{{ row.group_id }}</td>
            <td>{{ row.item_id }}</td>
            <td>{{ row.emby_item_id }}</td>
            <td :class="row.status === 'success' ? 'ok' : 'fail'">{{ row.status }}</td>
            <td>{{ row.status_code ?? "-" }}</td>
            <td>{{ row.message }}</td>
          </tr>
        </tbody>
      </table>
    </article>

    <p v-if="!loading && groups.length === 0" class="muted">No preview data. Run analysis first.</p>

    <section v-for="group in groups" :key="group.groupId" class="group-card">
      <h3>{{ group.title }}</h3>
      <p class="muted">
        Group: {{ group.groupId }} | Type: {{ group.mediaKind || "-" }} | TMDb: {{ group.tmdbId || "-" }} |
        Episode: {{ formatEpisode(group.seasonNumber, group.episodeNumber) }}
      </p>

      <div v-if="group.keepItem" class="item-block keep">
        <h4>Keep Item</h4>
        <p>#{{ group.keepItem.itemId }} - {{ group.keepItem.title }}</p>
        <p class="path">{{ group.keepItem.path || "-" }}</p>
      </div>

      <div class="item-block">
        <h4>Delete Candidates ({{ group.deleteCandidates.length }})</h4>
        <ul>
          <li v-for="item in group.deleteCandidates" :key="`d-${group.groupId}-${item.itemId}`">
            #{{ item.itemId }} - {{ item.title }} | Subtitle: {{ item.hasChineseSubtitle ? "Yes" : "No" }} |
            Runtime: {{ formatRuntime(item.runtime) }} | Effect: {{ item.effect || "-" }} | Resolution: {{ item.resolution || "-" }} |
            Bit Depth: {{ formatNumber(item.bitDepth) }} | Bitrate: {{ formatNumber(item.bitrate) }} | Codec: {{ item.codec || "-" }} |
            Frame Rate: {{ formatNumber(item.frameRate) }} | File Size: {{ formatNumber(item.fileSize) }}
            <div class="path">{{ item.path || "-" }}</div>
          </li>
          <li v-if="group.deleteCandidates.length === 0" class="muted">None</li>
        </ul>
      </div>

      <div class="item-block protected">
        <h4>Protected Items ({{ group.protectedItems.length }})</h4>
        <ul>
          <li v-for="item in group.protectedItems" :key="`p-${group.groupId}-${item.itemId}`">
            #{{ item.itemId }} - {{ item.title }} [PROTECTED]
            <div class="path">{{ item.path || "-" }}</div>
          </li>
          <li v-if="group.protectedItems.length === 0" class="muted">None</li>
        </ul>
      </div>
    </section>
  </section>
</template>

<style scoped>
.page {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.actions {
  display: flex;
  gap: 8px;
}

button {
  border: 1px solid #334155;
  background: #334155;
  color: #ffffff;
  border-radius: 8px;
  padding: 8px 12px;
  cursor: pointer;
}

button:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

button.danger {
  border-color: #b91c1c;
  background: #b91c1c;
}

.summary,
.group-card,
.execution {
  background: #ffffff;
  border: 1px solid #cbd5e1;
  border-radius: 10px;
  padding: 12px;
}

.group-card {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.results-table {
  width: 100%;
  border-collapse: collapse;
}

.results-table th,
.results-table td {
  border-bottom: 1px solid #e2e8f0;
  padding: 8px;
  text-align: left;
}

.ok {
  color: #166534;
  font-weight: 600;
}

.fail {
  color: #b91c1c;
  font-weight: 600;
}

.item-block {
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 10px;
}

.keep {
  border-color: #15803d;
  background: #f0fdf4;
}

.protected {
  border-color: #b45309;
  background: #fffbeb;
}

.path {
  word-break: break-all;
  color: #475569;
}

ul {
  margin: 0;
  padding-left: 18px;
}

.message {
  color: #166534;
}

.error {
  color: #b91c1c;
}

.muted {
  color: #64748b;
}
</style>
