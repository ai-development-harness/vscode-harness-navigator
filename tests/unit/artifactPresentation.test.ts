import assert from 'node:assert/strict';
import { test } from 'node:test';
import { artifactPresentation } from '../../src/views/artifactPresentation';
import type { Artifact, ArtifactKind } from '../../src/projectModel/artifactIndex';

function artifact(
  kind: ArtifactKind,
  status: string | undefined,
  metadata: Readonly<Record<string, unknown>> = {},
): Artifact {
  return {
    id: `${kind}-001`,
    title: 'Тестовый артефакт',
    kind,
    status,
    file: `/workspace/${kind}-001.md`,
    metadata,
    outgoingRelations: [],
    incomingRelations: [],
  };
}

test('artifactPresentation покрывает полную semantic matrix STEP, REQ и ADR', () => {
  const cases: readonly [Artifact, string, string][] = [
    [artifact('STEP', 'planned'), 'circle-large-outline', 'editorInfo.foreground'],
    [artifact('STEP', 'in_progress'), 'sync~spin', 'editorInfo.foreground'],
    [artifact('STEP', 'blocked'), 'circle-slash', 'editorError.foreground'],
    [artifact('STEP', 'completed'), 'pass-filled', 'testing.iconPassed'],
    [artifact('STEP', 'deferred'), 'clock', 'editorWarning.foreground'],
    [artifact('STEP', 'cancelled'), 'close', 'disabledForeground'],
    [artifact('REQ', undefined, { priority: 'critical' }), 'flame', 'editorError.foreground'],
    [artifact('REQ', undefined, { priority: 'high' }), 'arrow-up', 'editorWarning.foreground'],
    [artifact('REQ', undefined, { priority: 'medium' }), 'dash', 'editorInfo.foreground'],
    [artifact('REQ', undefined, { priority: 'low' }), 'arrow-down', 'disabledForeground'],
    [artifact('ADR', 'proposed'), 'lightbulb', 'editorWarning.foreground'],
    [artifact('ADR', 'accepted'), 'check', 'testing.iconPassed'],
    [artifact('ADR', 'superseded'), 'history', 'disabledForeground'],
    [artifact('ADR', 'rejected'), 'circle-slash', 'editorError.foreground'],
  ];

  for (const [input, iconId, colorId] of cases) {
    assert.deepEqual(artifactPresentation(input), { iconId, colorId });
  }
});

test('artifactPresentation возвращает neutral fallback для отсутствующих и некорректных metadata', () => {
  const cases: readonly [Artifact, string][] = [
    [artifact('STEP', undefined), 'checklist'],
    [artifact('STEP', 'unknown'), 'checklist'],
    [artifact('REQ', undefined), 'bookmark'],
    [artifact('REQ', undefined, { priority: 'unknown' }), 'bookmark'],
    [artifact('REQ', undefined, { priority: 1 }), 'bookmark'],
    [artifact('ADR', undefined), 'book'],
    [artifact('ADR', 'unknown'), 'book'],
    [artifact('OQ', 'open'), 'question'],
  ];

  for (const [input, iconId] of cases) {
    assert.deepEqual(artifactPresentation(input), { iconId, colorId: undefined });
  }
});
