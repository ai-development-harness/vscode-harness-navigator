import type { Artifact, ArtifactKind } from '../projectModel/artifactIndex';

/**
 * Vscode-независимая логика представления Artifacts View, Focus View и
 * `Harness: Go to Artifact`. Ни один экспорт этого модуля не импортирует
 * `vscode` во время выполнения (см. `import type` в
 * `lifecycle/disposableRegistry.ts`), поэтому вся группировка/сортировка/
 * фильтрация покрывается обычными `node:test` unit tests без Extension Host.
 * Модуль только читает уже разобранные `Artifact.status`/`Artifact.metadata`
 * из общего `ArtifactIndex.snapshot()` — самостоятельного parsing Markdown
 * здесь нет.
 */

/** Фиксированный порядок групп верхнего уровня Artifacts View. */
export const ARTIFACT_KIND_ORDER: readonly ArtifactKind[] = ['STEP', 'REQ', 'ADR', 'OQ'];

export type SortOrder = 'id' | 'title' | 'status' | 'priority';

export const SORT_ORDERS: readonly SortOrder[] = ['id', 'title', 'status', 'priority'];

/** Canonical machine STEP status enum (`AGENTS.md` §11): closed, не локализуется. */
export const STEP_STATUS_VALUES = [
  'planned',
  'in_progress',
  'blocked',
  'completed',
  'deferred',
  'cancelled',
] as const;

/** Canonical machine STEP type enum (`AGENTS.md` §11): закрытый список, не локализуется. */
export const STEP_TYPE_VALUES = [
  'implementation',
  'bugfix',
  'refactor',
  'research',
  'adr',
  'audit',
  'review',
  'hardening',
  'documentation',
  'release',
] as const;

/** Canonical machine priority enum (`.harness/docs/GLOSSARY.md`): closed set, худший rank — tail. */
export const STEP_PRIORITY_VALUES = ['critical', 'high', 'medium', 'low'] as const;

// `Object.create(null)` — намеренно без прототипа: `priority` приходит из
// untrusted Markdown frontmatter (см. `MAXIMUM_MARKDOWN_SIZE_BYTES` в
// `projectModel/artifactIndex.ts`), и значение вроде `priority: toString`
// не должно резолвиться в унаследованный `Object.prototype.toString` вместо
// `undefined` (что дало бы `NaN` в компараторе и сломало total order).
const PRIORITY_RANK: Readonly<Record<string, number>> = STEP_PRIORITY_VALUES.reduce<
  Record<string, number>
>(
  (rank, value, index) => {
    rank[value] = index;
    return rank;
  },
  Object.create(null) as Record<string, number>,
);
const UNKNOWN_PRIORITY_RANK = STEP_PRIORITY_VALUES.length;

function priorityRank(key: string): number {
  if (!Object.hasOwn(PRIORITY_RANK, key)) return UNKNOWN_PRIORITY_RANK;
  return PRIORITY_RANK[key] ?? UNKNOWN_PRIORITY_RANK;
}

export interface ArtifactFilterState {
  readonly status?: string;
  readonly type?: string;
  readonly priority?: string;
  readonly phase?: string;
}

/** Filter fields, которые действительно поддерживаются (используется `clearFilters`/preferences I/O). */
export const FILTER_FIELDS = ['status', 'type', 'priority', 'phase'] as const;
export type FilterField = (typeof FILTER_FIELDS)[number];

export const EMPTY_FILTER: ArtifactFilterState = {};

export interface ArtifactGroup {
  readonly kind: ArtifactKind;
  readonly artifacts: readonly Artifact[];
}

export interface RootArtifacts {
  readonly rootName: string;
  readonly artifacts: readonly Artifact[];
}

export interface QuickPickCandidate {
  readonly artifact: Artifact;
  /** Задано только когда candidates собраны из нескольких valid roots. */
  readonly rootName: string | undefined;
}

export interface FocusSelection {
  readonly activeSteps: readonly Artifact[];
  readonly blockedSteps: readonly Artifact[];
  readonly openQuestions: readonly Artifact[];
}

export type ArtifactsEmptyState = 'populated' | 'noArtifacts' | 'filteredEmpty';

function metadataString(artifact: Artifact, key: string): string | undefined {
  const value = artifact.metadata[key];
  return typeof value === 'string' ? value : undefined;
}

/** Total order tie-break: по `id`, чтобы каждая сортировка была детерминированной и воспроизводимой. */
function compareWithTiebreak(left: Artifact, right: Artifact, primary: number): number {
  return primary !== 0 ? primary : left.id.localeCompare(right.id);
}

/**
 * Сортирует artifacts по выбранному `SortOrder`. Отсутствующее/неизвестное
 * значение сортируемого поля всегда уходит в стабильный tail (после всех
 * artifacts с известным значением), так что sort остаётся total и
 * воспроизводимым независимо от входного порядка.
 */
export function sortArtifacts(artifacts: readonly Artifact[], order: SortOrder): Artifact[] {
  const copy = [...artifacts];
  switch (order) {
    case 'id':
      return copy.sort((left, right) =>
        compareWithTiebreak(left, right, left.id.localeCompare(right.id)),
      );
    case 'title':
      return copy.sort((left, right) =>
        compareWithTiebreak(left, right, left.title.localeCompare(right.title)),
      );
    case 'status':
      return copy.sort((left, right) => {
        if (left.status === undefined && right.status === undefined)
          return compareWithTiebreak(left, right, 0);
        if (left.status === undefined) return 1;
        if (right.status === undefined) return -1;
        return compareWithTiebreak(left, right, left.status.localeCompare(right.status));
      });
    case 'priority':
      return copy.sort((left, right) => {
        const leftRank = priorityRank(metadataString(left, 'priority') ?? '');
        const rightRank = priorityRank(metadataString(right, 'priority') ?? '');
        return compareWithTiebreak(left, right, leftRank - rightRank);
      });
  }
}

