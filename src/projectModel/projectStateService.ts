import * as vscode from 'vscode';
import { detectProject } from './manifestService';
import type { ProjectState } from './projectState';

/**
 * Хранит только производные in-memory результаты detection, разделённые по
 * URI workspace root. Команда показывает эти результаты через Output Channel
 * и никогда не запускает Harness либо не меняет файлы workspace.
 */
export class ProjectStateService implements vscode.Disposable {
  private readonly states = new Map<string, ProjectState>();

  constructor(
    workspaceFolders: readonly vscode.WorkspaceFolder[] | undefined,
    private readonly output: vscode.OutputChannel,
  ) {
    for (const folder of workspaceFolders ?? []) {
      this.states.set(folder.uri.toString(), detectProject(folder.uri.fsPath));
    }
  }

  get all(): readonly ProjectState[] {
    return [...this.states.values()];
  }

  showDiagnostics(): DiagnosticsReport {
    const states = this.all;
    const summary = vscode.l10n.t(
      'Harness Navigator diagnostics: {0} workspace roots inspected.',
      states.length,
    );
    this.output.appendLine(summary);
    const lines = states.map((projectState) => {
      const explanation = vscode.l10n.t(
        projectState.diagnostic.message,
        ...projectState.diagnostic.messageArguments,
      );
      const technicalDetail = projectState.diagnostic.detail;
      const line = `${projectState.workspaceRoot}: ${projectState.diagnostic.category} — ${explanation}${technicalDetail === '' ? '' : ` (${technicalDetail})`}`;
      this.output.appendLine(line);
      return line;
    });
    this.output.show(true);
    return { states, summary, lines };
  }

  dispose(): void {
    this.states.clear();
  }
}

/**
 * Команда возвращает уже выведенные локализованные строки, чтобы Extension Host
 * test мог проверить тот же наблюдаемый текст, который получает пользователь.
 */
export interface DiagnosticsReport {
  readonly states: readonly ProjectState[];
  readonly summary: string;
  readonly lines: readonly string[];
}
