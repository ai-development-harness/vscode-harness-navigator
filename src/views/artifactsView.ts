import * as vscode from 'vscode';
import {
  FILTER_FIELDS,
  SORT_ORDERS,
  STEP_PRIORITY_VALUES,
  STEP_STATUS_VALUES,
  STEP_TYPE_VALUES,
  computeEmptyState,
  groupArtifacts,
  type ArtifactFilterState,
  type FilterField,
  type SortOrder,
} from './artifactViewModel';
import { buildArtifactTreeItem, type ArtifactLeafNode } from './artifactTreeItem';
import { artifactPresentation } from './artifactPresentation';
import { VIEW_MESSAGES } from './viewMessages';
import type { Artifact, ArtifactKind } from '../projectModel/artifactIndex';
import type { ProjectStateService } from '../projectModel/projectStateService';

/** Секция workspace-настроек Artifacts View (sort order + 4 filter key). */
const CONFIG_SECTION = 'harnessNavigator.artifacts';

type ArtifactsTreeNode =
  | { readonly type: 'root'; readonly folder: vscode.WorkspaceFolder }
  | { readonly type: 'group'; readonly folder: vscode.WorkspaceFolder; readonly kind: ArtifactKind }
  | ArtifactLeafNode;

/**
 * `vscode.TreeDataProvider` для Harness Artifacts View. Данные читаются
 * только через `ProjectStateService.getIndex(folder)?.snapshot()` — никакого
 * собственного parsing Markdown здесь нет (mutation policy STEP-004,
 * forbidden: "самостоятельный parsing files в provider"). Группировка,
 * сортировка и фильтрация полностью делегированы vscode-независимому
 * `artifactViewModel.ts`; этот модуль отвечает только за vscode wiring:
 * структуру дерева, `TreeItem`, чтение/запись workspace preferences и
 * подписку на изменения общей project model.
 */
export class ArtifactsTreeDataProvider
  implements vscode.TreeDataProvider<ArtifactsTreeNode>, vscode.Disposable
{
  private readonly changeEmitter = new vscode.EventEmitter<void>();
  readonly onDidChangeTreeData = this.changeEmitter.event;
  private readonly listeners: vscode.Disposable[];

  constructor(private readonly projectStates: ProjectStateService) {
    this.listeners = [
      projectStates.onDidChangeProjectModel(() => this.changeEmitter.fire()),
      vscode.workspace.onDidChangeConfiguration((event) => {
        if (event.affectsConfiguration(CONFIG_SECTION)) this.changeEmitter.fire();
      }),
    ];
  }

  getTreeItem(element: ArtifactsTreeNode): vscode.TreeItem {
    switch (element.type) {
      case 'root':
        return buildRootTreeItem(element.folder);
      case 'group':
        return buildGroupTreeItem(element.folder, element.kind);
      case 'artifact':
        return buildArtifactTreeItem(
          element.folder,
          element.artifact,
          artifactPresentation(element.artifact),
        );
    }
  }

  getChildren(element?: ArtifactsTreeNode): ArtifactsTreeNode[] {
    const folders = this.validFolders();
    if (element === undefined) {
      if (folders.length > 1) return folders.map((folder) => ({ type: 'root', folder }) as const);
      const only = folders[0];
      return only === undefined ? [] : this.groupsFor(only);
    }
    if (element.type === 'root') return this.groupsFor(element.folder);
    if (element.type === 'group') return this.artifactsFor(element.folder, element.kind);
    return [];
  }

  /**
   * Локализованное сообщение для `TreeView.message`, различающее три
   * diagnosable empty state: отсутствие valid Harness root, valid root без
   * artifacts и valid root, у которого активный filter скрыл все artifacts.
   * "populated" возвращает `''` (`TreeView.message` — non-optional `string`
   * под `exactOptionalPropertyTypes`; пустая строка эквивалентна отсутствию
   * message в VS Code UI). Сам three-state расчёт делегирован
   * `computeEmptyState` — единственному источнику истины (см. её doc
   * comment) — а не пересчитывается здесь самостоятельно; artifacts по всем
   * valid roots объединяются перед вызовом, так как filter теперь один
   * workspace-wide `ArtifactFilterState` (не per-folder).
   */
  computeMessage(): string {
    const folders = this.validFolders();
    if (folders.length === 0) return vscode.l10n.t(VIEW_MESSAGES.noHarnessProject);
    const allArtifacts = folders.flatMap((folder) => this.snapshotArtifacts(folder));
    switch (computeEmptyState(allArtifacts, readFilter())) {
      case 'noArtifacts':
        return vscode.l10n.t(VIEW_MESSAGES.noArtifacts);
      case 'filteredEmpty':
        return vscode.l10n.t(VIEW_MESSAGES.filteredEmpty);
      case 'populated':
        return '';
    }
  }

  dispose(): void {
    for (const listener of this.listeners.splice(0)) listener.dispose();
    this.changeEmitter.dispose();
  }

  private validFolders(): vscode.WorkspaceFolder[] {
    return (vscode.workspace.workspaceFolders ?? []).filter(
      (folder) => this.projectStates.getIndex(folder) !== undefined,
    );
  }

  private snapshotArtifacts(folder: vscode.WorkspaceFolder): readonly Artifact[] {
    return this.projectStates.getIndex(folder)?.snapshot().artifacts ?? [];
  }

  private groupsFor(folder: vscode.WorkspaceFolder): ArtifactsTreeNode[] {
    const groups = groupArtifacts(this.snapshotArtifacts(folder), readSortOrder(), readFilter());
    return groups
      .filter((group) => group.artifacts.length > 0)
      .map((group) => ({ type: 'group', folder, kind: group.kind }) as const);
  }

  private artifactsFor(folder: vscode.WorkspaceFolder, kind: ArtifactKind): ArtifactsTreeNode[] {
    const groups = groupArtifacts(this.snapshotArtifacts(folder), readSortOrder(), readFilter());
    const group = groups.find((candidate) => candidate.kind === kind);
    return (group?.artifacts ?? []).map(
      (artifact) => ({ type: 'artifact', folder, artifact }) as const,
    );
  }
}

