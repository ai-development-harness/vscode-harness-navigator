import { test } from 'node:test';
import assert from 'node:assert/strict';
import type { Artifact, ArtifactSnapshot } from '../../src/projectModel/artifactIndex';
import type { ProjectState } from '../../src/projectModel/projectState';
import { buildSummaryModel, EMPTY_COUNTS } from '../../src/views/summaryModel';

function artifact(id: string, status: string | undefined): Artifact {
  const kind = id.split('-')[0] as Artifact['kind'];
  return {
    id,
    title: id,
    kind,
    status,
    file: `/root/${id}.md`,
    metadata: {},
    outgoingRelations: [],
    incomingRelations: [],
  };
}

function valid(root: string): ProjectState {
  return {
    kind: 'valid',
    workspaceRoot: root,
    release: '0.6.0',
    configuredPaths: {} as never,
    diagnostic: {
      category: 'ValidHarnessProject',
      message: 'Harness manifest is valid.',
      messageArguments: [],
      detail: '',
    },
  };
}

const nonHarness: ProjectState = {
  kind: 'nonHarness',
  workspaceRoot: '/plain',
  diagnostic: {
    category: 'NotHarnessProject',
    message: 'Harness manifest is absent.',
    messageArguments: [],
    detail: '',
  },
};

function snapshot(artifacts: Artifact[], diagnostics = 0): ArtifactSnapshot {
  return {
    artifacts,
    references: [],
    diagnostics: Array.from({ length: diagnostics }, () => ({
      category: 'ArtifactParseError' as const,
      message: 'x',
      messageArguments: [],
      detail: '',
    })),
  };
}

test('пустой проект даёт нулевые counts и valid root', () => {
  const model = buildSummaryModel([
    { rootName: 'a', rootKey: 'file:///a', state: valid('/a'), snapshot: snapshot([]) },
  ]);
  assert.deepEqual(model.aggregate, EMPTY_COUNTS);
  assert.equal(model.validRootCount, 1);
  assert.equal(model.roots[0]?.release, '0.6.0');
});

test('смешанные статусы считаются через общий focus selector', () => {
  const model = buildSummaryModel([
    {
      rootName: 'a',
      rootKey: 'file:///a',
      state: valid('/a'),
      snapshot: snapshot(
        [
          artifact('STEP-001', 'in_progress'),
          artifact('STEP-002', 'blocked'),
          artifact('STEP-003', 'planned'),
          artifact('REQ-001', 'active'),
          artifact('ADR-001', 'accepted'),
          artifact('OQ-001', 'open'),
          artifact('OQ-002', 'resolved'),
        ],
        2,
      ),
    },
  ]);
  assert.deepEqual(model.aggregate, {
    steps: 3,
    requirements: 1,
    adrs: 1,
    openQuestions: 1,
    inProgress: 1,
    blocked: 1,
    diagnostics: 2,
  });
});

test('несколько roots суммируются, non-valid root не влияет на aggregate', () => {
  const model = buildSummaryModel([
    {
      rootName: 'a',
      rootKey: 'file:///a',
      state: valid('/a'),
      snapshot: snapshot([artifact('STEP-001', 'in_progress')]),
    },
    {
      rootName: 'b',
      rootKey: 'file:///b',
      state: valid('/b'),
      snapshot: snapshot([artifact('STEP-002', 'in_progress')]),
    },
    { rootName: 'c', rootKey: 'file:///c', state: nonHarness, snapshot: undefined },
  ]);
  assert.equal(model.aggregate.inProgress, 2);
  assert.equal(model.validRootCount, 2);
  const plain = model.roots[2];
  assert.equal(plain?.kind, 'nonHarness');
  assert.equal(plain?.category, 'NotHarnessProject');
  assert.equal(plain?.release, undefined);
  assert.deepEqual(plain?.counts, EMPTY_COUNTS);
});

test('результат не зависит от locale и содержит только числа и canonical значения', () => {
  const inputs = [
    {
      rootName: 'a',
      rootKey: 'file:///a',
      state: valid('/a'),
      snapshot: snapshot([artifact('STEP-001', 'blocked')]),
    },
  ];
  const first = JSON.stringify(buildSummaryModel(inputs));
  const previous = process.env['LANG'];
  process.env['LANG'] = 'ru_RU.UTF-8';
  try {
    assert.equal(JSON.stringify(buildSummaryModel(inputs)), first);
  } finally {
    if (previous === undefined) delete process.env['LANG'];
    else process.env['LANG'] = previous;
  }
});

test('root с одинаковым basename различаются по rootKey', () => {
  const model = buildSummaryModel([
    { rootName: 'app', rootKey: 'file:///a/app', state: valid('/a/app'), snapshot: snapshot([]) },
    { rootName: 'app', rootKey: 'file:///b/app', state: valid('/b/app'), snapshot: snapshot([]) },
  ]);
  assert.deepEqual(
    model.roots.map((root) => root.rootKey),
    ['file:///a/app', 'file:///b/app'],
  );
});
