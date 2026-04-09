<script setup>
import { computed, onMounted, ref, watch } from "vue";

import { api } from "../api/client";

const props = defineProps({
  groupId: {
    type: String,
    required: true,
  },
});

const loading = ref(false);
const overriding = ref(false);
const error = ref("");
const message = ref("");
const detail = ref(null);
const selectedKeepItemId = ref(null);

function isKeepAction(action) {
  return action === "keep_recommended" || action === "keep_manual";
}

function normalizeItem(item, fallbackAction = "") {
  const meta = item?.metadata || {};
  return {
    itemId: item?.item_id ?? null,
    embyItemId: item?.emby_item_id ?? "",
    mediaSourceId: item?.media_source_id ?? "",
    title: item?.title || "(untitled)",
    action: item?.action || fallbackAction,
    isProtected: item?.action === "protected" || false,
    reason: item?.reason || {},
    path: item?.path || meta?.path || "",
    metadata: {
      ...meta,
      subtitle_streams: Array.isArray(meta?.subtitle_streams) ? meta.subtitle_streams : [],
      audio_streams: Array.isArray(meta?.audio_streams) ? meta.audio_streams : [],
    },
  };
}

function normalizeDetail(raw) {
  if (!raw || typeof raw !== "object") return null;

  const keep = raw.keep_item ? normalizeItem(raw.keep_item, "keep_recommended") : null;
  const deleteCandidates = Array.isArray(raw.delete_candidates)
    ? raw.delete_candidates.map((x) => normalizeItem(x, "delete_candidate"))
    : [];
  const protectedItems = Array.isArray(raw.protected_items)
    ? raw.protected_items.map((x) => normalizeItem(x, "protected"))
    : [];

  return {
    groupId: raw.group_id || "",
    title: raw.title || "(untitled)",
    tmdbId: raw?.comparison?.tmdb_id || "",
    mediaKind: raw.media_kind || "",
    seasonNumber: raw?.comparison?.season_number ?? null,
    episodeNumber: raw?.comparison?.episode_number ?? null,
    keepItem: keep,
    deleteCandidates,
    protectedItems,
  };
}

function formatEpisode(season, episode) {
  if (season == null || episode == null) return "-";
  return `S${season}E${episode}`;
}

function formatNumber(value) {
  if (value == null || value === "") return "-";
  return String(value);
}

function formatRuntime(seconds) {
  if (seconds == null) return "-";
  const total = Math.max(0, Number(seconds));
  if (!Number.isFinite(total)) return "-";
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = Math.floor(total % 60);
  if (h > 0) return `${h}h ${m}m ${s}s`;
  return `${m}m ${s}s`;
}

function formatFileSize(bytes) {
  const n = Number(bytes);
  if (!Number.isFinite(n) || n <= 0) return "-";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let i = 0;
  let value = n;
  while (value >= 1024 && i < units.length - 1) {
    value /= 1024;
    i += 1;
  }
  return `${value.toFixed(value >= 10 || i === 0 ? 0 : 1)} ${units[i]}`;
}

