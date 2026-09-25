import type { Artifact, ArtifactKind } from '../projectModel/artifactIndex';

/**
 * Theme-aware presentation leaf-артефакта только для Harness Artifacts.
 * Модуль читает исключительно уже построенный `Artifact` из Artifact Index:
 * не импортирует VS Code и не выполняет повторный parsing Markdown.
 */
export interface ArtifactPresentation {
  readonly iconId: string;
  readonly colorId: string | undefined;
}

const NEUTRAL_PRESENTATIONS: Readonly<Record<ArtifactKind, ArtifactPresentation>> = {
  STEP: { iconId: 'checklist', colorId: undefined },
  REQ: { iconId: 'bookmark', colorId: undefined },
  ADR: { iconId: 'book', colorId: undefined },
  OQ: { iconId: 'question', colorId: undefined },
};

const STEP_PRESENTATIONS: Readonly<Record<string, ArtifactPresentation>> = {
  planned: { iconId: 'circle-large-outline', colorId: 'editorInfo.foreground' },
  in_progress: { iconId: 'sync~spin', colorId: 'editorInfo.foreground' },
  blocked: { iconId: 'circle-slash', colorId: 'editorError.foreground' },
  completed: { iconId: 'pass-filled', colorId: 'testing.iconPassed' },
  deferred: { iconId: 'clock', colorId: 'editorWarning.foreground' },
  cancelled: { iconId: 'close', colorId: 'disabledForeground' },
};

const REQ_PRESENTATIONS: Readonly<Record<string, ArtifactPresentation>> = {
  critical: { iconId: 'flame', colorId: 'editorError.foreground' },
  high: { iconId: 'arrow-up', colorId: 'editorWarning.foreground' },
  medium: { iconId: 'dash', colorId: 'editorInfo.foreground' },
  low: { iconId: 'arrow-down', colorId: 'disabledForeground' },
};

const ADR_PRESENTATIONS: Readonly<Record<string, ArtifactPresentation>> = {
  proposed: { iconId: 'lightbulb', colorId: 'editorWarning.foreground' },
  accepted: { iconId: 'check', colorId: 'testing.iconPassed' },
  superseded: { iconId: 'history', colorId: 'disabledForeground' },
  rejected: { iconId: 'circle-slash', colorId: 'editorError.foreground' },
};

/**
 * Возвращает semantic presentation только для известных значений matrix.
 * Workspace metadata не типизирована в runtime, поэтому любое отсутствующее
 * или неизвестное значение намеренно остаётся безопасной neutral kind-иконкой.
 */
export function artifactPresentation(artifact: Artifact): ArtifactPresentation {
  switch (artifact.kind) {
    case 'STEP':
      return presentationFor(STEP_PRESENTATIONS, artifact.status, artifact.kind);
    case 'REQ':
      return presentationFor(REQ_PRESENTATIONS, artifact.metadata.priority, artifact.kind);
    case 'ADR':
      return presentationFor(ADR_PRESENTATIONS, artifact.status, artifact.kind);
    case 'OQ':
      return NEUTRAL_PRESENTATIONS.OQ;
  }
}

function presentationFor(
  presentations: Readonly<Record<string, ArtifactPresentation>>,
  value: unknown,
  kind: ArtifactKind,
): ArtifactPresentation {
  if (typeof value !== 'string') return NEUTRAL_PRESENTATIONS[kind];
  return presentations[value] ?? NEUTRAL_PRESENTATIONS[kind];
}
