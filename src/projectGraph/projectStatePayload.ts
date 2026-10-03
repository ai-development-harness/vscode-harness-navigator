/**
 * Типы Project State API намеренно описывают только schemaVersion 1. Новые
 * optional поля metadata сохраняются, но не становятся основанием для
 * локальных выводов Navigator-а.
 */
export type ProjectGraphNodeKind =
  'PROJECT' | 'REQ' | 'ADR' | 'STEP' | 'OQ' | 'REVIEW' | 'SKILL' | 'MISSING';
export type ProjectGraphRelation =
  'implemented_by' | 'addresses' | 'governs' | 'depends_on' | 'affects' | 'reviews';

export interface ProjectStateNode {
  readonly id: string;
  readonly artifactId: string;
  readonly type: ProjectGraphNodeKind;
  readonly status?: string;
  readonly title?: string;
  readonly path?: string;
  readonly metadata: Readonly<Record<string, unknown>>;
}

export interface ProjectStateEdge {
  readonly source: string;
  readonly target: string;
  readonly relation: ProjectGraphRelation;
  readonly declaredBy: readonly string[];
}

export interface ProjectStatePayload {
  readonly schemaVersion: 1;
  readonly status: string;
  readonly integrity: 'ok' | 'degraded';
  readonly project: Readonly<Record<string, unknown>>;
  readonly summary: Readonly<Record<string, unknown>>;
  readonly graph: {
    readonly nodes: readonly ProjectStateNode[];
    readonly edges: readonly ProjectStateEdge[];
  };
  readonly insights: Readonly<Record<string, unknown>>;
  readonly diagnostics: readonly Readonly<Record<string, unknown>>[];
  readonly sources: Readonly<Record<string, unknown>>;
}

export type ProjectStatePayloadResult =
  | { readonly kind: 'valid'; readonly payload: ProjectStatePayload }
  | { readonly kind: 'invalid'; readonly reason: 'malformed' | 'unsupportedSchema' | 'blocked' };

const NODE_KINDS = new Set<ProjectGraphNodeKind>([
  'PROJECT',
  'REQ',
  'ADR',
  'STEP',
  'OQ',
  'REVIEW',
  'SKILL',
  'MISSING',
]);
const RELATIONS = new Set<ProjectGraphRelation>([
  'implemented_by',
  'addresses',
  'governs',
  'depends_on',
  'affects',
  'reviews',
]);

function record(value: unknown): Readonly<Record<string, unknown>> | undefined {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
    ? (value as Readonly<Record<string, unknown>>)
    : undefined;
}

function optionalString(value: unknown): string | undefined {
  return typeof value === 'string' ? value : undefined;
}

function declaredBy(value: unknown): readonly string[] {
  return Array.isArray(value)
    ? value.filter((item): item is string => typeof item === 'string')
    : [];
}

/** Неполный ответ API — ошибка, а не повод подменять graph данными ArtifactIndex. */
export function parseProjectStatePayload(value: unknown): ProjectStatePayloadResult {
  const root = record(value);
  if (root === undefined) return { kind: 'invalid', reason: 'malformed' };
  if (root.schemaVersion !== 1) return { kind: 'invalid', reason: 'unsupportedSchema' };
  if (root.status === 'BLOCKED') return { kind: 'invalid', reason: 'blocked' };
  if (
    root.status !== 'PASS' ||
    !['ok', 'degraded'].includes(String(root.integrity)) ||
    !record(root.project) ||
    !record(root.summary) ||
    !record(root.insights) ||
    !record(root.sources) ||
    !Array.isArray(root.diagnostics) ||
    root.diagnostics.some((d) => !record(d))
  )
    return { kind: 'invalid', reason: 'malformed' };
  const graph = record(root.graph);
  if (graph === undefined || !Array.isArray(graph.nodes) || !Array.isArray(graph.edges))
    return { kind: 'invalid', reason: 'malformed' };
  const nodes: ProjectStateNode[] = [];
  for (const candidate of graph.nodes) {
    const node = record(candidate);
    if (node === undefined) return { kind: 'invalid', reason: 'malformed' };
    const id = optionalString(node.id);
    const artifactId = optionalString(node.artifactId);
    const type = optionalString(node.type);
    if (
      id === undefined ||
      artifactId === undefined ||
      type === undefined ||
      !NODE_KINDS.has(type as ProjectGraphNodeKind)
    )
      return { kind: 'invalid', reason: 'malformed' };
    const status = optionalString(node.status);
    const title = optionalString(node.title);
    const nodePath = optionalString(node.path);
    nodes.push({
      id,
      artifactId,
      type: type as ProjectGraphNodeKind,
      ...(status === undefined ? {} : { status }),
      ...(title === undefined ? {} : { title }),
      ...(nodePath === undefined ? {} : { path: nodePath }),
      metadata: record(node.metadata) ?? {},
    });
  }
  const edges: ProjectStateEdge[] = [];
  for (const candidate of graph.edges) {
    const edge = record(candidate);
    if (edge === undefined) return { kind: 'invalid', reason: 'malformed' };
    const source = optionalString(edge.source);
    const target = optionalString(edge.target);
    const relation = optionalString(edge.relation);
    if (
      source === undefined ||
      target === undefined ||
      relation === undefined ||
      !RELATIONS.has(relation as ProjectGraphRelation)
    )
      return { kind: 'invalid', reason: 'malformed' };
    edges.push({
      source,
      target,
      relation: relation as ProjectGraphRelation,
      declaredBy: declaredBy(edge.declaredBy),
    });
  }
  const ids = new Set(nodes.map((n) => n.id));
  if (ids.size !== nodes.length || edges.some((e) => !ids.has(e.source) || !ids.has(e.target)))
    return { kind: 'invalid', reason: 'malformed' };
  return {
    kind: 'valid',
    payload: {
      schemaVersion: 1,
      status: optionalString(root.status) ?? 'UNKNOWN',
      integrity: root.integrity === 'degraded' ? 'degraded' : 'ok',
      project: record(root.project) ?? {},
      summary: record(root.summary) ?? {},
      graph: { nodes, edges },
      insights: record(root.insights) ?? {},
      diagnostics: Array.isArray(root.diagnostics)
        ? root.diagnostics
            .map(record)
            .filter((item): item is Readonly<Record<string, unknown>> => item !== undefined)
        : [],
      sources: record(root.sources) ?? {},
    },
  };
}
