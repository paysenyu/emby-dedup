<script setup>
import { useI18n } from "vue-i18n";
import { APP_VERSION, REPO_URL } from "./version";

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
      <div class="sidebar-footer">
        <span class="version-label">{{ t("app.footer.version", { version: APP_VERSION }) }}</span>
        <a
          class="github-link"
          :href="REPO_URL"
          target="_blank"
          rel="noopener noreferrer"
          :aria-label="t('app.footer.githubAria')"
          :title="t('app.footer.githubAria')"
        >
          <svg viewBox="0 0 16 16" aria-hidden="true">
            <path
              d="M8 0C3.58 0 0 3.65 0 8.15c0 3.6 2.29 6.66 5.47 7.73.4.08.55-.18.55-.39 0-.19-.01-.82-.01-1.49-2.01.38-2.53-.51-2.69-.98-.09-.24-.48-.98-.82-1.18-.28-.15-.68-.53-.01-.54.63-.01 1.08.59 1.23.83.72 1.25 1.88.9 2.34.69.07-.54.28-.9.5-1.11-1.78-.21-3.64-.92-3.64-4.09 0-.9.31-1.64.82-2.22-.08-.21-.36-1.05.08-2.19 0 0 .67-.22 2.2.85a7.45 7.45 0 0 1 4 0c1.53-1.07 2.2-.85 2.2-.85.44 1.14.16 1.98.08 2.19.51.58.82 1.31.82 2.22 0 3.18-1.87 3.88-3.65 4.09.29.25.54.73.54 1.49 0 1.07-.01 1.94-.01 2.21 0 .21.15.47.55.39A8.19 8.19 0 0 0 16 8.15C16 3.65 12.42 0 8 0Z"
            />
          </svg>
        </a>
      </div>
    </aside>
    <main class="content">
      <RouterView />
    </main>
  </div>
</template>

<style scoped>
.layout { min-height: 100vh; display: grid; grid-template-columns: 220px 1fr; }
.sidebar { padding: 20px; background: #0f172a; color: #e2e8f0; display: flex; flex-direction: column; }
.sidebar h1 { margin-top: 0; font-size: 20px; }
.sidebar nav { display: flex; flex-direction: column; gap: 10px; }
.sidebar a { text-decoration: none; padding: 8px 10px; border-radius: 6px; }
.sidebar a.router-link-active { background: #334155; }
.sidebar-footer { margin-top: auto; padding-top: 16px; display: flex; align-items: center; justify-content: space-between; gap: 8px; border-top: 1px solid rgba(148, 163, 184, 0.25); }
.version-label { font-size: 12px; color: #94a3b8; }
.github-link { width: 28px; height: 28px; border-radius: 6px; display: inline-flex; align-items: center; justify-content: center; color: #e2e8f0; background: transparent; border: 1px solid rgba(148, 163, 184, 0.35); padding: 0; }
.github-link:hover { background: #1e293b; border-color: #64748b; }
.github-link svg { width: 16px; height: 16px; fill: currentColor; }
.content { padding: 24px; }
@media (max-width: 900px) { .layout { grid-template-columns: 1fr; } .sidebar nav { flex-direction: row; flex-wrap: wrap; } .sidebar-footer { margin-top: 16px; } }
</style>
