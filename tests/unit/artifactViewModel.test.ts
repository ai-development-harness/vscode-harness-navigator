import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  ARTIFACT_KIND_ORDER,
  SORT_ORDERS,
  buildQuickPickCandidates,
  clearFilters,
  computeEmptyState,
  filterArtifacts,
  groupArtifacts,
  isFilterActive,
  matchesFilter,
  selectFocusArtifacts,
  sortArtifacts,
  type ArtifactFilterState,
} from '../../src/views/artifactViewModel';
import type { Artifact, ArtifactKind } from '../../src/projectModel/artifactIndex';

function artifact(overrides: Partial<Artifact> & { id: string; kind: ArtifactKind }): Artifact {
  return {
    title: `${overrides.id} title`,
    status: undefined,
    file: `/root/${overrides.id}.md`,
    metadata: {},
    outgoingRelations: [],
    incomingRelations: [],
    ...overrides,
  };
}

test('groupArtifacts группирует в фиксированном порядке STEP/REQ/ADR/OQ', () => {
  const artifacts = [
    artifact({ id: 'OQ-002', kind: 'OQ' }),
    artifact({ id: 'ADR-002', kind: 'ADR' }),
    artifact({ id: 'REQ-002', kind: 'REQ' }),
    artifact({ id: 'STEP-002', kind: 'STEP' }),
  ];
  const groups = groupArtifacts(artifacts, 'id', {});
  assert.deepEqual(
    groups.map((group) => group.kind),
    [...ARTIFACT_KIND_ORDER],
  );
  assert.deepEqual(
    groups.map((group) => group.artifacts.map((item) => item.id)),
    [['STEP-002'], ['REQ-002'], ['ADR-002'], ['OQ-002']],
  );
});

test('groupArtifacts сохраняет пустые группы в выдаче', () => {
  const groups = groupArtifacts([artifact({ id: 'STEP-001', kind: 'STEP' })], 'id', {});
  const kinds = groups.map((group) => group.kind);
  assert.deepEqual(kinds, [...ARTIFACT_KIND_ORDER]);
  const empty = groups.filter((group) => group.kind !== 'STEP');
  assert.ok(empty.every((group) => group.artifacts.length === 0));
});

test('SORT_ORDERS перечисляет все поддерживаемые поля сортировки ровно один раз', () => {
  assert.deepEqual([...SORT_ORDERS].sort(), ['id', 'priority', 'status', 'title'].sort());
});

test('sortArtifacts по id использует локальный порядок сравнения и total order', () => {
  const artifacts = [
    artifact({ id: 'STEP-010', kind: 'STEP' }),
    artifact({ id: 'STEP-002', kind: 'STEP' }),
    artifact({ id: 'STEP-001', kind: 'STEP' }),
  ];
  const sorted = sortArtifacts(artifacts, 'id').map((item) => item.id);
  assert.deepEqual(sorted, ['STEP-001', 'STEP-002', 'STEP-010']);
});

test('sortArtifacts по title сортирует по названию и не мутирует исходный массив', () => {
  const artifacts = [
    artifact({ id: 'STEP-002', kind: 'STEP', title: 'Zeta' }),
    artifact({ id: 'STEP-001', kind: 'STEP', title: 'Alpha' }),
  ];
  const original = [...artifacts];
  const sorted = sortArtifacts(artifacts, 'title').map((item) => item.id);
  assert.deepEqual(sorted, ['STEP-001', 'STEP-002']);
  assert.deepEqual(artifacts, original);
});

test('sortArtifacts по status отправляет отсутствующий status в стабильный tail', () => {
  const artifacts = [
    artifact({ id: 'STEP-003', kind: 'STEP', status: undefined }),
    artifact({ id: 'STEP-002', kind: 'STEP', status: 'in_progress' }),
    artifact({ id: 'STEP-001', kind: 'STEP', status: 'blocked' }),
  ];
  const sorted = sortArtifacts(artifacts, 'status').map((item) => item.id);
  assert.deepEqual(sorted, ['STEP-001', 'STEP-002', 'STEP-003']);
});

test('sortArtifacts по priority ранжирует critical > high > medium > low и отправляет unknown в tail', () => {
  const artifacts = [
    artifact({ id: 'STEP-004', kind: 'STEP', metadata: {} }),
    artifact({ id: 'STEP-003', kind: 'STEP', metadata: { priority: 'low' } }),
    artifact({ id: 'STEP-002', kind: 'STEP', metadata: { priority: 'critical' } }),
    artifact({ id: 'STEP-001', kind: 'STEP', metadata: { priority: 'unknown-value' } }),
  ];
  const sorted = sortArtifacts(artifacts, 'priority').map((item) => item.id);
  assert.deepEqual(sorted, ['STEP-002', 'STEP-003', 'STEP-001', 'STEP-004']);
});

