<script setup>
import { onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";

import { api } from "../api/client";

const { t } = useI18n();

const loading = ref(false);
const message = ref("");
const error = ref("");
const issues = ref([]);

function formatMediaSourceId(value) {
  const raw = String(value || "").trim();
  if (!raw) return t("common.unknown");
  const marker = "mediasource_";
  if (raw.toLowerCase().startsWith(marker)) {
    return raw.slice(marker.length) || raw;
  }
  return raw;
}

function issueTypeLabel(v) {
  if (!v) return t("common.unknown");
  const key = String(v).trim();
  const i18nKey = `metadataIssues.issueType.${key}`;
  const translated = t(i18nKey);
  return translated === i18nKey ? key : translated;
}

async function loadIssues() {
  loading.value = true;
  message.value = "";
  error.value = "";
  try {
    const data = await api.getMetadataIssues();
    issues.value = Array.isArray(data?.items) ? data.items : [];
    message.value = t("metadataIssues.loaded", { count: issues.value.length });
  } catch (e) {
    error.value = t("metadataIssues.loadFailed", { message: e.message });
  } finally {
    loading.value = false;
  }
}

function refreshMetadataPlaceholder() {
  message.value = t("metadataIssues.refreshTodo");
}

onMounted(loadIssues);
</script>

<template>
  <section class="page">
    <header class="header">
      <h2>{{ t("metadataIssues.title") }}</h2>
      <div class="actions">
        <button type="button" @click="refreshMetadataPlaceholder">{{ t("metadataIssues.refreshMetadata") }}</button>
        <button type="button" @click="loadIssues" :disabled="loading">
          {{ loading ? t("common.loading") : t("metadataIssues.reload") }}
        </button>
      </div>
    </header>

    <p v-if="message" class="message">{{ message }}</p>
    <p v-if="error" class="error">{{ error }}</p>

    <table class="issues-table" v-if="!loading">
      <thead>
        <tr>
          <th>{{ t("metadataIssues.columns.title") }}</th>
          <th>{{ t("metadataIssues.columns.embyItemId") }}</th>
          <th>{{ t("metadataIssues.columns.mediaSourceId") }}</th>
          <th>{{ t("metadataIssues.columns.tmdbId") }}</th>
          <th>{{ t("metadataIssues.columns.issueType") }}</th>
          <th>{{ t("metadataIssues.columns.path") }}</th>
        </tr>
      </thead>
      <tbody>
        <tr v-if="issues.length === 0">
          <td colspan="6">{{ t("metadataIssues.empty") }}</td>
        </tr>
        <tr v-for="item in issues" :key="`${item.emby_item_id}:${item.media_source_id}:${item.path}`">
          <td class="clip title-cell" :title="item.title || t('common.unknown')">{{ item.title || t("common.unknown") }}</td>
          <td class="mono">{{ item.emby_item_id || t("common.unknown") }}</td>
          <td class="mono">{{ formatMediaSourceId(item.media_source_id) }}</td>
          <td class="mono">{{ item.tmdb_id || t("common.unknown") }}</td>
          <td>{{ issueTypeLabel(item.issue_type) }}</td>
          <td class="path-cell clip" :title="item.path || t('common.unknown')">{{ item.path || t("common.unknown") }}</td>
        </tr>
      </tbody>
    </table>
    <p v-else>{{ t("metadataIssues.loading") }}</p>
  </section>
</template>

<style scoped>
.page { display: flex; flex-direction: column; gap: 10px; }
.header { display: flex; justify-content: space-between; align-items: center; }
.actions { display: flex; gap: 8px; }
button { border: 1px solid #334155; background: #334155; color: #ffffff; border-radius: 8px; padding: 8px 12px; cursor: pointer; }
button:disabled { opacity: 0.6; cursor: not-allowed; }
.issues-table { width: 100%; border-collapse: collapse; background: #ffffff; border: 1px solid #cbd5e1; table-layout: fixed; }
.issues-table th, .issues-table td { padding: 6px 10px; border-bottom: 1px solid #e2e8f0; text-align: left; vertical-align: middle; white-space: nowrap; }
.issues-table th:nth-child(1) { width: 18%; }
.issues-table th:nth-child(2) { width: 10%; }
.issues-table th:nth-child(3) { width: 14%; }
.issues-table th:nth-child(4) { width: 8%; }
.issues-table th:nth-child(5) { width: 8%; }
.issues-table th:nth-child(6) { width: 42%; }
.mono { font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace; }
.clip { overflow: hidden; text-overflow: ellipsis; }
.title-cell { max-width: 0; }
.path-cell { max-width: 0; }
.message { color: #166534; }
.error { color: #b91c1c; }
</style>