function formatBitrate(value) {
  const n = Number(value);
  if (!Number.isFinite(n) || n <= 0) return "-";
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(2)} Mbps`;
  return `${(n / 1_000).toFixed(0)} Kbps`;
}

function formatFrameRate(value) {
  const n = Number(value);
  if (!Number.isFinite(n) || n <= 0) return "-";
  return `${n.toFixed(3).replace(/0+$/, "").replace(/\.$/, "")} fps`;
}

function formatBitDepth(value) {
  const n = Number(value);
  if (!Number.isFinite(n) || n <= 0) return "-";
  return `${n}-bit`;
}

function subtitleCategoryLabel(category) {
  const map = {
    simplified: "Simplified Chinese",
    traditional: "Traditional Chinese",
    bilingual_cn: "Bilingual Chinese",
    generic_chinese: "Chinese",
    none: "None",
  };
  return map[category] || category || "None";
}

const hasAnyItems = computed(() => {
  if (!detail.value) return false;
  return !!detail.value.keepItem || detail.value.deleteCandidates.length > 0 || detail.value.protectedItems.length > 0;
});

const allSelectableItems = computed(() => {
  if (!detail.value) return [];
  const list = [];
  if (detail.value.keepItem) list.push(detail.value.keepItem);
  list.push(...detail.value.deleteCandidates);
  list.push(...detail.value.protectedItems);
  return list;
});

async function loadDetail() {
  loading.value = true;
  error.value = "";
  message.value = "";

  try {
    const data = await api.getAnalysisGroup(props.groupId);
    detail.value = normalizeDetail(data);
    selectedKeepItemId.value = detail.value?.keepItem?.itemId ?? null;
    message.value = "Group detail loaded.";
  } catch (e) {
    detail.value = null;
    selectedKeepItemId.value = null;
    error.value = `Failed to load group detail: ${e.message}`;
  } finally {
    loading.value = false;
  }
}

async function submitOverride() {
  if (!selectedKeepItemId.value) {
    error.value = "Please choose a keep item.";
    return;
  }

  overriding.value = true;
  error.value = "";
  message.value = "";
  try {
    await api.overrideAnalysisGroup(props.groupId, selectedKeepItemId.value);
    message.value = "Manual override applied.";
    await loadDetail();
  } catch (e) {
    error.value = `Failed to apply override: ${e.message}`;
  } finally {
    overriding.value = false;
  }
}

onMounted(loadDetail);
watch(() => props.groupId, loadDetail);
</script>

<template>
  <section class="page">
    <header class="header">
      <div>
        <h2>Group Detail</h2>
        <p class="muted">Group ID: {{ groupId }}</p>
      </div>
      <button type="button" @click="loadDetail" :disabled="loading || overriding">
        {{ loading ? "Loading..." : "Reload" }}
      </button>
    </header>

    <p v-if="message" class="message">{{ message }}</p>
    <p v-if="error" class="error">{{ error }}</p>

    <article v-if="detail" class="group-summary">
      <p><strong>Title:</strong> {{ detail.title }}</p>
      <p><strong>TMDb ID:</strong> {{ detail.tmdbId || "-" }}</p>
      <p><strong>Media Type:</strong> {{ detail.mediaKind || "-" }}</p>
      <p><strong>Episode:</strong> {{ formatEpisode(detail.seasonNumber, detail.episodeNumber) }}</p>
    </article>

    <section v-if="allSelectableItems.length > 0" class="override-panel">
      <h3>Manual Override</h3>
      <p class="muted">Choose a keep item. Protected entries stay protected and are never deletable.</p>
      <div class="override-controls">
        <select v-model.number="selectedKeepItemId">
          <option v-for="item in allSelectableItems" :key="item.itemId" :value="item.itemId">
            #{{ item.itemId }} - {{ item.title }}{{ item.isProtected ? " [PROTECTED]" : "" }}
          </option>
        </select>
        <button type="button" @click="submitOverride" :disabled="overriding || loading">
          {{ overriding ? "Applying..." : "Apply Keep Item" }}
        </button>
      </div>
    </section>

    <p v-if="!loading && detail && !hasAnyItems" class="muted">No items found for this group.</p>

    <section v-if="detail?.keepItem" class="section keep-section">
      <h3>Keep Item (Current)</h3>
      <article class="item-card keep-card">
        <header class="item-header">
          <h4>#{{ detail.keepItem.itemId }} - {{ detail.keepItem.title }}</h4>
          <span class="badge keep">{{ detail.keepItem.action }}</span>
        </header>

        <div class="cards-grid">
          <section class="mini-card">
            <h5>Top Summary</h5>
            <p>Codec: {{ detail.keepItem.metadata.codec_label || "-" }}</p>
            <p>Resolution: {{ detail.keepItem.metadata.resolution_label || "-" }}</p>
            <p>Effect: {{ detail.keepItem.metadata.effect_label || "-" }}</p>
            <p>Subtitle: {{ subtitleCategoryLabel(detail.keepItem.metadata.subtitle_category) }}</p>
            <p>Runtime: {{ formatRuntime(detail.keepItem.metadata.runtime_seconds) }}</p>
          </section>

          <section class="mini-card">
            <h5>Video</h5>
            <p>{{ detail.keepItem.metadata.video_display_title || "-" }}</p>
            <p>{{ detail.keepItem.metadata.video_codec || "-" }} | {{ detail.keepItem.metadata.video_profile || "-" }}</p>
            <p>{{ detail.keepItem.metadata.video_width || "-" }} x {{ detail.keepItem.metadata.video_height || "-" }}</p>
            <p>{{ formatBitDepth(detail.keepItem.metadata.bit_depth) }} | {{ formatFrameRate(detail.keepItem.metadata.frame_rate) }}</p>
            <p>{{ detail.keepItem.metadata.video_range || "-" }} | {{ detail.keepItem.metadata.effect_label || "-" }}</p>
          </section>

          <section class="mini-card">
            <h5>Audio</h5>
            <p>{{ detail.keepItem.metadata.audio_display_title || "-" }}</p>
            <p>{{ detail.keepItem.metadata.audio_codec || "-" }} | {{ detail.keepItem.metadata.audio_profile || "-" }}</p>
            <p>{{ formatNumber(detail.keepItem.metadata.audio_channels) }} ch | {{ detail.keepItem.metadata.audio_channel_layout || "-" }}</p>
            <p>{{ formatBitrate(detail.keepItem.metadata.audio_bitrate) }} | {{ formatNumber(detail.keepItem.metadata.audio_sample_rate) }} Hz</p>
          </section>

          <section class="mini-card">
            <h5>Subtitle</h5>
            <p>Category: {{ subtitleCategoryLabel(detail.keepItem.metadata.subtitle_category) }}</p>
            <p>Chinese: {{ detail.keepItem.metadata.has_chinese_subtitle ? "Yes" : "No" }}</p>
            <p>Tracks: {{ detail.keepItem.metadata.subtitle_streams.length }}</p>
          </section>

          <section class="mini-card wide">
            <h5>Source</h5>
            <p>Emby Item: {{ detail.keepItem.embyItemId }}</p>
            <p>Media Source: {{ detail.keepItem.mediaSourceId }}</p>
            <p>Source Name: {{ detail.keepItem.metadata.media_source_name || "-" }}</p>
            <p>Container: {{ detail.keepItem.metadata.container || "-" }}</p>
            <p>File Size: {{ formatFileSize(detail.keepItem.metadata.file_size) }}</p>
            <p>Bitrate: {{ formatBitrate(detail.keepItem.metadata.bitrate) }}</p>
            <p class="path">Path: {{ detail.keepItem.path || "-" }}</p>
          </section>
        </div>
      </article>
    </section>

    <section v-if="detail && detail.deleteCandidates.length > 0" class="section">
      <h3>Delete Candidates</h3>
      <div class="stack">
        <article v-for="item in detail.deleteCandidates" :key="`del-${item.itemId}`" class="item-card">
          <header class="item-header">
            <h4>#{{ item.itemId }} - {{ item.title }}</h4>
            <span class="badge delete">delete_candidate</span>
          </header>
          <p class="muted">{{ item.metadata.codec_label || "-" }} | {{ item.metadata.resolution_label || "-" }} | {{ item.metadata.effect_label || "-" }}</p>
          <p class="path">{{ item.path || "-" }}</p>
        </article>
      </div>
    </section>

    <section v-if="detail && detail.protectedItems.length > 0" class="section protected-section">
      <h3>Protected Items</h3>
      <div class="stack">
        <article v-for="item in detail.protectedItems" :key="`prot-${item.itemId}`" class="item-card protected-card">
          <header class="item-header">
            <h4>#{{ item.itemId }} - {{ item.title }}</h4>
            <span class="badge protected">protected</span>
          </header>
          <p class="muted">{{ item.metadata.codec_label || "-" }} | {{ item.metadata.resolution_label || "-" }} | {{ item.metadata.effect_label || "-" }}</p>
          <p class="path">{{ item.path || "-" }}</p>
        </article>
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
  gap: 12px;
}

button,
select {
  font: inherit;
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

select {
  min-width: 360px;
  border: 1px solid #94a3b8;
  border-radius: 8px;
  padding: 8px;
}

.group-summary,
.override-panel,
.item-card {
  background: #ffffff;
  border: 1px solid #cbd5e1;
  border-radius: 10px;
  padding: 12px;
}

.group-summary p {
  margin: 4px 0;
}

.override-controls {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  align-items: center;
}

.section {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.stack {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.item-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
}

.item-header h4 {
  margin: 0;
}

.badge {
  border-radius: 999px;
  padding: 2px 8px;
  font-size: 12px;
}

.badge.keep {
  background: #dcfce7;
  color: #166534;
}

.badge.delete {
  background: #fee2e2;
  color: #991b1b;
}

.badge.protected {
  background: #fef3c7;
  color: #92400e;
}

.keep-card {
  border-color: #15803d;
  background: #f0fdf4;
}

.protected-card {
  border-color: #b45309;
  background: #fffbeb;
}

.cards-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}

.mini-card {
  border: 1px solid #dbeafe;
  background: #f8fbff;
  border-radius: 8px;
  padding: 10px;
}

.mini-card h5 {
  margin: 0 0 6px;
}

.mini-card p {
  margin: 4px 0;
}

.mini-card.wide {
  grid-column: span 2;
}

.path {
  word-break: break-all;
}

.keep-section h3 {
  color: #15803d;
}

.protected-section h3 {
  color: #b45309;
}

.message {
  color: #166534;
}

.error {
  color: #b91c1c;
}

.muted {
  color: #64748b;
  margin: 0;
}

@media (max-width: 900px) {
  .cards-grid {
    grid-template-columns: 1fr;
  }

  .mini-card.wide {
    grid-column: span 1;
  }

  select {
    min-width: 220px;
    width: 100%;
  }
}
</style>
