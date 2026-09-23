import * as vscode from 'vscode';
import type { ProjectStateService } from '../projectModel/projectStateService';
import type { ProjectDiagnostic } from '../projectModel/projectState';
import { COMMAND_GRAPH_RELATIVE_PATH, loadCatalogForRoot, type CatalogState } from './commandGraph';

/**
 * Per-root Command Catalog. Хранит только производное in-memory состояние
 * command graph и наблюдает один файл графа на каждый valid root. Ошибки
 * изолированы в состоянии своего root и не влияют на ArtifactIndex/Views.
 * Ничего не выполняет и не пишет в workspace.
 */
export class CommandCatalogService implements vscode.Disposable {
  private readonly states = new Map<string, CatalogState>();
  private readonly signatures = new Map<string, string>();
  private readonly watchers = new Map<string, vscode.FileSystemWatcher>();
  private readonly changeEmitter = new vscode.EventEmitter<void>();
  private readonly subscription: vscode.Disposable;

  readonly onDidChangeCatalog: vscode.Event<void> = this.changeEmitter.event;

  constructor(
    private readonly projectStates: ProjectStateService,
    private readonly output: vscode.OutputChannel,
  ) {
    // Граф перечитывается на каждом обновлении project model: это же событие
    // срабатывает в конце `refreshRoot`, поэтому `Harness: Refresh` восстанавливает
    // каталог даже при недоставленном событии watcher.
    this.subscription = projectStates.onDidChangeProjectModel(() => this.sync());
    this.sync();
  }

  getCatalog(folder: vscode.WorkspaceFolder): CatalogState | undefined {
    return this.states.get(folder.uri.toString());
  }

  /** Diagnostics каталога для общего diagnostics flow (только valid roots). */
  diagnosticsFor(folder: vscode.WorkspaceFolder): readonly ProjectDiagnostic[] {
    return this.getCatalog(folder)?.diagnostics ?? [];
  }

  dispose(): void {
    this.subscription.dispose();
    for (const watcher of this.watchers.values()) watcher.dispose();
    this.watchers.clear();
    this.states.clear();
    this.signatures.clear();
    this.changeEmitter.dispose();
  }

  private sync(): void {
    try {
      const seen = new Set<string>();
      let changed = false;
      for (const folder of vscode.workspace.workspaceFolders ?? []) {
        const key = folder.uri.toString();
        if (this.projectStates.getState(folder)?.kind !== 'valid') continue;
        seen.add(key);
        this.ensureWatcher(folder);
        if (this.load(folder)) changed = true;
      }
      for (const key of [...this.states.keys()]) {
        if (seen.has(key)) continue;
        this.states.delete(key);
        this.signatures.delete(key);
        this.watchers.get(key)?.dispose();
        this.watchers.delete(key);
        changed = true;
      }
      if (changed) this.changeEmitter.fire();
    } catch (error) {
      this.logFailure(error);
    }
  }

  private ensureWatcher(folder: vscode.WorkspaceFolder): void {
    const key = folder.uri.toString();
    if (this.watchers.has(key)) return;
    const watcher = vscode.workspace.createFileSystemWatcher(
      new vscode.RelativePattern(folder, COMMAND_GRAPH_RELATIVE_PATH),
    );
    const reload = () => {
      try {
        if (this.projectStates.getState(folder)?.kind !== 'valid') return;
        if (this.load(folder)) this.changeEmitter.fire();
      } catch (error) {
        this.logFailure(error);
      }
    };
    watcher.onDidCreate(reload);
    watcher.onDidChange(reload);
    watcher.onDidDelete(reload);
    this.watchers.set(key, watcher);
  }

  /** Перечитывает граф root; возвращает true, если наблюдаемое состояние изменилось. */
  private load(folder: vscode.WorkspaceFolder): boolean {
    const key = folder.uri.toString();
    const state = loadCatalogForRoot(folder.uri.fsPath);
    const signature = JSON.stringify(state);
    if (this.signatures.get(key) === signature) return false;
    this.states.set(key, state);
    this.signatures.set(key, signature);
    if (state.kind !== 'ready')
      this.output.appendLine(
        `${key}: ${state.diagnostics.map((item) => item.category).join(', ')}`,
      );
    return true;
  }

  private logFailure(error: unknown): void {
    this.output.appendLine(
      `Command catalog refresh failed: ${error instanceof Error ? error.name : 'unknown error'}`,
    );
  }
}
