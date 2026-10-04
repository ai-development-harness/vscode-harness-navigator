import assert from 'node:assert/strict';
import { test } from 'node:test';
import { layoutDependencyGraph } from '../../src/projectGraph/dependencyGraphLayout';

test('layered layout детерминирован и сохраняет MISSING/isolated nodes', () => {
  const graph = {
    nodes: [
      { id: 'MISSING:X', kind: 'MISSING' as const, metadata: {} },
      { id: 'STEP-001', kind: 'STEP' as const, metadata: {} },
      { id: 'PROJECT', kind: 'PROJECT' as const, metadata: {} },
    ],
    edges: [],
  };
  const first = layoutDependencyGraph(graph),
    second = layoutDependencyGraph({ nodes: [...graph.nodes].reverse(), edges: [] });
  assert.deepEqual(first, second);
  assert.ok(first.nodes.some((node) => node.lane === 'MISSING'));
  assert.equal(new Set(first.nodes.map((node) => `${node.x}:${node.y}`)).size, first.nodes.length);
});

test('layout сохраняет direction, provenance, reciprocal и self edge', () => {
  const graph = {
    nodes: [
      { id: 'STEP-001', kind: 'STEP' as const, metadata: {} },
      { id: 'STEP-002', kind: 'STEP' as const, metadata: {} },
    ],
    edges: [
      { from: 'STEP-001', to: 'STEP-002', type: 'depends_on' as const, declaredBy: ['STEP-001'] },
      { from: 'STEP-002', to: 'STEP-001', type: 'depends_on' as const, declaredBy: [] },
      { from: 'STEP-001', to: 'STEP-001', type: 'depends_on' as const, declaredBy: [] },
    ],
  };
  const layout = layoutDependencyGraph(graph);
  assert.equal(layout.edges[0]?.reciprocal, true);
  assert.equal(layout.edges[0]?.declaredBy[0], 'STEP-001');
  assert.equal(layout.edges[2]?.self, true);
});
