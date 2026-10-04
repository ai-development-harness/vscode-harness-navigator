import { realpathSync, statSync } from 'node:fs';
import * as path from 'node:path';
import * as vscode from 'vscode';
import {
  presentDependencyGraph,
  type DependencyGraphPresentation,
} from './dependencyGraphPresentation';
import {
  dependencyGraphHtml,
  isDependencyGraphMessage,
  GRAPH_LABELS,
  type GraphLabels,
} from './dependencyGraphWebview';
import type { ProjectGraphService } from './projectStateService';

import { PROJECT_STATE_ERROR_MESSAGES } from './projectStateErrors';
export { PROJECT_STATE_ERROR_MESSAGES, PROJECT_STATE_ERROR_CATEGORIES } from './projectStateErrors';

/** Panel получает только presentation; open проверяет canonical path независимо от WebView. */
export class DependencyGraphPanel implements vscode.Disposable {
  private readonly panel: vscode.WebviewPanel;
  private focusId: string | undefined;
  private selectedId: string | undefined;
  private readonly disposables: vscode.Disposable[] = [];
  private disposed = false;
  private initialized = false;
  // Revision отличает внешний reveal от echo selection и обычного refresh.
  private navigationRevision = 0;
  private model: DependencyGraphPresentation = {
    state: 'error',
    nodes: [],
    edges: [],
    longestDependencyChain: undefined,
  };
  constructor(
    private readonly folder: vscode.WorkspaceFolder,
    private readonly graphs: ProjectGraphService,
    focusId?: string,
    onClose?: () => void,
  ) {
    this.focusId = focusId;
    this.selectedId = focusId;
    this.panel = vscode.window.createWebviewPanel(
      'harnessNavigator.dependencyGraph',
      `${vscode.l10n.t('Dependency Graph')} · ${folder.name}`,
      vscode.ViewColumn.Active,
      { enableScripts: true, retainContextWhenHidden: true, localResourceRoots: [] },
    );
    this.disposables.push(
      this.panel.webview.onDidReceiveMessage((message: unknown) => {
        void this.handleMessage(message).catch(() =>
          vscode.window.showWarningMessage(vscode.l10n.t('Project State artifact is unavailable.')),
        );
      }),
      this.panel.onDidDispose(() => {
        this.dispose();
        onClose?.();
      }),
      graphs.onDidChange((changed) => {
        if (changed.uri.toString() === folder.uri.toString()) this.render();
      }),
    );
    this.render();
    if (graphs.get(folder) === undefined) void graphs.refresh(folder);
  }
  reveal(focusId?: string): void {
    this.navigationRevision++;
    this.focusId = focusId;
    this.selectedId = focusId;
    this.panel.reveal();
    this.render();
  }
  getSnapshot() {
    return { title: this.panel.title, model: this.model, html: this.panel.webview.html };
  }
  dispose(): void {
    if (this.disposed) return;
    this.disposed = true;
    for (const disposable of this.disposables.splice(0).reverse()) disposable.dispose();
    this.panel.dispose();
  }
  private render(): void {
    if (this.disposed) return;
    const snapshot = this.graphs.get(this.folder) ?? { kind: 'error' as const, error: 'loading' };
    const model = presentDependencyGraph(snapshot, this.focusId);
    this.model = {
      ...model,
      navigationRevision: this.navigationRevision,
      ...(this.selectedId === undefined ? {} : { selectedId: this.selectedId }),
      ...(model.error === undefined
        ? {}
        : {
            error: vscode.l10n.t(
              PROJECT_STATE_ERROR_MESSAGES[model.error] ?? 'Project State API process failed.',
            ),
          }),
    };
    if (!this.initialized) {
      const labels = Object.fromEntries(
        Object.entries(GRAPH_LABELS).map(([k, v]) => [k, vscode.l10n.t(v)]),
      ) as GraphLabels;
      this.panel.webview.html = dependencyGraphHtml(
        this.panel.webview,
        this.model,
        labels,
        this.folder.name,
      );
      this.initialized = true;
    } else void this.panel.webview.postMessage({ type: 'model', model: this.model });
  }
  /** Этот же валидатор используется runtime и read-only integration seam. */
  async handleMessage(message: unknown): Promise<void> {
    if (this.disposed || !isDependencyGraphMessage(message)) return;
    if (message.type === 'refresh') {
      await this.graphs.refresh(this.folder);
      return;
    }
    if (message.type === 'reset') {
      this.focusId = undefined;
      this.selectedId = undefined;
      this.render();
      return;
    }
    if (message.type === 'fit') return;
    if (!('id' in message)) return;
    const nodeId = message.id;
    const node = this.graphs.get(this.folder)?.payload?.graph.nodes.find((n) => n.id === nodeId);
    if (!node) return;
    if (message.type === 'select' || message.type === 'related') {
      this.selectedId = message.id;
      if (message.type === 'related') this.focusId = message.id;
      this.render();
      return;
    }
    if (node.type === 'MISSING' || !node.path || path.isAbsolute(node.path)) return;
    const root = realpathSync(this.folder.uri.fsPath),
      target = realpathSync(path.resolve(root, node.path));
    const relative = path.relative(root, target);
    if (
      relative === '..' ||
      relative.startsWith(`..${path.sep}`) ||
      path.isAbsolute(relative) ||
      !statSync(target).isFile()
    )
      return;
    await vscode.commands.executeCommand('vscode.open', vscode.Uri.file(target));
  }
}
