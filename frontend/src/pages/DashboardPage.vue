<script setup>
import { onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";

import { api } from "../api/client";

const { t } = useI18n();

const loading = ref(false);
const error = ref("");
const stats = ref({ movie_count: 0, series_count: 0, episode_count: 0, storage_size_total: null });

function formatFileSize(v) {
  const n = Number(v);
  if (!Number.isFinite(n) || n <= 0) return t("common.unknown");
  const u = ["B", "KB", "MB", "GB", "TB"];
  let i = 0;
  let x = n;
  while (x >= 1024 && i < u.length - 1) { x /= 1024; i += 1; }
  return `${x.toFixed(x >= 10 || i === 0 ? 0 : 1)} ${u[i]}`;
}

async function loadStats() {
  loading.value = true;
  error.value = "";
  try {
    const data = await api.getDashboardStats();
    stats.value = {
      movie_count: Number(data?.movie_count || 0),
      series_count: Number(data?.series_count || 0),
      episode_count: Number(data?.episode_count || 0),
      storage_size_total: data?.storage_size_total == null ? null : Number(data.storage_size_total),
    };
  } catch (e) {
    error.value = t("dashboard.loadFailed", { message: e.message });
  } finally {
    loading.value = false;
  }
}

onMounted(loadStats);
</script>

<template>
  <section class="page">
    <header class="header">
      <h2>{{ t("dashboard.title") }}</h2>
      <button type="button" @click="loadStats" :disabled="loading">{{ loading ? t("common.loading") : t("dashboard.refresh") }}</button>
    </header>

    <p v-if="error" class="error">{{ error }}</p>

    <div class="cards">
      <article class="card"><h3>{{ t("dashboard.cards.movieCount") }}</h3><p>{{ stats.movie_count }}</p></article>
      <article class="card"><h3>{{ t("dashboard.cards.seriesCount") }}</h3><p>{{ stats.series_count }}</p></article>
      <article class="card"><h3>{{ t("dashboard.cards.episodeCount") }}</h3><p>{{ stats.episode_count }}</p></article>
      <article class="card"><h3>{{ t("dashboard.cards.storageTotal") }}</h3><p>{{ formatFileSize(stats.storage_size_total) }}</p></article>
    </div>

    <p class="muted">{{ t("dashboard.desc") }}</p>
  </section>
</template>

<style scoped>
.page { display: flex; flex-direction: column; gap: 12px; }
.header { display: flex; justify-content: space-between; align-items: center; }
button { border: 1px solid #334155; background: #334155; color: #fff; border-radius: 8px; padding: 8px 12px; cursor: pointer; }
button:disabled { opacity: 0.6; cursor: not-allowed; }
.cards { display: grid; grid-template-columns: repeat(4, minmax(150px, 1fr)); gap: 10px; }
.card { background: #fff; border: 1px solid #cbd5e1; border-radius: 10px; padding: 12px; }
.card h3 { margin: 0 0 8px; font-size: 14px; color: #475569; }
.card p { margin: 0; font-size: 24px; font-weight: 700; color: #0f172a; }
.error { color: #b91c1c; }
.muted { color: #64748b; }
@media (max-width: 900px) { .cards { grid-template-columns: repeat(2, minmax(120px, 1fr)); } }
</style>
