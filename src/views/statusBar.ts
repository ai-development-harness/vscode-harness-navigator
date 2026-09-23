import * as vscode from 'vscode';
import type { ProjectStateService } from '../projectModel/projectStateService';
import type { RootSummary } from './summaryModel';
import { collectSummary } from './summaryView';
import { VIEW_MESSAGES } from './viewMessages';

/** Открывает контейнер Harness View: навигация UI, не dispatch Harness-команды. */
export const OPEN_VIEW_COMMAND = 'workbench.view.extension.harnessNavigator';

export interface StatusBarSnapshot {
  readonly text: string;
  readonly tooltip: string;
  readonly command: string | undefined;
  readonly visible: boolean;
  readonly counts: {
    readonly active: number;
    readonly blocked: number;
    readonly openQuestions: number;
  };
}

/**
 * Один Status Bar item из общей сводки derived indexes. Использует ThemeIcon и
 * theme-цвета по умолчанию (никаких фиксированных цветов); скрыт только когда
 * все roots — NotHarnessProject; для non-valid Harness root показывает категорию.
 */
export class HarnessStatusBar implements vscode.Disposable {
  private readonly item: vscode.StatusBarItem;
  private readonly listener: vscode.Disposable;
  private visible = false;

  constructor(private readonly projectStates: ProjectStateService) {
    this.item = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 0);
    this.item.name = vscode.l10n.t(VIEW_MESSAGES.statusBarName);
    this.item.command = OPEN_VIEW_COMMAND;
    this.listener = projectStates.onDidChangeProjectModel(() => this.update());
    this.update();
  }

  snapshot(): StatusBarSnapshot {
    const { aggregate } = collectSummary(this.projectStates);
    return {
      text: this.item.text,
      tooltip: typeof this.item.tooltip === 'string' ? this.item.tooltip : '',
      command:
        typeof this.item.command === 'string' ? this.item.command : this.item.command?.command,
      visible: this.visible,
      counts: {
        active: aggregate.inProgress,
        blocked: aggregate.blocked,
        openQuestions: aggregate.openQuestions,
      },
    };
  }

  dispose(): void {
    this.listener.dispose();
    this.item.dispose();
  }

  private update(): void {
    const model = collectSummary(this.projectStates);
    const diagnosticRoots = model.roots.filter((root) => root.category !== 'NotHarnessProject');
    if (model.validRootCount === 0 && diagnosticRoots.length === 0) {
      this.item.hide();
      this.visible = false;
      this.item.text = '';
      this.item.tooltip = '';
      return;
    }
    const { aggregate } = model;
    const first = diagnosticRoots[0];
    this.item.text =
      model.validRootCount === 0 && first !== undefined
        ? `$(list-tree) ${vscode.l10n.t(VIEW_MESSAGES.statusBarTextCategory, first.category)}`
        : `$(list-tree) ${vscode.l10n.t(
            VIEW_MESSAGES.statusBarText,
            aggregate.inProgress,
            aggregate.blocked,
            aggregate.openQuestions,
          )}`;
    const labelOf = (root: RootSummary) =>
      model.roots.filter((other) => other.rootName === root.rootName).length > 1
        ? `${root.rootName} (${root.rootKey})`
        : root.rootName;
    const lines = model.roots
      .filter((root) => root.category !== 'NotHarnessProject')
      .map((root) =>
        root.kind !== 'valid'
          ? vscode.l10n.t(VIEW_MESSAGES.statusBarTooltipRootCategory, labelOf(root), root.category)
          : vscode.l10n.t(
              VIEW_MESSAGES.statusBarTooltipRoot,
              labelOf(root),
              root.release ?? '',
              root.counts.steps,
              root.counts.requirements,
              root.counts.adrs,
              root.counts.openQuestions,
              root.counts.diagnostics,
            ),
      );
    lines.push(vscode.l10n.t(VIEW_MESSAGES.statusBarTooltipHint));
    this.item.tooltip = lines.join('\n');
    this.item.show();
    this.visible = true;
  }
}
