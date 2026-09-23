import type {
  Artifact,
  ArtifactReference,
  DefinitionRange,
  TextRange,
} from '../projectModel/artifactIndex';

/** Минимальный срез ArtifactIndex, нужный relations/references (без vscode). */
export interface RelationsIndex {
  get(id: string): Artifact | undefined;
  referencesTo(id: string, includeDeclaration?: boolean): readonly ArtifactReference[];
  definitionRangesOf(id: string): readonly DefinitionRange[];
}

export interface RelationItem {
  readonly id: string;
  readonly unresolved: boolean;
  readonly title?: string;
  readonly kind?: string;
  /** Canonical файл и позиция определения для клика; отсутствует у unresolved. */
  readonly file?: string;
  readonly range?: TextRange;
}

export interface MentionGroup {
  readonly file: string;
  readonly references: readonly ArtifactReference[];
}

export interface Relations {
  readonly id: string;
  readonly outgoing: readonly RelationItem[];
  readonly incoming: readonly RelationItem[];
  readonly mentions: readonly MentionGroup[];
}

function toItem(index: RelationsIndex, id: string): RelationItem {
  const artifact = index.get(id);
  // Dangling relation не бросает исключение: элемент помечается unresolved.
  if (artifact === undefined) return { id, unresolved: true };
  const range = index.definitionRangesOf(id)[0];
  return {
    id,
    unresolved: false,
    title: artifact.title,
    kind: artifact.kind,
    file: artifact.file,
    ...(range === undefined ? {} : { range }),
  };
}

/**
 * Строит outgoing/incoming/backlinks по общим индексам. Mentions используют
 * тот же `referencesTo`, что и Find All References (без declaration).
 */
export function buildRelations(index: RelationsIndex, id: string): Relations | undefined {
  const artifact = index.get(id);
  if (artifact === undefined) return undefined;
  const groups = new Map<string, ArtifactReference[]>();
  for (const reference of index.referencesTo(id, false)) {
    const list = groups.get(reference.file);
    if (list === undefined) groups.set(reference.file, [reference]);
    else list.push(reference);
  }
  return {
    id,
    outgoing: artifact.outgoingRelations.map((item) => toItem(index, item)),
    incoming: artifact.incomingRelations.map((item) => toItem(index, item)),
    mentions: [...groups.entries()]
      .sort(([left], [right]) => left.localeCompare(right))
      .map(([file, references]) => ({ file, references })),
  };
}
