import type * as vscode from 'vscode';
import type { DependencyGraphPresentation } from './dependencyGraphPresentation';
import { createGraphViewModel } from './dependencyGraphViewModel';
import { layoutDependencyGraph } from './dependencyGraphLayout';
import { dependencyGraphRuntime } from './dependencyGraphRuntime';
import { DEPENDENCY_GRAPH_STYLES } from './dependencyGraphStyles';

export type DependencyGraphMessage =
  | { readonly type: 'open' | 'select' | 'related'; readonly id: string }
  | { readonly type: 'refresh' | 'reset' | 'fit' };

export const GRAPH_LABELS = {
  canvasHelp: 'Use arrow keys to pan; Home fits the graph.',
  title: 'Dependency Graph',
  overview: 'Project overview',
  views: 'Views and filters',
  health: 'Health',
  active: 'In progress',
  blocked: 'Blocked',
  cycle: 'Dependency cycle',
  selected: 'Selected node',
  refresh: 'Refresh',
  reset: 'Full graph',
  fit: 'Fit to viewport',
  mode: 'STEP dependencies',
  kind: 'Node type',
  status: 'Status',
  relation: 'Relation type',
  all: 'All',
  search: 'Search ID or title',
  details: 'Details',
  open: 'Open canonical artifact',
  related: 'Related nodes',
  longest: 'Longest dependency chain',
  missing: 'Missing artifact: navigation is unavailable.',
  empty: 'No nodes match the filters.',
  diagnostics: 'Diagnostics',
  priority: 'Priority',
  phase: 'Phase',
  planFreshness: 'Plan freshness',
  planStaleCauses: 'Plan stale causes',
  planRemediation: 'Plan remediation',
  downstreamImpact: 'Downstream impact',
  executionGroups: 'Execution groups',
  provenance: 'Declared by',
  integrity: 'Integrity',
  root: 'Workspace root',
  full: 'Full graph',
  blockers: 'Blockers',
  cycles: 'Dependency cycles',
  missingReferences: 'Missing references',
  uncovered: 'Uncovered requirements',
  isolated: 'Isolated artifacts',
  incoming: 'Incoming relations',
  outgoing: 'Outgoing relations',
  copy: 'Copy command',
  unavailable: 'Unavailable',
  error: 'Graph is unavailable.',
  artifacts: 'Canonical artifacts',
  reviews: 'Reviews',
  skills: 'Skills',
  relationships: 'Relationships',
  relationshipCoverage: 'Relationship coverage',
  release: 'Harness release',
  emptyInspector: 'Select a node to inspect its canonical facts.',
  highlightedChain: 'Highlight longest chain',
  invalidReviews: 'Invalid reviews',
  zoomIn: 'Zoom in',
  zoomOut: 'Zoom out',
  stepType: 'STEP type',
  completionState: 'Completion state',
  latestReviewVerdict: 'Latest review verdict',
  latestCompletionResult: 'Latest completion result',
  riskFlags: 'Risk flags',
  planStatus: 'Plan status',
  planRevision: 'Plan revision',
  expectedType: 'Expected type',
  source: 'Source',
  target: 'Target',
  date: 'Date',
  createdAt: 'Created at',
  resolvedAt: 'Resolved at',
  verdict: 'Verdict',
  stepId: 'STEP ID',
  verificationStatus: 'Verification status',
  path: 'Canonical path',
  errors: 'Errors',
  message: 'Message',
  artifactId: 'Artifact ID',
  stepsCount: 'Steps count',
  parallel: 'Parallel',
  dependsOn: 'Depends on',
  yes: 'Yes',
  no: 'No',
  noDiagnostics: 'No diagnostics in this snapshot.',
  requirements: 'Requirements',
  coveredByStep: 'Covered by STEP',
  verified: 'Verified',
  staleEvidence: 'Stale evidence',
  openBlockingQuestions: 'Open blocking questions',
  orphanSteps: 'Orphan steps',
  invalidReferences: 'Invalid references',
} as const;
export type GraphLabels = { readonly [K in keyof typeof GRAPH_LABELS]: string };

/** Inline factories не получают Host capabilities; CSP и escaped data сохраняют ADR-008 boundary. */
export function dependencyGraphHtml(
  _webview: Pick<vscode.Webview, 'cspSource'>,
  model: DependencyGraphPresentation,
  labels: GraphLabels = GRAPH_LABELS,
  root = '',
): string {
  const nonce = Array.from({ length: 32 }, () => Math.floor(Math.random() * 36).toString(36)).join(
    '',
  );
  const encode = (v: unknown) => JSON.stringify(v).replace(/</gu, '\\u003c');
  return `<!DOCTYPE html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'nonce-${nonce}'; script-src 'nonce-${nonce}';"><style nonce="${nonce}">${DEPENDENCY_GRAPH_STYLES}</style></head><body>
<header class="page-header"><h1 id="title"></h1><div class="project-context"><strong id="project-name"></strong><span id="root"></span><span id="release"></span></div></header><section id="overview"></section><p id="state" role="status"></p>
<main id="layout"><details id="filters" open><summary id="views-title"></summary><div class="sidebar-body"><input id="search" type="search"><div id="presets"></div><h2 id="kind-title" class="section-label"></h2><div id="kinds"></div><h2 id="status-title" class="section-label"></h2><select id="status-filter"></select><h2 id="relation-title" class="section-label"></h2><div id="relations"></div></div></details>
<section id="canvas"><div id="toolbar"></div><svg id="graph" role="img" tabindex="0"></svg></section><aside id="details"><h2 id="details-title"></h2><section id="graph-inspector"></section></aside></main>
<details id="health"><summary id="health-title"></summary><div id="health-values"></div><div id="coverage"></div><h2 id="diagnostics-title" class="diagnostics-title"></h2><section id="diagnostics"></section></details>
<script nonce="${nonce}">const __name=(fn)=>fn,api=acquireVsCodeApi(),labels=${encode(labels)};for(const [id,key] of [['title','title'],['views-title','views'],['kind-title','kind'],['status-title','status'],['relation-title','relation'],['details-title','details'],['health-title','health'],['diagnostics-title','diagnostics']])document.getElementById(id).textContent=labels[key];document.getElementById('search').placeholder=labels.search;document.getElementById('search').setAttribute('aria-label',labels.search);document.getElementById('status-filter').setAttribute('aria-label',labels.status);document.getElementById('graph').setAttribute('aria-label',labels.title);document.getElementById('overview').setAttribute('aria-label',labels.overview);(${dependencyGraphRuntime.toString()})(api,labels,${encode(model)},${encode(root)},(${createGraphViewModel.toString()})(),${layoutDependencyGraph.toString()});</script></body></html>`;
}

/** Узкий message allowlist разрешает operations и IDs, но не пути или команды. */
export function isDependencyGraphMessage(value: unknown): value is DependencyGraphMessage {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) return false;
  const m = value as Record<string, unknown>;
  if (Object.keys(m).some((k) => k !== 'type' && k !== 'id')) return false;
  return (
    (['refresh', 'reset', 'fit'].includes(String(m.type)) && !('id' in m)) ||
    (['open', 'select', 'related'].includes(String(m.type)) &&
      typeof m.id === 'string' &&
      m.id.length > 0 &&
      m.id.length < 256)
  );
}