function buildRootTreeItem(folder: vscode.WorkspaceFolder): vscode.TreeItem {
  const item = new vscode.TreeItem(folder.name, vscode.TreeItemCollapsibleState.Expanded);
  item.id = `harnessNavigator.root:${folder.uri.toString()}`;
  item.iconPath = new vscode.ThemeIcon('root-folder');
  item.contextValue = 'harnessRootItem';
  return item;
}

function buildGroupTreeItem(folder: vscode.WorkspaceFolder, kind: ArtifactKind): vscode.TreeItem {
  // `kind` — canonical machine-token (STEP/REQ/ADR/OQ), не локализуется.
  const item = new vscode.TreeItem(kind, vscode.TreeItemCollapsibleState.Expanded);
  item.id = `harnessNavigator.group:${folder.uri.toString()}:${kind}`;
  item.iconPath = new vscode.ThemeIcon('layers');
  item.contextValue = 'harnessGroupItem';
  return item;
}

function readSortOrder(): SortOrder {
  const raw = vscode.workspace.getConfiguration(CONFIG_SECTION).get<string>('sortOrder', 'id');
  return (SORT_ORDERS as readonly string[]).includes(raw) ? (raw as SortOrder) : 'id';
}

/**
 * Читает filter workspace-wide (`scope: "window"` в `package.json`), без
 * resource/folder-семантики: `Harness: Set Filter`/`Harness: Clear Filters`
 * не выбирают root и пишут через `ConfigurationTarget.Workspace`, поэтому
 * чтение с resource-scope только создавало бы ложное впечатление per-root
 * изоляции, которого запись фактически не даёт (F-002 STEP REVIEW STEP-004).
 */
function readFilter(): ArtifactFilterState {
  const config = vscode.workspace.getConfiguration(CONFIG_SECTION);
  const filter: { -readonly [K in FilterField]?: string } = {};
  for (const field of FILTER_FIELDS) {
    const value = config.get<string | null>(`filter.${field}`, null);
    if (typeof value === 'string' && value.length > 0) filter[field] = value;
  }
  return filter;
}

const SORT_ORDER_LABELS: Readonly<Record<SortOrder, () => string>> = {
  id: () => vscode.l10n.t(VIEW_MESSAGES.sortOrderId),
  title: () => vscode.l10n.t(VIEW_MESSAGES.sortOrderTitle),
  status: () => vscode.l10n.t(VIEW_MESSAGES.sortOrderStatus),
  priority: () => vscode.l10n.t(VIEW_MESSAGES.sortOrderPriority),
};

const FILTER_FIELD_LABELS: Readonly<Record<FilterField, () => string>> = {
  status: () => vscode.l10n.t(VIEW_MESSAGES.filterFieldStatus),
  type: () => vscode.l10n.t(VIEW_MESSAGES.filterFieldType),
  priority: () => vscode.l10n.t(VIEW_MESSAGES.filterFieldPriority),
  phase: () => vscode.l10n.t(VIEW_MESSAGES.filterFieldPhase),
};

