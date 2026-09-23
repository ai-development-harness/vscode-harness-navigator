import * as vscode from 'vscode';
import type { ProjectStateService } from '../projectModel/projectStateService';
import { buildSummaryModel, type RootSummary, type SummaryModel } from './summaryModel';
import { VIEW_MESSAGES } from './viewMessages';

/** Собирает сводку из общих derived indexes: единственный источник — ProjectStateService. */
export function collectSummary(projectStates: ProjectStateService): SummaryModel {
  const inputs = [];
  for (const folder of vscode.workspace.workspaceFolders ?? []) {
    const state = projectStates.getState(folder);
    if (state === undefined) continue;
    inputs.push({
      rootName: folder.name,
      rootKey: folder.uri.toString(),
      state,
      snapshot: projectStates.getIndex(folder)?.snapshot(),
    });
  }
  return buildSummaryModel(inputs);
}

export type SummaryTreeNode =
  | { readonly type: 'root'; readonly root: RootSummary }
  | { readonly type: 'item'; readonly id: string; readonly label: string; readonly value: string };

/**
 * Нативный read-only Tree View «Project Summary»: без WebView, без
 * `TreeItem.command`, только derived counts (REQ-009). Не выбирает
 * «следующий STEP» и не предлагает действий.
 */
export class SummaryTreeDataProvider
  implements vscode.TreeDataProvider<SummaryTreeNode>, vscode.Disposable
{
  private readonly changeEmitter = new vscode.EventEmitter<void>();
  readonly onDidChangeTreeData = this.changeEmitter.event;
  private readonly listener: vscode.Disposable;

  constructor(private readonly projectStates: ProjectStateService) {
    this.listener = projectStates.onDidChangeProjectModel(() => this.changeEmitter.fire());
  }

  getTreeItem(element: SummaryTreeNode): vscode.TreeItem {
    if (element.type === 'root') {
      const item = new vscode.TreeItem(
        element.root.rootName,
        vscode.TreeItemCollapsibleState.Expanded,
      );
      item.id = `harnessNavigator.summaryRoot:${element.root.rootKey}`;
      item.iconPath = new vscode.ThemeIcon('root-folder');
      item.contextValue = 'harnessSummaryRoot';
      return item;
    }
    const item = new vscode.TreeItem(element.label, vscode.TreeItemCollapsibleState.None);
    item.id = element.id;
    item.description = element.value;
    item.contextValue = 'harnessSummaryItem';
    return item;
  }

  getChildren(element?: SummaryTreeNode): SummaryTreeNode[] {
    const model = collectSummary(this.projectStates);
    if (element === undefined) {
      if (model.roots.length > 1)
        return model.roots.map((root) => ({ type: 'root', root }) as const);
      const only = model.roots[0];
      return only === undefined ? [] : this.itemsFor(only, '');
    }
    if (element.type === 'root') return this.itemsFor(element.root, element.root.rootKey);
    return [];
  }

  computeMessage(): string {
    const model = collectSummary(this.projectStates);
    return model.roots.length === 0 ? vscode.l10n.t(VIEW_MESSAGES.noHarnessProject) : '';
  }

  dispose(): void {
    this.listener.dispose();
    this.changeEmitter.dispose();
  }

  private itemsFor(root: RootSummary, scope: string): SummaryTreeNode[] {
    const id = (key: string) => `harnessNavigator.summaryItem:${scope}:${key}`;
    if (root.kind !== 'valid') {
      // Non-valid root показывает stable category и локализованное объяснение.
      return [
        {
          type: 'item',
          id: id('category'),
          label: root.category,
          value: vscode.l10n.t(root.explanation, ...root.explanationArguments),
        },
      ];
    }
    const { counts } = root;
    const items: [string, string, number | string][] = [
      ['release', vscode.l10n.t(VIEW_MESSAGES.summaryRelease), root.release ?? ''],
      ['step', 'STEP', counts.steps],
      ['req', 'REQ', counts.requirements],
      ['adr', 'ADR', counts.adrs],
      ['oq', vscode.l10n.t(VIEW_MESSAGES.summaryOpenQuestions), counts.openQuestions],
      ['active', vscode.l10n.t(VIEW_MESSAGES.summaryInProgress), counts.inProgress],
      ['blocked', vscode.l10n.t(VIEW_MESSAGES.summaryBlocked), counts.blocked],
      ['diagnostics', vscode.l10n.t(VIEW_MESSAGES.summaryDiagnostics), counts.diagnostics],
    ];
    return items.map(([key, label, value]) => ({
      type: 'item',
      id: id(key),
      label,
      value: String(value),
    }));
  }
}
