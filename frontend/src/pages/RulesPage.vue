<script setup>
import { onMounted, ref } from "vue";
import { api } from "../api/client";

const loading = ref(false);
const saving = ref(false);
const message = ref("");
const error = ref("");
const rules = ref([]);

const draggedRuleId = ref("");
const showPriorityModal = ref(false);
const editingRuleIndex = ref(-1);
const modalPriority = ref([]);
const draggedPriorityIndex = ref(-1);

const RULE_LABELS = {
  subtitle: "Subtitle",
  runtime: "Runtime",
  effect: "Effect",
  resolution: "Resolution",
  bit_depth: "Bit Depth",
  bitrate: "Bitrate",
  codec: "Codec",
  filesize: "File Size",
  date_added: "Date Added",
  frame_rate: "Frame Rate",
};

const CATEGORICAL_CHOICES = {
  codec: ["AV1", "HEVC", "H.264", "VP9"],
  resolution: ["4K", "1080p", "720p", "480p"],
  effect: ["DoVi P8", "DoVi P7", "DoVi P5", "DoVi (Other)", "HDR10+", "HDR", "SDR"],
  subtitle: ["Chinese", "None"],
};

function isCategoricalRule(rule) { return Array.isArray(CATEGORICAL_CHOICES[rule.id]); }

function normalizeRule(rule, index) {
  const normalized = {
    id: rule.id,
    enabled: !!rule.enabled,
    order: Number(rule.order || index + 1),
    priority: rule.priority,
  };

  if (isCategoricalRule(normalized)) {
    const choices = CATEGORICAL_CHOICES[normalized.id];
    const incoming = Array.isArray(rule.priority) ? rule.priority : [];
    const ordered = [];
    for (const value of incoming) {
      if (choices.includes(value) && !ordered.includes(value)) ordered.push(value);
    }
    for (const choice of choices) {
      if (!ordered.includes(choice)) ordered.push(choice);
    }
    normalized.priority = ordered;
  }
  return normalized;
}

function resetOrders() { rules.value.forEach((rule, i) => { rule.order = i + 1; }); }
function ruleLabel(ruleId) { return RULE_LABELS[ruleId] || ruleId; }

function onDragStart(event, ruleId) {
  const el = event.target;
  if (el.closest("button") || el.closest("input") || el.closest("label")) {
    event.preventDefault();
    return;
  }
  draggedRuleId.value = ruleId;
}

function onDropRule(targetRuleId) {
  if (!draggedRuleId.value || draggedRuleId.value === targetRuleId) {
    draggedRuleId.value = "";
    return;
  }
  const from = rules.value.findIndex((r) => r.id === draggedRuleId.value);
  const to = rules.value.findIndex((r) => r.id === targetRuleId);
  if (from < 0 || to < 0) {
    draggedRuleId.value = "";
    return;
  }
  const [moved] = rules.value.splice(from, 1);
  rules.value.splice(to, 0, moved);
  resetOrders();
  draggedRuleId.value = "";
}

function openPriorityModal(index) {
  const rule = rules.value[index];
  if (!rule || !isCategoricalRule(rule)) return;
  editingRuleIndex.value = index;
  modalPriority.value = [...rule.priority];
  showPriorityModal.value = true;
}
function closePriorityModal() { showPriorityModal.value = false; editingRuleIndex.value = -1; modalPriority.value = []; }
function onPriorityDragStart(index) { draggedPriorityIndex.value = index; }
function onPriorityDrop(targetIndex) {
  const from = draggedPriorityIndex.value;
  if (from < 0 || from === targetIndex) {
    draggedPriorityIndex.value = -1;
    return;
  }
  const [moved] = modalPriority.value.splice(from, 1);
  modalPriority.value.splice(targetIndex, 0, moved);
  draggedPriorityIndex.value = -1;
}
function saveModalPriority() {
  if (editingRuleIndex.value < 0) return;
  rules.value[editingRuleIndex.value].priority = [...modalPriority.value];
  closePriorityModal();
}

async function loadRules() {
  loading.value = true;
  message.value = "";
  error.value = "";
  try {
    const data = await api.getRules();
    const list = Array.isArray(data?.rules) ? data.rules : [];
    rules.value = list.map((rule, index) => normalizeRule(rule, index)).sort((a, b) => a.order - b.order);
    resetOrders();
  } catch (e) {
    error.value = `Failed to load rules: ${e.message}`;
  } finally {
    loading.value = false;
  }
}

async function saveRules() {
  saving.value = true;
  message.value = "";
  error.value = "";
  try {
    resetOrders();
    const payload = { rules: rules.value.map((rule) => ({ id: rule.id, enabled: !!rule.enabled, order: Math.max(1, Number(rule.order || 1)), priority: rule.priority })) };
    const data = await api.putRules(payload);
    const list = Array.isArray(data?.rules) ? data.rules : [];
    rules.value = list.map((rule, index) => normalizeRule(rule, index)).sort((a, b) => a.order - b.order);
    resetOrders();
    message.value = "Rules saved.";
  } catch (e) {
    error.value = `Failed to save rules: ${e.message}`;
  } finally {
    saving.value = false;
  }
}

