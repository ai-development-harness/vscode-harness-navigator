import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import { ARTIFACT_DIAGNOSTIC_MESSAGES } from '../../src/projectModel/artifactIndex';
import { VIEW_MESSAGE_VALUES } from '../../src/views/viewMessages';

const here = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(here, '../..');

function readJsonBundle(relativePath: string): Record<string, string> {
  const raw = readFileSync(path.join(repoRoot, relativePath), 'utf8');
  const parsed: unknown = JSON.parse(raw);
  assert.equal(typeof parsed, 'object');
  assert.ok(parsed !== null);
  return parsed as Record<string, string>;
}

const packageNlsEn = readJsonBundle('package.nls.json');
const packageNlsRu = readJsonBundle('package.nls.ru.json');
const bundleL10nEn = readJsonBundle('l10n/bundle.l10n.json');
const bundleL10nRu = readJsonBundle('l10n/bundle.l10n.ru.json');

test('en/ru bundles package.nls имеют идентичный набор ключей', () => {
  assert.deepEqual(Object.keys(packageNlsRu).sort(), Object.keys(packageNlsEn).sort());
});

test('русский runtime bundle содержит только ключи из English fallback bundle', () => {
  for (const key of Object.keys(bundleL10nRu)) {
    assert.ok(key in bundleL10nEn, `русский ключ "${key}" отсутствует в English fallback bundle`);
  }
});

test('ни одно значение bundle не пустое', () => {
  for (const bundle of [packageNlsEn, packageNlsRu, bundleL10nEn, bundleL10nRu]) {
    for (const [key, value] of Object.entries(bundle)) {
      assert.ok(value.length > 0, `key "${key}" has an empty value`);
    }
  }
});

test('ключи диагностик артефактов присутствуют в обоих runtime bundle', () => {
  for (const key of ARTIFACT_DIAGNOSTIC_MESSAGES) {
    assert.ok(bundleL10nEn[key] !== undefined, `English key: ${key}`);
    assert.ok(bundleL10nRu[key] !== undefined, `Russian key: ${key}`);
  }
});

test('ключи Artifacts/Focus View и Go to Artifact присутствуют в обоих runtime bundle', () => {
  for (const key of VIEW_MESSAGE_VALUES) {
    assert.ok(bundleL10nEn[key] !== undefined, `English key: ${key}`);
    assert.ok(bundleL10nRu[key] !== undefined, `Russian key: ${key}`);
  }
});

test('fallback ключ существует на английском и намеренно отсутствует в русском bundle', () => {
  const fallbackMessage = 'Harness Navigator localization fallback is active.';
  assert.equal(bundleL10nEn[fallbackMessage], fallbackMessage);
  assert.equal(bundleL10nRu[fallbackMessage], undefined);
});

// Canonical Harness identifiers, enum-значения и command names никогда не
// должны появляться как переводимые значения bundle: это технические
// токены, а не user-facing текст, и они не должны молча локализоваться.
const FORBIDDEN_CANONICAL_PATTERNS: RegExp[] = [
  /\bSTEP-\d+\b/,
  /\bREQ-\d+\b/,
  /\bADR-\d+\b/,
  /\bOQ-\d+\b/,
  /\bPROJECT INIT\b/,
  /\bSTEP (ADD|PLAN|IMPLEMENT|REVIEW|FIX|RUN|AUDIT)\b/,
  /\bGIT (CHECK|COMMIT|PUSH|PR|SYNC)\b/,
  /\bHARNESS UPDATE (CHECK|APPLY)\b/,
];

test('значения bundle не содержат canonical Harness ID, enum-значения или command names', () => {
  for (const bundle of [packageNlsEn, packageNlsRu, bundleL10nEn, bundleL10nRu]) {
    for (const [key, value] of Object.entries(bundle)) {
      for (const pattern of FORBIDDEN_CANONICAL_PATTERNS) {
        assert.doesNotMatch(
          value,
          pattern,
          `bundle value for key "${key}" must not contain canonical token matching ${pattern}`,
        );
      }
    }
  }
});
