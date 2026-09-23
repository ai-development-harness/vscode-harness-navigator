import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { ArtifactIndex } from '../../src/projectModel/artifactIndex';
import type { ValidProjectState } from '../../src/projectModel/projectState';
import { buildRelations } from '../../src/navigation/relationsService';
import { buildCompletionModels, buildHoverModel } from '../../src/navigation/navigationViewModel';

function state(root: string): ValidProjectState {
  return {
    kind: 'valid',
    workspaceRoot: root,
    release: '0.6.0',
    configuredPaths: {
      taskDirectory: 'planning/tasks',
      projectOverview: 'docs/PROJECT.md',
      requirements: 'docs/requirements',
      adrDirectory: 'docs/adr',
      architecture: 'docs/architecture.md',
      openQuestions: 'docs/open-questions',
      openQuestionsIndex: 'docs/OPEN_QUESTIONS.md',
      roadmap: 'planning/PLAN.md',
      status: 'planning/STATUS.md',
    },
    diagnostic: {
      category: 'ValidHarnessProject',
      message: 'Harness manifest is valid.',
      messageArguments: [],
      detail: '',
    },
  };
}

function build(files: Record<string, string>): { root: string; index: ArtifactIndex } {
  const root = mkdtempSync(path.join(tmpdir(), 'navigator-relations-'));
  for (const [relative, content] of Object.entries(files)) {
    mkdirSync(path.dirname(path.join(root, relative)), { recursive: true });
    writeFileSync(path.join(root, relative), content);
  }
  const index = new ArtifactIndex();
  index.rebuild(state(root));
  return { root, index };
}

const doc = (id: string, fields = '') => `---\nschema: 1\nid: ${id}\n${fields}---\n\n# ${id} — T\n`;

test('outgoing, incoming, backlinks и dangling relations', () => {
  const { root, index } = build({
    'planning/tasks/STEP-001.md': doc('STEP-001', 'requirements:\n  - REQ-001\n  - REQ-404\n'),
    'docs/requirements/REQ-001.md': doc('REQ-001'),
    'docs/guides/usage.md': 'REQ-001\n',
  });
  try {
    const step = buildRelations(index, 'STEP-001');
    assert.deepEqual(
      step?.outgoing.map((item) => [item.id, item.unresolved]),
      [
        ['REQ-001', false],
        ['REQ-404', true],
      ],
    );
    assert.equal(step?.outgoing[1]?.file, undefined);
    assert.ok(step?.outgoing[0]?.range !== undefined);
    const req = buildRelations(index, 'REQ-001');
    assert.deepEqual(
      req?.incoming.map((item) => item.id),
      ['STEP-001'],
    );
    // mentions = тот же referencesTo без declaration
    const mentionCount = req?.mentions.reduce((sum, group) => sum + group.references.length, 0);
    assert.equal(mentionCount, index.referencesTo('REQ-001', false).length);
    assert.equal(buildRelations(index, 'REQ-404'), undefined);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test('multi-root: индексы root не смешиваются', () => {
  const first = build({ 'docs/requirements/REQ-001.md': doc('REQ-001') });
  const second = build({ 'docs/requirements/REQ-002.md': doc('REQ-002') });
  try {
    assert.equal(buildRelations(first.index, 'REQ-002'), undefined);
    assert.equal(buildRelations(second.index, 'REQ-001'), undefined);
    assert.ok(buildRelations(second.index, 'REQ-002') !== undefined);
  } finally {
    rmSync(first.root, { recursive: true, force: true });
    rmSync(second.root, { recursive: true, force: true });
  }
});

test('view-model hover и completion', () => {
  const { root, index } = build({
    'docs/requirements/REQ-001.md': doc('REQ-001', 'status: draft\n'),
    'docs/requirements/REQ-010.md': doc('REQ-010'),
    'planning/tasks/STEP-001.md': doc('STEP-001'),
  });
  try {
    const req = index.get('REQ-001');
    assert.ok(req);
    assert.deepEqual(
      { ...buildHoverModel(req, 3) },
      {
        id: 'REQ-001',
        title: 'T',
        kind: 'REQ',
        status: 'draft',
        outgoing: 0,
        incoming: 0,
        mentions: 3,
      },
    );
    const models = buildCompletionModels(index.artifactIds(), (id) => index.get(id), 'REQ-');
    assert.deepEqual(
      models.map((item) => item.id),
      ['REQ-001', 'REQ-010'],
    );
    assert.deepEqual(
      buildCompletionModels(index.artifactIds(), (id) => index.get(id), 'REQ-01').map((i) => i.id),
      ['REQ-010'],
    );
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});