onMounted(loadRules);
</script>

<template>
  <section class="page">
    <header class="header">
      <h2>Rules</h2>
      <div class="actions">
        <button type="button" @click="loadRules" :disabled="loading">{{ loading ? "Loading..." : "Reload" }}</button>
        <button type="button" @click="saveRules" :disabled="saving || loading">{{ saving ? "Saving..." : "Save Rules" }}</button>
      </div>
    </header>

    <p v-if="message" class="message">{{ message }}</p>
    <p v-if="error" class="error">{{ error }}</p>
    <p v-if="loading">Loading rules...</p>

    <div v-else class="rules-list">
      <article v-for="rule in rules" :key="rule.id" class="rule-card" draggable="true" @dragstart="onDragStart($event, rule.id)" @dragover.prevent @drop="onDropRule(rule.id)">
        <div class="rule-main">
          <span class="drag-handle" title="Drag to reorder">::</span>
          <div>
            <h3>{{ rule.order }}. {{ ruleLabel(rule.id) }}</h3>
            <p class="muted">ID: {{ rule.id }}</p>
          </div>
        </div>

        <div class="rule-actions">
          <label class="switch"><input v-model="rule.enabled" type="checkbox" /><span>Enabled</span></label>
          <button v-if="isCategoricalRule(rule)" class="icon-btn" type="button" title="Edit category priority" draggable="false" @dragstart.stop @click="openPriorityModal(rules.findIndex((x) => x.id === rule.id))">⚙</button>
          <span v-else class="priority-text">Priority: {{ rule.priority }}</span>
        </div>

        <div v-if="isCategoricalRule(rule)" class="chips"><span v-for="tag in rule.priority" :key="`${rule.id}-${tag}`" class="chip">{{ tag }}</span></div>
      </article>
    </div>

    <div v-if="showPriorityModal" class="modal-backdrop" @click.self="closePriorityModal">
      <section class="modal">
        <h3>Edit Priority</h3>
        <p class="muted">Drag to reorder fixed choices.</p>
        <ul class="priority-list">
          <li v-for="(item, index) in modalPriority" :key="item" class="priority-item" draggable="true" @dragstart="onPriorityDragStart(index)" @dragover.prevent @drop="onPriorityDrop(index)">
            <span class="drag-handle">::</span>
            <span>{{ item }}</span>
          </li>
        </ul>
        <div class="modal-actions"><button type="button" @click="closePriorityModal">Cancel</button><button type="button" @click="saveModalPriority">Save</button></div>
      </section>
    </div>
  </section>
</template>

<style scoped>
.page { display: flex; flex-direction: column; gap: 12px; }
.header { display: flex; justify-content: space-between; align-items: center; gap: 12px; }
.actions { display: flex; gap: 8px; }
button, input { font: inherit; }
button { border: 1px solid #334155; background: #334155; color: #fff; border-radius: 8px; padding: 8px 12px; cursor: pointer; }
button:disabled { opacity: 0.6; cursor: not-allowed; }
.rules-list { display: flex; flex-direction: column; gap: 10px; }
.rule-card { background: #fff; border: 1px solid #cbd5e1; border-radius: 10px; padding: 12px; display: flex; flex-direction: column; gap: 10px; }
.rule-main { display: flex; align-items: center; gap: 10px; }
.rule-main h3 { margin: 0; }
.rule-actions { display: flex; align-items: center; gap: 14px; flex-wrap: wrap; }
.icon-btn { width: 30px; height: 30px; padding: 0; border-radius: 999px; display: inline-flex; align-items: center; justify-content: center; }
.switch { display: inline-flex; gap: 6px; align-items: center; }
.drag-handle { font-weight: 700; color: #64748b; cursor: grab; }
.priority-text, .muted { color: #64748b; }
.chips { display: flex; flex-wrap: wrap; gap: 6px; }
.chip { border: 1px solid #bfdbfe; background: #eff6ff; color: #1e3a8a; border-radius: 999px; padding: 2px 8px; font-size: 12px; }
.modal-backdrop { position: fixed; inset: 0; background: rgba(15, 23, 42, 0.45); display: flex; align-items: center; justify-content: center; z-index: 20; }
.modal { width: min(520px, 95vw); background: #fff; border-radius: 12px; border: 1px solid #cbd5e1; padding: 16px; display: flex; flex-direction: column; gap: 10px; }
.priority-list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 6px; }
.priority-item { border: 1px solid #cbd5e1; border-radius: 8px; padding: 8px; display: flex; gap: 8px; align-items: center; background: #f8fafc; }
.modal-actions { display: flex; justify-content: flex-end; gap: 8px; }
.message { color: #166534; }
.error { color: #b91c1c; }
</style>

