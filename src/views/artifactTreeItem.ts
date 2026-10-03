import * as vscode from 'vscode';
import path from 'node:path';
import type { Artifact, ArtifactKind } from '../projectModel/artifactIndex';
import type { ArtifactPresentation } from './artifactPresentation';
import { VIEW_MESSAGES } from './viewMessages';
import { artifactPriorityPresentation } from './artifactPriorityPresentation';

export const ARTIFACT_PRIORITY_RESOURCE_SCHEME = 'harness-navigator-artifact';

export interface ArtifactPriorityResourceIdentity {
  readonly folderUri: string;
  readonly file: string;
}

/**
 * Стабильный synthetic URI связывает leaf с FileDecoration, не выдавая себя за файл workspace.
 * Поэтому глобальный provider не влияет на Explorer, открытие документа и Focus View.
 */
export function artifactPriorityResourceUri(
  folder: vscode.WorkspaceFolder,
  artifact: Artifact,
): vscode.Uri {
  return vscode.Uri.from({
    scheme: ARTIFACT_PRIORITY_RESOURCE_SCHEME,
    path: '/artifact',
    query: encodeURIComponent(JSON.stringify([folder.uri.toString(), artifact.file])),
  });
}

/** Возвращает identity только для корректной сериализованной пары root и canonical file. */
export function parseArtifactPriorityResourceUri(
  uri: vscode.Uri,
): ArtifactPriorityResourceIdentity | undefined {
  try {
    const value: unknown = JSON.parse(decodeURIComponent(uri.query));
    if (!Array.isArray(value) || typeof value[0] !== 'string' || typeof value[1] !== 'string')
      return undefined;
    return { folderUri: value[0], file: value[1] };
  } catch {
    return undefined;
  }
}

const KIND_ICONS: Readonly<Record<ArtifactKind, string>> = {
  STEP: 'checklist',
  REQ: 'bookmark',
  ADR: 'book',
  OQ: 'question',
};

/**
 * Общая forma leaf-узла Artifacts View и Focus View: оба представления
 * показывают одни и те же artifacts из общего `ArtifactIndex.snapshot()` и
 * должны допускать одинаковые context-действия (`copyArtifactId`/
 * `copyArtifactPath`) без дублирования структуры узла между модулями.
 */
export interface ArtifactLeafNode {
  readonly type: 'artifact';
  readonly folder: vscode.WorkspaceFolder;
  readonly artifact: Artifact;
}

/**
 * Общий leaf `TreeItem` builder для Artifacts View и Focus View: оба
 * представления открывают canonical artifact одинаково (`vscode.open` на
 * уже проверенный индексом `Artifact.file`) и используют один и тот же
 * `contextValue`, под который заведены `view/item/context` в `package.json`.
 */
export function buildArtifactTreeItem(
  folder: vscode.WorkspaceFolder,
  artifact: Artifact,
  presentation?: ArtifactPresentation,
  priorityResourceUri?: vscode.Uri,
  includePriorityTooltip = false,
): vscode.TreeItem {
  const item = new vscode.TreeItem(artifact.id, vscode.TreeItemCollapsibleState.None);
  item.id = `harnessNavigator.artifact:${folder.uri.toString()}:${artifact.id}`;
  item.description = artifact.title;
  item.tooltip = buildTooltip(folder, artifact, includePriorityTooltip);
  if (priorityResourceUri !== undefined) item.resourceUri = priorityResourceUri;
  // Focus View не передаёт presentation и сохраняет нейтральную kind-иконку.
  // Semantic цвет/иконка создаются только opt-in consumer-ом Artifacts View.
  item.iconPath = new vscode.ThemeIcon(
    presentation?.iconId ?? KIND_ICONS[artifact.kind],
    presentation?.colorId === undefined ? undefined : new vscode.ThemeColor(presentation.colorId),
  );
  item.contextValue = 'harnessArtifactItem';
  item.command = {
    command: 'vscode.open',
    title: vscode.l10n.t(VIEW_MESSAGES.openArtifact),
    arguments: [vscode.Uri.file(artifact.file)],
  };
  return item;
}

function buildTooltip(
  folder: vscode.WorkspaceFolder,
  artifact: Artifact,
  includePriority: boolean,
): string {
  const relativePath = path.relative(folder.uri.fsPath, artifact.file);
  const statusLine = vscode.l10n.t(VIEW_MESSAGES.statusTooltip, artifact.status ?? '—');
  const priority = includePriority
    ? artifactPriorityPresentation(artifact.metadata.priority)
    : undefined;
  const priorityLine =
    priority === undefined
      ? ''
      : `\n${vscode.l10n.t(VIEW_MESSAGES.priorityTooltip, vscode.l10n.t(priority.label))}`;
  return `${artifact.id} — ${artifact.title}\n${statusLine}${priorityLine}\n${relativePath}`;
}