/** Есть ли хотя бы один активный filter key. */
export function isFilterActive(filter: ArtifactFilterState): boolean {
  return FILTER_FIELDS.some((field) => filter[field] !== undefined);
}

/**
 * Фильтрация применяется только к STEP: `status`/`type`/`priority`/`phase`
 * являются machine-полями STEP frontmatter, а не общим контрактом REQ/ADR/OQ.
 * Артефакты остальных kind проходят фильтр без изменений — активный STEP
 * filter не должен незаметно скрывать REQ/ADR/OQ группы Artifacts View.
 */
export function matchesFilter(artifact: Artifact, filter: ArtifactFilterState): boolean {
  if (artifact.kind !== 'STEP') return true;
  if (filter.status !== undefined && artifact.status !== filter.status) return false;
  if (filter.type !== undefined && metadataString(artifact, 'type') !== filter.type) return false;
  if (filter.priority !== undefined && metadataString(artifact, 'priority') !== filter.priority)
    return false;
  if (filter.phase !== undefined && metadataString(artifact, 'phase') !== filter.phase)
    return false;
  return true;
}

export function filterArtifacts(
  artifacts: readonly Artifact[],
  filter: ArtifactFilterState,
): Artifact[] {
  return artifacts.filter((artifact) => matchesFilter(artifact, filter));
}

/** Сбрасывает все поддерживаемые filter keys, не трогая sort order. */
export function clearFilters(): ArtifactFilterState {
  return EMPTY_FILTER;
}

/**
 * Группирует artifacts в фиксированном порядке STEP/REQ/ADR/OQ и применяет
 * sort order/filter внутри каждой группы. Группы с пустым результатом
 * остаются в выдаче (с пустым `artifacts`), решение не рендерить пустую
 * группу в дереве остаётся за provider.
 */
export function groupArtifacts(
  artifacts: readonly Artifact[],
  sortOrder: SortOrder,
  filter: ArtifactFilterState,
): ArtifactGroup[] {
  const filtered = filterArtifacts(artifacts, filter);
  return ARTIFACT_KIND_ORDER.map((kind) => ({
    kind,
    artifacts: sortArtifacts(
      filtered.filter((artifact) => artifact.kind === kind),
      sortOrder,
    ),
  }));
}

/**
 * Различает три diagnosable empty-state Artifacts View: единственный
 * источник истины для этого расчёта — `ArtifactsTreeDataProvider.computeMessage`
 * вызывает эту же функцию (а не пересчитывает семантику самостоятельно),
 * передавая artifacts, собранные по всем valid roots сразу (aggregation
 * across roots не меняет результат: total/filtered count конкатенированного
 * массива равен сумме per-root count).
 * - `populated` — есть хотя бы один artifact после filter;
 * - `noArtifacts` — artifacts вообще нет (filter не влияет);
 * - `filteredEmpty` — artifacts есть, но активный filter скрыл все.
 *
 * Состояние "root невалиден/не-Harness" не входит в этот enum: оно
 * определяется по `ProjectState.kind`, а не по `Artifact[]`, и остаётся
 * ответственностью provider.
 */
export function computeEmptyState(
  artifacts: readonly Artifact[],
  filter: ArtifactFilterState,
): ArtifactsEmptyState {
  if (artifacts.length === 0) return 'noArtifacts';
  return filterArtifacts(artifacts, filter).length === 0 ? 'filteredEmpty' : 'populated';
}

/**
 * Focus View: active (`in_progress`) STEP, blocked STEP и open OQ, в порядке
 * ID внутри каждой группы. Никакого ранжирования или «next step» — выбор
 * следующей работы остаётся за пользователем (mutation policy STEP-004).
 */
export function selectFocusArtifacts(artifacts: readonly Artifact[]): FocusSelection {
  const steps = artifacts.filter((artifact) => artifact.kind === 'STEP');
  const openQuestions = artifacts.filter((artifact) => artifact.kind === 'OQ');
  return {
    activeSteps: sortArtifacts(
      steps.filter((step) => step.status === 'in_progress'),
      'id',
    ),
    blockedSteps: sortArtifacts(
      steps.filter((step) => step.status === 'blocked'),
      'id',
    ),
    openQuestions: sortArtifacts(
      openQuestions.filter((question) => question.status === 'open'),
      'id',
    ),
  };
}

/**
 * Кандидаты `Harness: Go to Artifact` по всем valid roots, отсортированные
 * по ID внутри каждого root. `rootName` заполняется только когда передано
 * несколько roots — single-root workspace не должен показывать избыточный
 * root context в Quick Pick `detail`.
 */
export function buildQuickPickCandidates(roots: readonly RootArtifacts[]): QuickPickCandidate[] {
  const multiRoot = roots.length > 1;
  const candidates: QuickPickCandidate[] = [];
  for (const root of roots) {
    for (const artifact of sortArtifacts(root.artifacts, 'id')) {
      candidates.push({ artifact, rootName: multiRoot ? root.rootName : undefined });
    }
  }
  return candidates;
}
