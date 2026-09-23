import type { Artifact } from '../projectModel/artifactIndex';

/** Данные hover без vscode: форматирование и l10n остаются в provider. */
export interface HoverModel {
  readonly id: string;
  readonly title: string;
  readonly kind: string;
  readonly status: string;
  readonly outgoing: number;
  readonly incoming: number;
  readonly mentions: number;
}

export function buildHoverModel(artifact: Artifact, mentions: number): HoverModel {
  return {
    id: artifact.id,
    title: artifact.title,
    kind: artifact.kind,
    status: artifact.status ?? '—',
    outgoing: artifact.outgoingRelations.length,
    incoming: artifact.incomingRelations.length,
    mentions,
  };
}

export interface CompletionModel {
  readonly id: string;
  readonly detail: string;
  readonly title: string;
}

/**
 * Фильтрует известные ID по набранному префиксу. `insertText` в provider
 * всегда равен `id` — только canonical ID, без title или markup.
 */
export function buildCompletionModels(
  ids: Iterable<string>,
  lookup: (id: string) => Artifact | undefined,
  prefix: string,
): CompletionModel[] {
  const result: CompletionModel[] = [];
  for (const id of ids) {
    if (!id.startsWith(prefix)) continue;
    const artifact = lookup(id);
    if (artifact === undefined) continue;
    result.push({
      id,
      detail: `${artifact.kind} · ${artifact.status ?? '—'}`,
      title: artifact.title,
    });
  }
  return result.sort((left, right) => left.id.localeCompare(right.id, 'en', { numeric: true }));
}
