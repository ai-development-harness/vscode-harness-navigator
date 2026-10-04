import type { DependencyGraphPresentation } from './dependencyGraphPresentation';
import type { ProjectGraphNodeKind, ProjectGraphRelation } from './projectStatePayload';

export type GraphPreset =
  'full' | 'steps' | 'blockers' | 'cycles' | 'missing' | 'uncovered' | 'isolated';
export interface GraphFilters {
  readonly preset: GraphPreset;
  readonly kinds: readonly ProjectGraphNodeKind[];
  readonly statuses: readonly string[];
  readonly relations: readonly ProjectGraphRelation[];
  readonly search: string;
  readonly focusId?: string;
}
export interface GraphInspector {
  readonly id: string;
  readonly kind: string;
  readonly title?: string;
  readonly status?: string;
  readonly path?: string;
  readonly fields: readonly {
    readonly key: string;
    readonly label: string;
    readonly value: string;
  }[];
  readonly causes: readonly string[];
  readonly remediation?: string;
  readonly groups: readonly {
    id: string;
    count?: number;
    parallel?: boolean;
    dependsOn: readonly string[];
  }[];
  readonly impact?: number;
  readonly incoming: DependencyGraphPresentation['edges'];
  readonly outgoing: DependencyGraphPresentation['edges'];
}

/**
 * Один набор чистых helpers обслуживает unit tests и браузер. Все runtime bindings
 * объявлены внутри factory: её сериализация не зависит от имён imports после minify.
 */