test('sortArtifacts по priority не резолвит untrusted значения в Object.prototype (F-003)', () => {
  // Markdown frontmatter — untrusted workspace input; `priority: toString`
  // (или другое имя из Object.prototype) не должно возвращать унаследованную
  // функцию из PRIORITY_RANK[...] вместо undefined — иначе comparator
  // получает NaN и total/воспроизводимый order ломается.
  const artifacts = [
    artifact({ id: 'STEP-003', kind: 'STEP', metadata: { priority: 'toString' } }),
    artifact({ id: 'STEP-002', kind: 'STEP', metadata: { priority: 'high' } }),
    artifact({ id: 'STEP-004', kind: 'STEP', metadata: { priority: 'constructor' } }),
    artifact({ id: 'STEP-001', kind: 'STEP', metadata: { priority: 'critical' } }),
  ];
  const sorted = sortArtifacts(artifacts, 'priority').map((item) => item.id);
  // Известные priority (critical, high) идут первыми в canonical порядке;
  // prototype-имена ('toString', 'constructor') уходят в стабильный tail,
  // отсортированный по id tiebreak, а не в implementation-defined порядок.
  assert.deepEqual(sorted, ['STEP-001', 'STEP-002', 'STEP-003', 'STEP-004']);
  // Повторный вызов даёт тот же результат — не NaN-comparator с
  // недетерминированным порядком между прогонами.
  assert.deepEqual(
    sortArtifacts(artifacts, 'priority').map((item) => item.id),
    sorted,
  );
});

test('sortArtifacts возвращает total order независимо от исходного порядка (стабильность через id tiebreak)', () => {
  const artifacts = [
    artifact({ id: 'STEP-002', kind: 'STEP', status: 'blocked' }),
    artifact({ id: 'STEP-001', kind: 'STEP', status: 'blocked' }),
  ];
  const sorted = sortArtifacts(artifacts, 'status').map((item) => item.id);
  assert.deepEqual(sorted, ['STEP-001', 'STEP-002']);
});

test('matchesFilter применяется только к STEP: REQ/ADR/OQ всегда проходят', () => {
  const filter: ArtifactFilterState = { status: 'in_progress' };
  const req = artifact({ id: 'REQ-001', kind: 'REQ', status: 'accepted' });
  assert.equal(matchesFilter(req, filter), true);
});

test('matchesFilter фильтрует STEP по status/type/priority/phase независимо', () => {
  const step = artifact({
    id: 'STEP-001',
    kind: 'STEP',
    status: 'in_progress',
    metadata: { type: 'implementation', priority: 'high', phase: 'workspace-ui' },
  });
  assert.equal(matchesFilter(step, { status: 'in_progress' }), true);
  assert.equal(matchesFilter(step, { status: 'blocked' }), false);
  assert.equal(matchesFilter(step, { type: 'implementation' }), true);
  assert.equal(matchesFilter(step, { type: 'bugfix' }), false);
  assert.equal(matchesFilter(step, { priority: 'high' }), true);
  assert.equal(matchesFilter(step, { priority: 'low' }), false);
  assert.equal(matchesFilter(step, { phase: 'workspace-ui' }), true);
  assert.equal(matchesFilter(step, { phase: 'other' }), false);
});

test('matchesFilter исключает STEP без status, когда активен status filter', () => {
  const stepWithoutStatus = artifact({ id: 'STEP-001', kind: 'STEP', status: undefined });
  assert.equal(matchesFilter(stepWithoutStatus, { status: 'blocked' }), false);
  // Без активного status filter отсутствие status не исключает STEP.
  assert.equal(matchesFilter(stepWithoutStatus, {}), true);
});

test('matchesFilter требует совпадения по каждому активному filter key одновременно', () => {
  const step = artifact({
    id: 'STEP-001',
    kind: 'STEP',
    status: 'in_progress',
    metadata: { priority: 'high' },
  });
  assert.equal(matchesFilter(step, { status: 'in_progress', priority: 'high' }), true);
  assert.equal(matchesFilter(step, { status: 'in_progress', priority: 'low' }), false);
});

test('filterArtifacts/isFilterActive согласованы с matchesFilter и EMPTY_FILTER', () => {
  assert.equal(isFilterActive({}), false);
  assert.equal(isFilterActive({ status: 'blocked' }), true);
  const artifacts = [
    artifact({ id: 'STEP-001', kind: 'STEP', status: 'blocked' }),
    artifact({ id: 'STEP-002', kind: 'STEP', status: 'planned' }),
  ];
  assert.deepEqual(
    filterArtifacts(artifacts, { status: 'blocked' }).map((item) => item.id),
    ['STEP-001'],
  );
});

test('clearFilters возвращает пустой filter state', () => {
  assert.deepEqual(clearFilters(), {});
});

