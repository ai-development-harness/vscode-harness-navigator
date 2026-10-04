import type { ProjectGraphSnapshot } from './projectStateService';
import type { ProjectGraphNodeKind, ProjectGraphRelation } from './projectStatePayload';

export interface DependencyGraphPresentation {
  readonly navigationRevision?: number;
  readonly state: ProjectGraphSnapshot['kind'];
  readonly error?: string;
  readonly nodes: readonly {
    readonly id: string;
    readonly kind: ProjectGraphNodeKind;
    readonly status?: string;
    readonly title?: string;
    readonly path?: string;
    readonly metadata: Readonly<Record<string, unknown>>;
  }[];
  readonly edges: readonly {
    readonly from: string;
    readonly to: string;
    readonly type: ProjectGraphRelation;
    readonly declaredBy: readonly string[];
  }[];
  readonly longestDependencyChain: unknown;
  readonly project?: Readonly<Record<string, unknown>>;
  readonly summary?: Readonly<Record<string, unknown>>;
  readonly insights?: Readonly<Record<string, unknown>>;
  readonly diagnostics?: readonly Readonly<Record<string, unknown>>[];
  readonly sources?: Readonly<Record<string, unknown>>;
  readonly integrity?: string;
  readonly cycleMembers?: readonly string[];
  readonly selectedId?: string;
  readonly focusId?: string;
}

/** Только presentation: API relations сохраняются без синтеза reciprocal edges. */
export function presentDependencyGraph(
  snapshot: ProjectGraphSnapshot,
  focusId?: string,
): DependencyGraphPresentation {
  if (snapshot.kind !== 'ready' || snapshot.payload === undefined)
    return {
      state: snapshot.kind,
      ...(snapshot.error === undefined ? {} : { error: snapshot.error }),
      nodes: [],
      edges: [],
      longestDependencyChain: undefined,
      // Pending context intent сохраняется до первого ready snapshot; это не graph facts.
      ...(focusId === undefined ? {} : { selectedId: focusId, focusId }),
    };
  const payload = snapshot.payload;
  // Полный snapshot остаётся доступен WebView: focus — только intent представления,
  // иначе overview и локальные presets потеряли бы факты, которых нет возле узла.
  const allNodes = payload.graph.nodes;
  return {
    state: 'ready',
    project: payload.project,
    summary: payload.summary,
    insights: payload.insights,
    diagnostics: payload.diagnostics,
    sources: payload.sources,
    integrity: payload.integrity,
    ...(focusId === undefined ? {} : { selectedId: focusId, focusId }),
    cycleMembers: cycleMembers(payload.insights),
    nodes: allNodes.map(({ id, type, status, title, path, metadata }) => ({
      id,
      kind: type,
      metadata,
      ...(status === undefined ? {} : { status }),
      ...(title === undefined ? {} : { title }),
      ...(path === undefined ? {} : { path }),
    })),
    edges: payload.graph.edges.map((edge) => ({
      from: edge.source,
      to: edge.target,
      type: edge.relation,
      declaredBy: edge.declaredBy,
    })),
    longestDependencyChain: (payload.insights.dependency as Record<string, unknown> | undefined)
      ?.longestChain,
  };
}

export function filterDependencyGraph(
  model: DependencyGraphPresentation,
  options: {
    readonly stepDependencies?: boolean;
    readonly nodeKinds?: readonly ProjectGraphNodeKind[];
    readonly relations?: readonly ProjectGraphRelation[];
    readonly statuses?: readonly string[];
  },
): DependencyGraphPresentation {
  const typed = options.stepDependencies
    ? model.nodes.filter((node) => node.kind === 'STEP')
    : options.nodeKinds === undefined
      ? model.nodes
      : model.nodes.filter((node) => options.nodeKinds?.includes(node.kind));
  const nodes =
    options.statuses === undefined
      ? typed
      : typed.filter((node) => options.statuses?.includes(node.status ?? ''));
  const ids = new Set(nodes.map((node) => node.id));
  return {
    ...model,
    nodes,
    edges: model.edges.filter(
      (edge) =>
        ids.has(edge.from) &&
        ids.has(edge.to) &&
        (options.stepDependencies
          ? edge.type === 'depends_on'
          : options.relations === undefined || options.relations.includes(edge.type)),
    ),
  };
}

/** Подсвечиваем только members, прямо предоставленные API, без своего cycle detection. */
function cycleMembers(insights: Readonly<Record<string, unknown>>): string[] {
  const dependency = insights.dependency as { cycles?: unknown } | undefined;
  return Array.isArray(dependency?.cycles)
    ? dependency.cycles.flatMap((cycle: unknown) =>
        Array.isArray(cycle) ? cycle.filter((id): id is string => typeof id === 'string') : [],
      )
    : [];
}
