import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
  filterDependencyGraph,
  presentDependencyGraph,
} from '../../src/projectGraph/dependencyGraphPresentation';
import { parseProjectStatePayload } from '../../src/projectGraph/projectStatePayload';
import { projectStateFixture } from './fixtures/projectState';

function snapshot() {
  const result = parseProjectStatePayload(projectStateFixture());
  if (result.kind !== 'valid') throw new Error('fixture must parse');
  return { kind: 'ready' as const, payload: result.payload };
}

test('presentation сохраняет supplied diagnostics semantics и Longest dependency chain', () => {
  const model = presentDependencyGraph(snapshot());
  assert.equal(model.nodes.find((n) => n.id === 'STEP-002')?.status, 'blocked');
  assert.deepEqual(model.longestDependencyChain, ['STEP-002', 'STEP-001']);
  assert.equal(model.edges.length, 7);
});

test('STEP dependencies mode оставляет только STEP и depends_on', () => {
  const model = filterDependencyGraph(presentDependencyGraph(snapshot()), {
    stepDependencies: true,
  });
  assert.deepEqual(
    model.nodes.map((node) => node.id),
    ['STEP-001', 'STEP-002'],
  );
  assert.deepEqual(
    model.edges.map((edge) => edge.type),
    ['depends_on', 'depends_on'],
  );
});

test('фильтр типа оставляет только рёбра между видимыми узлами', () => {
  const model = filterDependencyGraph(presentDependencyGraph(snapshot()), {
    nodeKinds: ['REQ', 'STEP'],
  });
  const ids = new Set(model.nodes.map((n) => n.id));
  assert.ok(model.nodes.every((n) => ['REQ', 'STEP'].includes(n.kind)));
  assert.ok(model.edges.every((e) => ids.has(e.from) && ids.has(e.to)));
});

test('status/relation filters не создают lifecycle conclusions', () => {
  const model = filterDependencyGraph(presentDependencyGraph(snapshot()), {
    statuses: ['blocked'],
  });
  assert.deepEqual(
    model.nodes.map((n) => n.id),
    ['STEP-002'],
  );
  assert.equal(model.edges.length, 0);
  const relations = filterDependencyGraph(presentDependencyGraph(snapshot()), {
    relations: ['reviews'],
  });
  assert.equal(relations.edges.length, 1);
});
