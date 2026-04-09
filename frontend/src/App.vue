<script setup>
import { useI18n } from "vue-i18n";

const { t } = useI18n();
</script>

<template>
  <div class="layout">
    <aside class="sidebar">
      <h1>{{ t("app.title") }}</h1>
      <nav>
        <RouterLink to="/dashboard">{{ t("app.nav.dashboard") }}</RouterLink>
        <RouterLink to="/settings-sync">{{ t("app.nav.settings") }}</RouterLink>
        <RouterLink to="/analysis-groups">{{ t("app.nav.analysisGroups") }}</RouterLink>
        <RouterLink to="/metadata-issues">{{ t("app.nav.metadataIssues") }}</RouterLink>
      </nav>
    </aside>
    <main class="content">
      <RouterView />
    </main>
  </div>
</template>

<style scoped>
.layout { min-height: 100vh; display: grid; grid-template-columns: 220px 1fr; }
.sidebar { padding: 20px; background: #0f172a; color: #e2e8f0; }
.sidebar h1 { margin-top: 0; font-size: 20px; }
.sidebar nav { display: flex; flex-direction: column; gap: 10px; }
.sidebar a { text-decoration: none; padding: 8px 10px; border-radius: 6px; }
.sidebar a.router-link-active { background: #334155; }
.content { padding: 24px; }
@media (max-width: 900px) { .layout { grid-template-columns: 1fr; } .sidebar nav { flex-direction: row; flex-wrap: wrap; } }
</style>
