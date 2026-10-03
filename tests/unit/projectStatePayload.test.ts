import assert from 'node:assert/strict';
import { test } from 'node:test';
import { parseProjectStatePayload } from '../../src/projectGraph/projectStatePayload';
import { projectStateFixture } from './fixtures/projectState';

test('schema v1 сохраняет supplied nodes, provenance и неизвестные optional fields', () => {
  const payload = projectStateFixture();
  const result = parseProjectStatePayload(payload);
  assert.equal(result.kind, 'valid');
  if (result.kind !== 'valid') return;
  assert.deepEqual(
    result.payload.graph.nodes.map((n) => n.type),
    payload.graph.nodes.map((n) => n.type),
  );
  assert.equal(result.payload.graph.nodes[2]?.metadata.planRemediation, 'STEP PLAN STEP-002');
  assert.deepEqual(result.payload.graph.edges, payload.graph.edges);
  assert.equal(result.payload.graph.edges.length, 7, 'parser не синтезирует reciprocal edge');
  assert.equal(result.payload.integrity, 'degraded');
  assert.deepEqual(result.payload.insights, payload.insights);
  assert.deepEqual(result.payload.sources, payload.sources);
  assert.deepEqual(result.payload.diagnostics, payload.diagnostics);
});

test('schema v1 tolerant к неизвестным optional fields', () => {
  const wire = projectStateFixture();
  const result = parseProjectStatePayload({
    ...wire,
    future: true,
    graph: {
      ...wire.graph,
      nodes: wire.graph.nodes.map((n) => ({
        ...n,
        future: true,
        metadata: { ...n.metadata, future: { optional: true } },
      })),
    },
  });
  assert.equal(result.kind, 'valid');
  if (result.kind === 'valid')
    assert.deepEqual(result.payload.graph.nodes[0]?.metadata.future, { optional: true });
});

test('BLOCKED response не превращается в ready graph', () => {
  const result = parseProjectStatePayload({ ...projectStateFixture(), status: 'BLOCKED' });
  assert.equal(result.kind, 'invalid');
  if (result.kind === 'invalid') assert.equal(result.reason, 'blocked');
});

test('malformed и future schema fail-safe без fallback', () => {
  const payload = projectStateFixture();
  assert.deepEqual(parseProjectStatePayload({ ...payload, schemaVersion: 2 }), {
    kind: 'invalid',
    reason: 'unsupportedSchema',
  });
  assert.deepEqual(parseProjectStatePayload({ ...payload, graph: { nodes: [{}], edges: [] } }), {
    kind: 'invalid',
    reason: 'malformed',
  });
});

test('пустой валидный graph не подменяется ArtifactIndex', () => {
  assert.equal(
    parseProjectStatePayload({ ...projectStateFixture(), graph: { nodes: [], edges: [] } }).kind,
    'valid',
  );
});
