#!/usr/bin/env node
/**
 * Generate the OpenUI Lang system prompt from the component spec.
 *
 * Reads `src/openui/generated/component-spec.json` (produced by `openui
 * generate --json-schema`) and writes a single prompt file to:
 *
 *   src/openui/generated/system.txt
 *
 * Also copied to the backend at
 *   ../agent-studio-backend/app/services/openui_prompts/system.txt
 * so FastAPI can load it without reaching across the frontend bundle.
 *
 * Runs as `npm run openui:prompts` after `npm run openui:spec`.
 */

import { generatePrompt } from '@openuidev/lang-core';
import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import promptOptions from '../src/openui/prompt-options.mjs';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const FRONTEND_OUT = path.resolve(__dirname, '..', 'src', 'openui', 'generated');
const BACKEND_OUT = path.resolve(
  __dirname,
  '..',
  '..',
  'agent-studio-backend',
  'app',
  'services',
  'openui_prompts',
);

const SPEC_PATH = path.join(FRONTEND_OUT, 'component-spec.json');

if (!fs.existsSync(SPEC_PATH)) {
  console.error(
    `[openui] component-spec.json not found at ${SPEC_PATH}. ` +
      'Run `npm run openui:spec` first.',
  );
  process.exit(1);
}

const componentSpec = JSON.parse(fs.readFileSync(SPEC_PATH, 'utf-8'));
const componentSpecHash = crypto
  .createHash('sha256')
  .update(JSON.stringify(componentSpec))
  .digest('hex');

const rawPrompt = generatePrompt({
  ...componentSpec,
  preamble: promptOptions.preamble,
  toolCalls: false,
  bindings: false,
  inlineMode: false,
  editMode: false,
  additionalRules: promptOptions.additionalRules,
  examples: promptOptions.examples,
});

// lang-core injects a generative-playground rule that contradicts this
// deterministic JSON-to-OpenUI translator ("generate realistic/plausible
// data"). We must only ever render facts present in the source JSON, so strip
// it. The assertion below fails the build loudly if upstream changes the
// wording, so this never silently regresses.
const CONTRADICTORY_DATA_RULE = /generate realistic\/plausible data/i;
const prompt = rawPrompt
  .split('\n')
  .filter((line) => !CONTRADICTORY_DATA_RULE.test(line))
  .join('\n');

if (CONTRADICTORY_DATA_RULE.test(prompt)) {
  throw new Error(
    '[openui] Generated prompt still contains the contradictory plausible-data ' +
      'rule. Update the strip filter in generate-openui-prompt.mjs.',
  );
}

const promptHash = crypto.createHash('sha256').update(prompt).digest('hex');

fs.mkdirSync(FRONTEND_OUT, { recursive: true });
fs.mkdirSync(BACKEND_OUT, { recursive: true });

const frontendPath = path.join(FRONTEND_OUT, 'system.txt');
const backendPath = path.join(BACKEND_OUT, 'system.txt');
fs.writeFileSync(frontendPath, prompt, 'utf-8');
fs.writeFileSync(backendPath, prompt, 'utf-8');
console.log(`[openui] wrote system.txt (${prompt.length} chars)`);

// Remove legacy flavor files if they linger from a previous build so the
// loader can't accidentally pick a stale flavor.
for (const legacy of ['base.txt', 'with_tools.txt', 'with_edit_mode.txt']) {
  for (const dir of [FRONTEND_OUT, BACKEND_OUT]) {
    const stale = path.join(dir, legacy);
    if (fs.existsSync(stale)) fs.rmSync(stale);
  }
}

const manifest = {
  generatedAt: new Date().toISOString(),
  prompt: 'system.txt',
  componentCount: Object.keys(componentSpec.components ?? {}).length,
  componentSpecHash,
  promptHash,
};
fs.writeFileSync(
  path.join(FRONTEND_OUT, 'manifest.json'),
  JSON.stringify(manifest, null, 2),
);
fs.writeFileSync(
  path.join(BACKEND_OUT, 'manifest.json'),
  JSON.stringify(manifest, null, 2),
);

console.log(`[openui] copied system.txt to backend at ${BACKEND_OUT}`);
