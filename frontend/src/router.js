import { createRouter, createWebHistory } from "vue-router";

import AnalysisGroupsPage from "./pages/AnalysisGroupsPage.vue";
import DashboardPage from "./pages/DashboardPage.vue";
import DeletePreviewPage from "./pages/DeletePreviewPage.vue";
import GroupDetailPage from "./pages/GroupDetailPage.vue";
import MetadataIssuesPage from "./pages/MetadataIssuesPage.vue";
import RulesPage from "./pages/RulesPage.vue";
import SettingsSyncPage from "./pages/SettingsSyncPage.vue";

const routes = [
  { path: "/", redirect: "/dashboard" },
  { path: "/dashboard", name: "dashboard", component: DashboardPage },
  { path: "/settings-sync", name: "settings-sync", component: SettingsSyncPage },
  { path: "/analysis-groups", name: "analysis-groups", component: AnalysisGroupsPage },
  { path: "/metadata-issues", name: "metadata-issues", component: MetadataIssuesPage },

  // Legacy/fallback pages kept for backward compatibility.
  { path: "/rules", name: "rules", component: RulesPage },
  { path: "/analysis-groups/:groupId", name: "group-detail", component: GroupDetailPage, props: true },
  { path: "/delete-preview", name: "delete-preview", component: DeletePreviewPage },
];

export default createRouter({
  history: createWebHistory(),
  routes,
});
