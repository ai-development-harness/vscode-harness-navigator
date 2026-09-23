import type { ArtifactSnapshot } from '../projectModel/artifactIndex';
import type { ProjectDiagnosticCategory, ProjectState } from '../projectModel/projectState';
import { selectFocusArtifacts } from './artifactViewModel';

/**
 * Vscode-независимая сводка проекта для Status Bar и Project Summary view.
 * Считает только из уже готовых `ProjectState`/`ArtifactSnapshot` (единые
 * derived indexes), без parsing и без зависимости от locale: результат
 * содержит числа, canonical enum-значения и категории diagnostics.
 */
export interface RootSummaryInput {
  readonly rootName: string;
  /** Уникальный ключ root (folder.uri.toString()); basename не уникален. */
  readonly rootKey: string;
  readonly state: ProjectState;
  /** Snapshot ArtifactIndex; `undefined` для non-valid root. */
  readonly snapshot: ArtifactSnapshot | undefined;
}

export interface SummaryCounts {
  readonly steps: number;
  readonly requirements: number;
  readonly adrs: number;
  readonly openQuestions: number;
  readonly inProgress: number;
  readonly blocked: number;
  readonly diagnostics: number;
}

export interface RootSummary {
  readonly rootName: string;
  readonly rootKey: string;
  readonly kind: ProjectState['kind'];
  readonly category: ProjectDiagnosticCategory;
  /** Ключ и аргументы локализуемого объяснения diagnostic root. */
  readonly explanation: string;
  readonly explanationArguments: readonly (string | number)[];
  /** Задано только для valid root. */
  readonly release: string | undefined;
  readonly counts: SummaryCounts;
}

export interface SummaryModel {
  readonly roots: readonly RootSummary[];
  /** Суммарные counts по valid roots. */
  readonly aggregate: SummaryCounts;
  readonly validRootCount: number;
}

export const EMPTY_COUNTS: SummaryCounts = {
  steps: 0,
  requirements: 0,
  adrs: 0,
  openQuestions: 0,
  inProgress: 0,
  blocked: 0,
  diagnostics: 0,
};

function countsOf(snapshot: ArtifactSnapshot): SummaryCounts {
  const focus = selectFocusArtifacts(snapshot.artifacts);
  const ofKind = (kind: string) =>
    snapshot.artifacts.filter((artifact) => artifact.kind === kind).length;
  return {
    steps: ofKind('STEP'),
    requirements: ofKind('REQ'),
    adrs: ofKind('ADR'),
    openQuestions: focus.openQuestions.length,
    inProgress: focus.activeSteps.length,
    blocked: focus.blockedSteps.length,
    diagnostics: snapshot.diagnostics.length,
  };
}

function addCounts(left: SummaryCounts, right: SummaryCounts): SummaryCounts {
  return {
    steps: left.steps + right.steps,
    requirements: left.requirements + right.requirements,
    adrs: left.adrs + right.adrs,
    openQuestions: left.openQuestions + right.openQuestions,
    inProgress: left.inProgress + right.inProgress,
    blocked: left.blocked + right.blocked,
    diagnostics: left.diagnostics + right.diagnostics,
  };
}

export function buildSummaryModel(inputs: readonly RootSummaryInput[]): SummaryModel {
  const roots: RootSummary[] = inputs.map((input) => {
    const valid = input.state.kind === 'valid' && input.snapshot !== undefined;
    return {
      rootName: input.rootName,
      rootKey: input.rootKey,
      kind: input.state.kind,
      category: input.state.diagnostic.category,
      explanation: input.state.diagnostic.message,
      explanationArguments: input.state.diagnostic.messageArguments,
      release: input.state.kind === 'valid' ? input.state.release : undefined,
      counts: valid && input.snapshot !== undefined ? countsOf(input.snapshot) : EMPTY_COUNTS,
    };
  });
  const validRoots = roots.filter((root) => root.kind === 'valid');
  return {
    roots,
    aggregate: validRoots.reduce((sum, root) => addCounts(sum, root.counts), EMPTY_COUNTS),
    validRootCount: validRoots.length,
  };
}