const FIELD_ENUM_VALUES: Readonly<Record<Exclude<FilterField, 'phase'>, readonly string[]>> = {
  status: STEP_STATUS_VALUES,
  type: STEP_TYPE_VALUES,
  priority: STEP_PRIORITY_VALUES,
};

/** `Harness: Set Sort Order` — записывает выбор только в workspace settings. */
export async function runSetSortOrder(): Promise<void> {
  const items = SORT_ORDERS.map((order) => ({ label: SORT_ORDER_LABELS[order](), order }));
  const picked = await vscode.window.showQuickPick(items, {
    placeHolder: vscode.l10n.t(VIEW_MESSAGES.sortOrderPlaceholder),
  });
  if (picked === undefined) return;
  await vscode.workspace
    .getConfiguration(CONFIG_SECTION)
    .update('sortOrder', picked.order, vscode.ConfigurationTarget.Workspace);
}

/**
 * `Harness: Set Filter` — выбирает поле и значение, затем пишет workspace
 * settings. Filter workspace-wide (не per-root, см. `readFilter`), поэтому
 * команда не спрашивает root: любой такой выбор был бы обманчив — запись
 * идёт через `ConfigurationTarget.Workspace` независимо от него (F-002).
 */
export async function runSetFilter(projectStates: ProjectStateService): Promise<void> {
  if (!hasValidFolder(projectStates)) {
    void vscode.window.showInformationMessage(vscode.l10n.t(VIEW_MESSAGES.noHarnessProject));
    return;
  }
  const fieldItems = FILTER_FIELDS.map((field) => ({ label: FILTER_FIELD_LABELS[field](), field }));
  const pickedField = await vscode.window.showQuickPick(fieldItems, {
    placeHolder: vscode.l10n.t(VIEW_MESSAGES.filterFieldPlaceholder),
  });
  if (pickedField === undefined) return;
  const picked = await pickFilterValue(pickedField.field);
  if (picked.cancelled) return;
  await vscode.workspace
    .getConfiguration(CONFIG_SECTION)
    .update(`filter.${pickedField.field}`, picked.value, vscode.ConfigurationTarget.Workspace);
}

/** `Harness: Clear Filters` — сбрасывает все четыре filter key, не трогая sort order. */
export async function runClearFilters(projectStates: ProjectStateService): Promise<void> {
  if (!hasValidFolder(projectStates)) {
    void vscode.window.showInformationMessage(vscode.l10n.t(VIEW_MESSAGES.noHarnessProject));
    return;
  }
  const config = vscode.workspace.getConfiguration(CONFIG_SECTION);
  for (const field of FILTER_FIELDS) {
    // `undefined` (не `null`) действительно удаляет ключ из settings JSON
    // вместо того, чтобы записать в него значение `null` (F-005).
    await config.update(`filter.${field}`, undefined, vscode.ConfigurationTarget.Workspace);
  }
}

function hasValidFolder(projectStates: ProjectStateService): boolean {
  return (vscode.workspace.workspaceFolders ?? []).some(
    (folder) => projectStates.getIndex(folder) !== undefined,
  );
}

/**
 * Результат выбора значения фильтра. `cancelled: true` — пользователь нажал
 * Escape, ничего писать не нужно. `value: undefined` (при `cancelled: false`)
 * — пользователь явно выбрал "Any"/оставил `phase` пустым, что означает
 * удаление ключа (`undefined`, не `null` — см. F-005), а не отмену.
 */
type FilterValuePick =
  { readonly cancelled: true } | { readonly cancelled: false; readonly value: string | undefined };

async function pickFilterValue(field: FilterField): Promise<FilterValuePick> {
  if (field === 'phase') {
    const input = await vscode.window.showInputBox({
      prompt: vscode.l10n.t(VIEW_MESSAGES.filterPhaseInputPrompt),
    });
    if (input === undefined) return { cancelled: true };
    const trimmed = input.trim();
    return { cancelled: false, value: trimmed.length === 0 ? undefined : trimmed };
  }
  const values = FIELD_ENUM_VALUES[field];
  const items: { label: string; value: string | undefined }[] = [
    { label: vscode.l10n.t(VIEW_MESSAGES.filterClearOption), value: undefined },
    ...values.map((value) => ({ label: value, value })),
  ];
  const picked = await vscode.window.showQuickPick(items, {
    placeHolder: vscode.l10n.t(VIEW_MESSAGES.filterValuePlaceholder, FILTER_FIELD_LABELS[field]()),
  });
  if (picked === undefined) return { cancelled: true };
  return { cancelled: false, value: picked.value };
}
