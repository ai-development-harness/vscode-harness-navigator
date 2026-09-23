import * as vscode from 'vscode';
import { selectFocusArtifacts, type FocusSelection } from './artifactViewModel';
import { buildArtifactTreeItem, type ArtifactLeafNode } from './artifactTreeItem';
import { VIEW_MESSAGES } from './viewMessages';
import type { Artifact } from '../projectModel/artifactIndex';
import type { ProjectStateService } from '../projectModel/projectStateService';

type FocusGroupKey = 'active' | 'blocked' | 'openQuestions';

const FOCUS_GROUP_ORDER: readonly FocusGroupKey[] = ['active', 'blocked', 'openQuestions'];

const FOCUS_GROUP_LABELS: Readonly<Record<FocusGroupKey, () => string>> = {
  active: () => vscode.l10n.t(VIEW_MESSAGES.focusActiveGroup),
  blocked: () => vscode.l10n.t(VIEW_MESSAGES.focusBlockedGroup),
  openQuestions: () => vscode.l10n.t(VIEW_MESSAGES.focusOpenQuestionsGroup),
};

type FocusTreeNode =
  | { readonly type: 'root'; readonly folder: vscode.WorkspaceFolder }
  | {
      readonly type: 'group';
      readonly folder: vscode.WorkspaceFolder;
      readonly group: FocusGroupKey;
    }
  | ArtifactLeafNode;

/**
 * `vscode.TreeDataProvider` для Harness Focus View. Показывает active
 * (`in_progress`) STEP, blocked STEP и open OQ через тот же
 * `selectFocusArtifacts` view model, что уже покрыт unit tests — никакого
 * ранжирования или выбора «следующего шага»: порядок групп фиксирован, а
 * внутри группы — по ID (mutation policy STEP-004, forbidden: "выбор
 * следующего STEP за пользователя").
 */
export class FocusTreeDataProvider
  implements vscode.TreeDataProvider<FocusTreeNode>, vscode.Disposable
{
  private readonly changeEmitter = new vscode.EventEmitter<void>();
  readonly onDidChangeTreeData = this.changeEmitter.event;
  private readonly listener: vscode.Disposable;

  constructor(private readonly projectStates: ProjectStateService) {
    this.listener = projectStates.onDidChangeProjectModel(() => this.changeEmitter.fire());
  }

  getTreeItem(element: FocusTreeNode): vscode.TreeItem {
    switch (element.type) {
      case 'root':
        return buildFocusRootTreeItem(element.folder);
      case 'group':
        return buildFocusGroupTreeItem(element.folder, element.group);
      case 'artifact':
        return buildArtifactTreeItem(element.folder, element.artifact);
    }
  }

  getChildren(element?: FocusTreeNode): FocusTreeNode[] {
    const folders = this.validFolders();
    if (element === undefined) {
      if (folders.length > 1) return folders.map((folder) => ({ type: 'root', folder }) as const);
      const only = folders[0];
      return only === undefined ? [] : this.groupsFor(only);
    }
    if (element.type === 'root') return this.groupsFor(element.folder);
    if (element.type === 'group') {
      const selection = this.selectionFor(element.folder);
      return groupArtifactsFor(selection, element.group).map(
        (artifact) => ({ type: 'artifact', folder: element.folder, artifact }) as const,
      );
    }
    return [];
  }

  /**
   * Локализованное сообщение для `TreeView.message`, когда ни у одного valid
   * root нет ни одного focus artifact. `''` (не `undefined`) означает
   * "нет message" — см. `ArtifactsTreeDataProvider.computeMessage`.
   */
  computeMessage(): string {
    const folders = this.validFolders();
    if (folders.length === 0) return vscode.l10n.t(VIEW_MESSAGES.noHarnessProject);
    const total = folders.reduce((sum, folder) => sum + this.totalFor(folder), 0);
    return total === 0 ? vscode.l10n.t(VIEW_MESSAGES.focusEmpty) : '';
  }

  dispose(): void {
    this.listener.dispose();
    this.changeEmitter.dispose();
  }

  private validFolders(): vscode.WorkspaceFolder[] {
    return (vscode.workspace.workspaceFolders ?? []).filter(
      (folder) => this.projectStates.getIndex(folder) !== undefined,
    );
  }

  private selectionFor(folder: vscode.WorkspaceFolder): FocusSelection {
    return selectFocusArtifacts(this.projectStates.getIndex(folder)?.snapshot().artifacts ?? []);
  }

  private totalFor(folder: vscode.WorkspaceFolder): number {
    const selection = this.selectionFor(folder);
    return (
      selection.activeSteps.length + selection.blockedSteps.length + selection.openQuestions.length
    );
  }

  private groupsFor(folder: vscode.WorkspaceFolder): FocusTreeNode[] {
    const selection = this.selectionFor(folder);
    return FOCUS_GROUP_ORDER.filter((group) => groupArtifactsFor(selection, group).length > 0).map(
      (group) => ({ type: 'group', folder, group }) as const,
    );
  }
}

function groupArtifactsFor(selection: FocusSelection, group: FocusGroupKey): readonly Artifact[] {
  switch (group) {
    case 'active':
      return selection.activeSteps;
    case 'blocked':
      return selection.blockedSteps;
    case 'openQuestions':
      return selection.openQuestions;
  }
}

function buildFocusRootTreeItem(folder: vscode.WorkspaceFolder): vscode.TreeItem {
  const item = new vscode.TreeItem(folder.name, vscode.TreeItemCollapsibleState.Expanded);
  item.id = `harnessNavigator.focusRoot:${folder.uri.toString()}`;
  item.iconPath = new vscode.ThemeIcon('root-folder');
  item.contextValue = 'harnessRootItem';
  return item;
}

function buildFocusGroupTreeItem(
  folder: vscode.WorkspaceFolder,
  group: FocusGroupKey,
): vscode.TreeItem {
  const item = new vscode.TreeItem(
    FOCUS_GROUP_LABELS[group](),
    vscode.TreeItemCollapsibleState.Expanded,
  );
  item.id = `harnessNavigator.focusGroup:${folder.uri.toString()}:${group}`;
  item.iconPath = new vscode.ThemeIcon('layers');
  item.contextValue = 'harnessGroupItem';
  return item;
}
