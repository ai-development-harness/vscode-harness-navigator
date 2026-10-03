import type * as vscode from 'vscode';
import { parseProjectStatePayload, type ProjectStatePayload } from './projectStatePayload';
import { ProjectStateProcess, type ProjectStateProcessResult } from './projectStateProcess';

export interface ProjectGraphSnapshot {
  readonly kind: 'ready' | 'untrusted' | 'error';
  readonly payload?: ProjectStatePayload;
  readonly error?: string;
}
interface GraphServiceOptions {
  readonly process?: {
    run(root: string, signal?: AbortSignal): Promise<ProjectStateProcessResult>;
  };
  readonly isTrusted?: () => boolean;
  readonly configurationError?: (folder: vscode.WorkspaceFolder) => string | undefined;
  readonly debounceMs?: number;
}

/** Per-root cache не зависит от ArtifactIndex: unavailable API остаётся явной ошибкой. */
export class ProjectGraphService implements vscode.Disposable {
  private readonly snapshots = new Map<string, ProjectGraphSnapshot>();
  private readonly requests = new Map<string, AbortController>();
  private readonly pending = new Map<string, Promise<ProjectGraphSnapshot>>();
  private readonly timers = new Map<string, ReturnType<typeof setTimeout>>();
  private readonly listeners = new Set<(folder: vscode.WorkspaceFolder) => void>();
  private disposed = false;
  readonly onDidChange: vscode.Event<vscode.WorkspaceFolder> = (
    listener,
    thisArgs,
    disposables,
  ) => {
    const bound = (folder: vscode.WorkspaceFolder) => {
      listener.call(thisArgs, folder);
    };
    this.listeners.add(bound);
    const disposable = {
      dispose: () => {
        this.listeners.delete(bound);
      },
    };
    disposables?.push(disposable);
    return disposable;
  };
  constructor(private readonly options: GraphServiceOptions = {}) {}
  get(folder: vscode.WorkspaceFolder) {
    return this.snapshots.get(folder.uri.toString());
  }

  refresh(folder: vscode.WorkspaceFolder): Promise<ProjectGraphSnapshot> {
    const key = folder.uri.toString();
    const timer = this.timers.get(key);
    if (timer) clearTimeout(timer);
    this.timers.delete(key);
    this.requests.get(key)?.abort();
    const controller = new AbortController();
    this.requests.set(key, controller);
    const previous = this.pending.get(key);
    const current = (async (): Promise<ProjectGraphSnapshot> => {
      if (previous) await previous;
      if (controller.signal.aborted || this.disposed) return { kind: 'error', error: 'cancelled' };
      let snapshot: ProjectGraphSnapshot;
      // Любой entry point, включая WebView и debounce, проверяет текущий manifest перед process.
      // Blocker нельзя снять простым refresh после перехода root в unsupported/invalid state.
      const configurationError = this.options.configurationError?.(folder);
      if (!this.options.isTrusted?.()) snapshot = { kind: 'untrusted', error: 'untrusted' };
      else if (configurationError) snapshot = { kind: 'error', error: configurationError };
      else {
        const result = await (this.options.process ?? new ProjectStateProcess()).run(
          folder.uri.fsPath,
          controller.signal,
        );
        if (result.kind === 'success') {
          try {
            const parsed = parseProjectStatePayload(JSON.parse(result.stdout) as unknown);
            snapshot =
              parsed.kind === 'valid'
                ? { kind: 'ready', payload: parsed.payload }
                : { kind: 'error', error: parsed.reason };
          } catch {
            snapshot = { kind: 'error', error: 'malformed' };
          }
        } else {
          // Настоящий API возвращает BLOCKED JSON вместе с exit 1; прочие nonzero не дают ready.
          let blocked = false;
          if (result.reason === 'processError' && result.stdout) {
            try {
              const parsed = parseProjectStatePayload(JSON.parse(result.stdout) as unknown);
              blocked = parsed.kind === 'invalid' && parsed.reason === 'blocked';
            } catch {
              /* Непарсящийся nonzero остаётся processError. */
            }
          }
          snapshot = { kind: 'error', error: blocked ? 'blocked' : result.reason };
        }
      }
      if (this.requests.get(key) === controller && !this.disposed && !controller.signal.aborted) {
        this.snapshots.set(key, snapshot);
        this.requests.delete(key);
        for (const listener of this.listeners) listener(folder);
      }
      return snapshot;
    })();
    this.pending.set(key, current);
    void current.finally(() => {
      if (this.pending.get(key) === current) this.pending.delete(key);
    });
    return current;
  }

  /** Burst changes отменяют устаревший child сразу, новый запуск идёт после debounce/close. */
  invalidate(folder: vscode.WorkspaceFolder): void {
    if (this.disposed) return;
    const key = folder.uri.toString();
    this.requests.get(key)?.abort();
    const timer = this.timers.get(key);
    if (timer) clearTimeout(timer);
    this.timers.set(
      key,
      setTimeout(() => {
        this.timers.delete(key);
        void this.refresh(folder);
      }, this.options.debounceMs ?? 250),
    );
  }
  removeRoot(folder: vscode.WorkspaceFolder): void {
    const key = folder.uri.toString();
    this.requests.get(key)?.abort();
    this.requests.delete(key);
    const timer = this.timers.get(key);
    if (timer) clearTimeout(timer);
    this.timers.delete(key);
    this.snapshots.delete(key);
  }
  /** Изменённый/unsupported manifest сразу убирает старый graph из открытого panel. */
  blockRoot(folder: vscode.WorkspaceFolder, error: string): void {
    this.removeRoot(folder);
    if (this.disposed) return;
    this.snapshots.set(folder.uri.toString(), { kind: 'error', error });
    for (const listener of this.listeners) listener(folder);
  }
  dispose(): void {
    this.disposed = true;
    for (const request of this.requests.values()) request.abort();
    for (const timer of this.timers.values()) clearTimeout(timer);
    this.requests.clear();
    this.timers.clear();
    this.snapshots.clear();
    this.listeners.clear();
  }
}
