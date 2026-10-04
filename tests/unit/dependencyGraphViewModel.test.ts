import assert from 'node:assert/strict';
import { test } from 'node:test';
import { presentDependencyGraph } from '../../src/projectGraph/dependencyGraphPresentation';
import {
  defaultGraphFilters,
  graphOverview,
  visibleGraph,
  createGraphViewModel,
} from '../../src/projectGraph/dependencyGraphViewModel';
import { parseProjectStatePayload } from '../../src/projectGraph/projectStatePayload';
import { projectStateFixture } from './fixtures/projectState';
import capturedApi from './fixtures/dependencyGraphApi.json';
import capturedStaleMetadata from './fixtures/dependencyGraphStaleMetadata.json';

function model() {
  const parsed = parseProjectStatePayload(projectStateFixture());
  if (parsed.kind !== 'valid') throw new Error('fixture must parse');
  return presentDependencyGraph({ kind: 'ready', payload: parsed.payload }, 'STEP-002');
}

test('view model хранит полный snapshot при focus и overview берёт supplied summary', () => {
  const graph = model();
  assert.equal(graph.nodes.length, 9);
  assert.equal(graphOverview(graph).artifacts, undefined);
  assert.equal(graphOverview(graph).relationshipCoveragePercent, 75);
  assert.equal(graphOverview({ ...graph, insights: {} }).cycles, undefined);
});

test('presets используют только API ids и не создают цикл или blocker', () => {
  const graph = model();
  const blockers = visibleGraph(graph, { ...defaultGraphFilters(), preset: 'blockers' });
  assert.ok(blockers.nodes.some((node) => node.id === 'STEP-002'));
  const cycles = visibleGraph(graph, { ...defaultGraphFilters(), preset: 'cycles' });
  assert.ok(cycles.nodes.every((node) => node.kind === 'STEP'));
  assert.ok(cycles.edges.every((edge) => edge.type === 'depends_on'));
});

test('search сочетается с filters и exact ID не требует refresh', () => {
  const graph = visibleGraph(model(), {
    ...defaultGraphFilters(),
    search: 'STEP-002',
    statuses: ['blocked'],
  });
  assert.deepEqual(
    graph.nodes.map((node) => node.id),
    ['STEP-002'],
  );
});

/** Fixture сохранён из настоящего schema-v1 API: nodeId blockers и review path/errors не выдумываются UI. */
test('captured schema-v1: numeric summary, actual blockers, diagnostics и structured stale causes', () => {
  const parsed = parseProjectStatePayload(capturedApi);
  assert.equal(parsed.kind, 'valid');
  if (parsed.kind !== 'valid') return;
  const graph = presentDependencyGraph({ kind: 'ready', payload: parsed.payload });
  const tools = createGraphViewModel();
  assert.equal(tools.overview(graph).artifacts, 39);
  assert.notEqual(tools.overview(graph).artifacts, graph.nodes.length);
  assert.equal(tools.overview(graph).invalidReviews, 1);
  const blockers = tools.visible(graph, { ...tools.defaults(), preset: 'blockers' });
  assert.ok(blockers.nodes.some((n) => n.id === 'STEP-019'));
  assert.equal(tools.inspector(graph, 'STEP-019')?.impact, 0);
  const staleGraph = {
    ...graph,
    nodes: graph.nodes.map((n) =>
      n.id === 'STEP-001' ? { ...n, metadata: capturedStaleMetadata } : n,
    ),
  };
  assert.ok(
    tools.inspector(staleGraph, 'STEP-001')?.causes.some((c) => c.includes('PLANNING_CONTEXT')),
  );
  assert.match(tools.inspector(staleGraph, 'STEP-001')?.remediation ?? '', /^STEP PLAN STEP-/u);
  const diagnostic = tools.diagnosticLines(graph).find((d) => d.code === 'INVALID_REVIEW');
  assert.ok(diagnostic?.fields.some((f) => f.key === 'path'));
  assert.ok(diagnostic?.fields.some((f) => f.key === 'errors' && f.value.includes('frontmatter')));
  assert.equal(tools.inspector(graph, 'MISSING:STEP-9999')?.path, undefined);
});

test('все presets и пересечение filters сохраняют только supplied факты', () => {
  const tools = createGraphViewModel();
  const graph = model();
  const supplied = {
    ...graph,
    insights: {
      blockers: [{ nodeId: 'STEP-002', impactCount: 0 }],
      uncoveredRequirements: ['REQ-001'],
      isolatedArtifacts: ['SKILL:1'],
      dependency: { cycles: [['STEP-001', 'STEP-002']], longestChain: ['STEP-001', 'STEP-002'] },
    },
  };
  for (const preset of [
    'full',
    'steps',
    'blockers',
    'cycles',
    'missing',
    'uncovered',
    'isolated',
  ] as const) {
    const view = tools.visible(supplied, { ...tools.defaults(), preset });
    assert.ok(view.nodes.every((n) => graph.nodes.some((actual) => actual.id === n.id)));
    if (preset === 'steps' || preset === 'cycles') {
      assert.ok(view.nodes.every((n) => n.kind === 'STEP'));
      assert.ok(view.edges.every((e) => e.type === 'depends_on'));
    }
    if (preset === 'uncovered')
      assert.deepEqual(
        view.nodes.map((n) => n.id),
        ['REQ-001'],
      );
    if (preset === 'isolated')
      assert.deepEqual(
        view.nodes.map((n) => n.id),
        ['SKILL:1'],
      );
  }
  assert.equal(tools.visible(supplied, { ...tools.defaults(), kinds: [] }).nodes.length, 0);
  assert.equal(tools.visible(supplied, { ...tools.defaults(), relations: [] }).edges.length, 0);
  assert.equal(
    tools.visible(supplied, { ...tools.defaults(), preset: 'steps', search: 'REQ-001' }).nodes
      .length,
    0,
  );
  assert.equal(
    tools.visible(supplied, { ...tools.defaults('STEP-002'), search: 'SKILL:' }).nodes.length,
    0,
  );
  const step = tools.inspector(
    {
      ...graph,
      nodes: graph.nodes.map((n) =>
        n.id !== 'STEP-002'
          ? n
          : {
              ...n,
              metadata: {
                planFreshness: 'fresh',
                planRemediation: 'STEP PLAN STEP-002',
                executionGroups: [
                  { id: 'test', steps: ['a', 'b'], parallel: true, dependsOn: ['base'] },
                ],
              },
            },
      ),
    },
    'STEP-002',
  );
  assert.equal(step?.remediation, undefined);
  assert.deepEqual(step?.groups, [{ id: 'test', count: 2, parallel: true, dependsOn: ['base'] }]);
  assert.equal(
    tools.inspector(
      { ...graph, nodes: graph.nodes.map((n) => ({ ...n, metadata: {} })), insights: {} },
      'STEP-002',
    )?.impact,
    undefined,
  );
});