test('computeEmptyState различает populated/noArtifacts/filteredEmpty', () => {
  const steps = [
    artifact({ id: 'STEP-001', kind: 'STEP', status: 'in_progress' }),
    artifact({ id: 'STEP-002', kind: 'STEP', status: 'blocked' }),
  ];
  assert.equal(computeEmptyState([], {}), 'noArtifacts');
  assert.equal(computeEmptyState([], { status: 'blocked' }), 'noArtifacts');
  assert.equal(computeEmptyState(steps, {}), 'populated');
  // Активный filter, который реально оставляет совпадения — 'populated', а
  // не 'filteredEmpty': computeEmptyState фактически фильтрует переданные
  // artifacts, а не просто проверяет "есть ли активный filter key"
  // (см. её doc comment — единственный источник истины для этого расчёта).
  assert.equal(computeEmptyState(steps, { status: 'blocked' }), 'populated');
  assert.equal(computeEmptyState(steps, { status: 'cancelled' }), 'filteredEmpty');
});

test('computeEmptyState игнорирует filter для не-STEP artifacts, как matchesFilter', () => {
  const artifacts = [artifact({ id: 'REQ-001', kind: 'REQ' })];
  assert.equal(computeEmptyState(artifacts, { status: 'blocked' }), 'populated');
});

test('selectFocusArtifacts отбирает in_progress/blocked STEP и open OQ, в порядке id', () => {
  const artifacts = [
    artifact({ id: 'STEP-003', kind: 'STEP', status: 'in_progress' }),
    artifact({ id: 'STEP-001', kind: 'STEP', status: 'in_progress' }),
    artifact({ id: 'STEP-002', kind: 'STEP', status: 'blocked' }),
    artifact({ id: 'STEP-004', kind: 'STEP', status: 'completed' }),
    artifact({ id: 'OQ-002', kind: 'OQ', status: 'open' }),
    artifact({ id: 'OQ-001', kind: 'OQ', status: 'resolved' }),
  ];
  const selection = selectFocusArtifacts(artifacts);
  assert.deepEqual(
    selection.activeSteps.map((item) => item.id),
    ['STEP-001', 'STEP-003'],
  );
  assert.deepEqual(
    selection.blockedSteps.map((item) => item.id),
    ['STEP-002'],
  );
  assert.deepEqual(
    selection.openQuestions.map((item) => item.id),
    ['OQ-002'],
  );
});

test('selectFocusArtifacts возвращает пустые группы, если нет ни одного совпадения', () => {
  const artifacts = [artifact({ id: 'STEP-001', kind: 'STEP', status: 'completed' })];
  const selection = selectFocusArtifacts(artifacts);
  assert.deepEqual(selection.activeSteps, []);
  assert.deepEqual(selection.blockedSteps, []);
  assert.deepEqual(selection.openQuestions, []);
});

test('buildQuickPickCandidates не заполняет rootName для единственного root', () => {
  const candidates = buildQuickPickCandidates([
    { rootName: 'solo', artifacts: [artifact({ id: 'STEP-001', kind: 'STEP' })] },
  ]);
  assert.equal(candidates.length, 1);
  assert.equal(candidates[0]?.rootName, undefined);
});

test('buildQuickPickCandidates: один из нескольких roots без артефактов не ломает выдачу других roots', () => {
  const candidates = buildQuickPickCandidates([
    { rootName: 'empty-root', artifacts: [] },
    { rootName: 'populated-root', artifacts: [artifact({ id: 'STEP-001', kind: 'STEP' })] },
  ]);
  assert.deepEqual(
    candidates.map((candidate) => [candidate.rootName, candidate.artifact.id]),
    [['populated-root', 'STEP-001']],
  );
});

test('groupArtifacts на пустом массиве artifacts (root без артефактов) возвращает все группы пустыми', () => {
  const groups = groupArtifacts([], 'id', {});
  assert.deepEqual(
    groups.map((group) => group.kind),
    [...ARTIFACT_KIND_ORDER],
  );
  assert.ok(groups.every((group) => group.artifacts.length === 0));
});

test('buildQuickPickCandidates заполняет rootName и сохраняет id-порядок при нескольких roots', () => {
  const candidates = buildQuickPickCandidates([
    {
      rootName: 'b-root',
      artifacts: [
        artifact({ id: 'STEP-002', kind: 'STEP' }),
        artifact({ id: 'STEP-001', kind: 'STEP' }),
      ],
    },
    { rootName: 'a-root', artifacts: [artifact({ id: 'REQ-001', kind: 'REQ' })] },
  ]);
  assert.deepEqual(
    candidates.map((candidate) => [candidate.rootName, candidate.artifact.id]),
    [
      ['b-root', 'STEP-001'],
      ['b-root', 'STEP-002'],
      ['a-root', 'REQ-001'],
    ],
  );
});