export function createGraphViewModel() {
  const kinds: readonly ProjectGraphNodeKind[] = [
    'PROJECT',
    'REQ',
    'ADR',
    'STEP',
    'OQ',
    'REVIEW',
    'SKILL',
    'MISSING',
  ];
  const relations: readonly ProjectGraphRelation[] = [
    'implemented_by',
    'addresses',
    'governs',
    'depends_on',
    'affects',
    'reviews',
  ];
  const rec = (v: unknown): Readonly<Record<string, unknown>> =>
    typeof v === 'object' && v !== null && !Array.isArray(v) ? (v as Record<string, unknown>) : {};
  const ids = (v: unknown): string[] =>
    Array.isArray(v) ? v.filter((i): i is string => typeof i === 'string') : [];
  const num = (v: unknown): number | undefined =>
    typeof v === 'number' && Number.isFinite(v) ? v : undefined;
  const str = (v: unknown): string | undefined =>
    typeof v === 'string' && v.trim() ? v : undefined;
  const text = (v: unknown): string | undefined =>
    typeof v === 'string'
      ? str(v)
      : typeof v === 'number' || typeof v === 'boolean'
        ? `${v}`
        : Array.isArray(v)
          ? v
              .flatMap((i) =>
                typeof i === 'string' || typeof i === 'number' || typeof i === 'boolean'
                  ? [`${i}`]
                  : [],
              )
              .join(', ') || undefined
          : undefined;
  const insightIds = (v: unknown): string[] =>
    Array.isArray(v)
      ? v.flatMap((i) => (typeof i === 'string' ? [i] : ids([rec(i).nodeId ?? rec(i).id])))
      : [];
  const defaults = (focusId?: string): GraphFilters => ({
    preset: 'full',
    kinds: [...kinds],
    relations: [...relations],
    statuses: [],
    search: '',
    ...(focusId ? { focusId } : {}),
  });
  function overview(model: DependencyGraphPresentation) {
    const s = rec(model.summary),
      p = rec(model.project),
      d = rec(rec(model.insights).dependency);
    return {
      projectName: str(p.name),
      release: str(p.harnessRelease),
      integrity: model.integrity,
      artifacts: num(s.artifacts),
      reviews: num(s.reviews),
      skills: num(s.skills),
      relationships: num(s.relationships),
      blockers: num(s.blockers),
      missingReferences: num(s.missingReferences),
      invalidReviews: num(s.invalidReviews),
      relationshipCoveragePercent: num(s.relationshipCoveragePercent),
      cycles: Array.isArray(d.cycles) ? d.cycles.length : undefined,
    };
  }
  function cycleMembers(model: DependencyGraphPresentation): string[] {
    const v = rec(rec(model.insights).dependency).cycles;
    return Array.isArray(v) ? [...new Set(v.flatMap(ids))] : [];
  }
  function longestChain(model: DependencyGraphPresentation): string[] {
    return ids(rec(rec(model.insights).dependency).longestChain ?? model.longestDependencyChain);
  }
  function visible(
    model: DependencyGraphPresentation,
    filters: GraphFilters,
  ): DependencyGraphPresentation {
    const insights = rec(model.insights);
    const direct = (seed: readonly string[]) => {
      const initial = new Set(seed);
      return new Set([
        ...seed,
        ...model.edges.flatMap((e) =>
          initial.has(e.from) ? [e.to] : initial.has(e.to) ? [e.from] : [],
        ),
      ]);
    };
    let allowed: ReadonlySet<string> | undefined;
    switch (filters.preset) {
      case 'steps':
        allowed = new Set(model.nodes.filter((n) => n.kind === 'STEP').map((n) => n.id));
        break;
      case 'blockers':
        allowed = direct(insightIds(insights.blockers));
        break;
      case 'cycles':
        allowed = new Set(cycleMembers(model));
        break;
      case 'missing':
        allowed = direct(model.nodes.filter((n) => n.kind === 'MISSING').map((n) => n.id));
        break;
      case 'uncovered':
        allowed = new Set(insightIds(insights.uncoveredRequirements));
        break;
      case 'isolated':
        allowed = new Set(insightIds(insights.isolatedArtifacts));
        break;
    }
    const query = filters.search.trim().toLowerCase();
    const focus = filters.focusId ? direct([filters.focusId]) : undefined;
    const nodes = model.nodes.filter(
      (n) =>
        (!allowed || allowed.has(n.id)) &&
        (!focus || focus.has(n.id)) &&
        filters.kinds.includes(n.kind) &&
        (!filters.statuses.length || filters.statuses.includes(n.status ?? '')) &&
        (!query || n.id.toLowerCase().includes(query) || n.title?.toLowerCase().includes(query)) &&
        (filters.preset !== 'cycles' || n.kind === 'STEP'),
    );
    const shown = new Set(nodes.map((n) => n.id));
    return {
      ...model,
      nodes,
      edges: model.edges.filter(
        (e) =>
          shown.has(e.from) &&
          shown.has(e.to) &&
          filters.relations.includes(e.type) &&
          (!['steps', 'cycles'].includes(filters.preset) || e.type === 'depends_on'),
      ),
    };
  }
  function inspector(
    model: DependencyGraphPresentation,
    selectedId?: string,
  ): GraphInspector | undefined {
    const node = model.nodes.find((n) => n.id === selectedId);
    if (!node) return;
    const m = node.metadata;
    const fieldsByKind: Record<string, readonly string[]> = {
      STEP: [
        'stepType',
        'priority',
        'phase',
        'completionState',
        'latestReviewVerdict',
        'latestCompletionResult',
        'riskFlags',
        'planStatus',
        'planRevision',
        'planFreshness',
      ],
      REQ: ['priority', 'source'],
      ADR: ['date'],
      OQ: ['createdAt', 'resolvedAt'],
      REVIEW: ['verdict', 'stepId', 'createdAt', 'verificationStatus'],
      MISSING: ['expectedType'],
      PROJECT: [],
      SKILL: [],
    };
    const fields = (fieldsByKind[node.kind] ?? []).flatMap((key) => {
      const value = text(m[key]);
      return value === undefined ? [] : [{ key, label: key, value }];
    });
    const showCauses =
      node.kind === 'STEP' && ['stale', 'blocked', 'invalid'].includes(String(m.planFreshness));
    const causes =
      showCauses && Array.isArray(m.planStaleCauses)
        ? m.planStaleCauses.flatMap((c) => {
            const value =
              text(c) ?? [text(rec(c).component), text(rec(c).change)].filter(Boolean).join(' · ');
            return value ? [value] : [];
          })
        : [];
    const remediation = showCauses ? str(m.planRemediation) : undefined;
    const groups =
      node.kind === 'STEP' && Array.isArray(m.executionGroups)
        ? m.executionGroups.flatMap((g) => {
            const value = rec(g),
              id = str(value.id);
            return id
              ? [
                  {
                    id,
                    ...(Array.isArray(value.steps) ? { count: value.steps.length } : {}),
                    ...(typeof value.parallel === 'boolean' ? { parallel: value.parallel } : {}),
                    dependsOn: ids(value.dependsOn),
                  },
                ]
              : [];
          })
        : [];
    const blocker = Array.isArray(rec(model.insights).blockers)
      ? (rec(model.insights).blockers as unknown[]).find((b) => rec(b).nodeId === node.id)
      : undefined;
    const impact =
      node.kind === 'STEP'
        ? (num(m.downstreamImpact) ?? num(m.impactCount) ?? num(rec(blocker).impactCount))
        : undefined;
    return {
      id: node.id,
      kind: node.kind,
      ...(node.title ? { title: node.title } : {}),
      ...(node.status ? { status: node.status } : {}),
      ...(node.kind !== 'MISSING' && node.path ? { path: node.path } : {}),
      fields,
      causes,
      ...(remediation ? { remediation } : {}),
      groups,
      ...(impact === undefined ? {} : { impact }),
      incoming: model.edges.filter((e) => e.to === node.id),
      outgoing: model.edges.filter((e) => e.from === node.id),
    };
  }
  function diagnosticLines(model: DependencyGraphPresentation) {
    return (model.diagnostics ?? []).map((d) => ({
      code: str(d.code) ?? str(d.category) ?? '',
      fields: ['source', 'target', 'relation', 'path', 'errors', 'message', 'artifactId'].flatMap(
        (key) => {
          const value = text(d[key]);
          return value === undefined ? [] : [{ key, value }];
        },
      ),
    }));
  }
  function health(model: DependencyGraphPresentation) {
    const s = rec(model.summary),
      i = rec(model.insights),
      t = rec(s.traceabilityCoverage ?? i.traceabilityCoverage);
    return {
      counts: {
        blockers: num(s.blockers),
        missingReferences: num(s.missingReferences),
        invalidReviews: num(s.invalidReviews),
        uncovered: Array.isArray(i.uncoveredRequirements)
          ? i.uncoveredRequirements.length
          : undefined,
        isolated: Array.isArray(i.isolatedArtifacts) ? i.isolatedArtifacts.length : undefined,
        cycles: Array.isArray(rec(i.dependency).cycles)
          ? (rec(i.dependency).cycles as unknown[]).length
          : undefined,
      },
      coverage: Object.entries(t).flatMap(([key, value]) =>
        num(value) === undefined ? [] : [{ key, value: value as number }],
      ),
    };
  }
  return {
    kinds,
    relations,
    defaults,
    overview,
    visible,
    inspector,
    diagnosticLines,
    cycleMembers,
    longestChain,
    health,
  };
}
export type GraphViewTools = ReturnType<typeof createGraphViewModel>;
const tools = createGraphViewModel();
export const defaultGraphFilters = tools.defaults;
export const graphOverview = tools.overview;
export const visibleGraph = tools.visible;
export const inspectorFor = tools.inspector;
