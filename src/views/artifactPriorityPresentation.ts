/**
 * Это отображение принимает только closed-set canonical priority из Artifact Index.
 * Неизвестные значения metadata workspace намеренно не превращаются в decoration.
 */
export interface ArtifactPriorityPresentation {
  readonly badge: string;
  readonly colorId: string;
  readonly label: string;
}

const PRESENTATIONS: Readonly<Record<string, ArtifactPriorityPresentation>> = {
  critical: { badge: '!', colorId: 'editorError.foreground', label: 'Critical' },
  high: { badge: 'H', colorId: 'editorWarning.foreground', label: 'High' },
  medium: { badge: 'M', colorId: 'editorInfo.foreground', label: 'Medium' },
  low: { badge: 'L', colorId: 'disabledForeground', label: 'Low' },
};

/** Возвращает decoration только для canonical priority, включая safe fallback. */
export function artifactPriorityPresentation(
  value: unknown,
): ArtifactPriorityPresentation | undefined {
  return typeof value === 'string' && Object.hasOwn(PRESENTATIONS, value)
    ? PRESENTATIONS[value]
    : undefined;
}
