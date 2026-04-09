import fs from "node:fs";
import path from "node:path";

const root = path.resolve(process.cwd(), "src");
const localePath = path.resolve(root, "i18n/locales/zh-CN.json");

function walk(dir) {
  const out = [];
  for (const ent of fs.readdirSync(dir, { withFileTypes: true })) {
    if (ent.name === "i18n") continue;
    const full = path.join(dir, ent.name);
    if (ent.isDirectory()) out.push(...walk(full));
    else if (/\.(vue|js)$/.test(ent.name)) out.push(full);
  }
  return out;
}

function flatten(obj, prefix = "") {
  const out = new Set();
  for (const [k, v] of Object.entries(obj || {})) {
    const key = prefix ? `${prefix}.${k}` : k;
    if (v && typeof v === "object" && !Array.isArray(v)) {
      for (const sub of flatten(v, key)) out.add(sub);
    } else {
      out.add(key);
    }
  }
  return out;
}

const locale = JSON.parse(fs.readFileSync(localePath, "utf8"));
const localeKeys = flatten(locale);
const files = walk(root);

const tRegex = /\bt\(\s*['\"]([^'\"]+)['\"]/g;
const usedKeys = new Set();
const hardcodedCJK = [];

for (const file of files) {
  const src = fs.readFileSync(file, "utf8");
  let m;
  while ((m = tRegex.exec(src)) !== null) {
    usedKeys.add(m[1]);
  }

  const lines = src.split(/\r?\n/);
  lines.forEach((line, idx) => {
    if (line.includes("$t(") || line.includes("t(")) return;
    if (/\p{Script=Han}/u.test(line) && !line.trim().startsWith("//")) {
      hardcodedCJK.push(`${path.relative(process.cwd(), file)}:${idx + 1}: ${line.trim()}`);
    }
  });
}

const missing = [...usedKeys].filter((k) => !localeKeys.has(k)).sort();
const unused = [...localeKeys].filter((k) => !usedKeys.has(k)).sort();

let failed = false;
if (missing.length) {
  failed = true;
  console.error("[i18n] Missing locale keys:");
  for (const k of missing) console.error(`  - ${k}`);
}

if (hardcodedCJK.length) {
  failed = true;
  console.error("[i18n] Possible hardcoded UI strings (CJK):");
  for (const row of hardcodedCJK.slice(0, 120)) console.error(`  - ${row}`);
  if (hardcodedCJK.length > 120) console.error(`  ... and ${hardcodedCJK.length - 120} more`);
}

if (unused.length) {
  console.warn("[i18n] Unused locale keys:");
  for (const k of unused.slice(0, 120)) console.warn(`  - ${k}`);
  if (unused.length > 120) console.warn(`  ... and ${unused.length - 120} more`);
}

if (failed) process.exit(1);
console.log("[i18n] check passed.");
