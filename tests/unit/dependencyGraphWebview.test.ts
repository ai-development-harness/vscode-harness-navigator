import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
  dependencyGraphHtml,
  isDependencyGraphMessage,
  GRAPH_LABELS,
} from '../../src/projectGraph/dependencyGraphWebview';
import { readFileSync } from 'node:fs';
import { PROJECT_STATE_ERROR_MESSAGES } from '../../src/projectGraph/projectStateErrors';

test('HTML имеет nonce CSP/theme variables/SVG и не интерполирует payload как HTML', () => {
  const html = dependencyGraphHtml(
    { cspSource: 'vscode-webview:' },
    {
      state: 'error',
      error: '</script><img src=x onerror=alert(1)>',
      nodes: [],
      edges: [],
      longestDependencyChain: undefined,
    },
  );
  assert.match(html, /style-src 'nonce-/u);
  assert.match(html, /script-src 'nonce-/u);
  assert.match(html, /<svg/u);
  assert.match(html, /--vscode-focusBorder/u);
  assert.doesNotMatch(html, /<img src=x/u);
  assert.doesNotMatch(html, /innerHTML/u);
  assert.match(html, /textContent/u);
  assert.match(html, /STEP dependencies/u);
});

test('message allowlist отклоняет произвольные пути, команды и malformed ID', () => {
  for (const value of [
    null,
    [],
    { type: 'exec', command: 'shell' },
    { type: 'open', path: '/tmp/a' },
    { type: 'select', id: '' },
    { type: 'select', id: 1 },
  ])
    assert.equal(isDependencyGraphMessage(value), false);
  for (const type of ['reset', 'refresh', 'fit'])
    assert.equal(isDependencyGraphMessage({ type }), true);
  assert.equal(isDependencyGraphMessage({ type: 'open', id: 'STEP-001' }), true);
});

test('все подписи графа локализованы RU/EN', () => {
  const en = JSON.parse(readFileSync('l10n/bundle.l10n.json', 'utf8')) as Record<string, string>;
  const ru = JSON.parse(readFileSync('l10n/bundle.l10n.ru.json', 'utf8')) as Record<string, string>;
  for (const label of [
    ...Object.values(GRAPH_LABELS),
    ...Object.values(PROJECT_STATE_ERROR_MESSAGES),
  ]) {
    assert.ok(en[label], label);
    assert.ok(ru[label], label);
  }
});
