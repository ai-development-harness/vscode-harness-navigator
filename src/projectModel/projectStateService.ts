import * as vscode from 'vscode';
import { detectProject } from './manifestService';
import { ArtifactIndex, handleArtifactWatcherEvent } from './artifactIndex';
import type {
  ConfiguredPaths,
  ProjectDiagnostic,
  ProjectState,
  ValidProjectState,
} from './projectState';

/** Внешний источник diagnostics для valid root (например Command Catalog). */
export type DiagnosticSource = (folder: vscode.WorkspaceFolder) => readonly ProjectDiagnostic[];

/**
 * Хранит только производные in-memory результаты detection, разделённые по
 * URI workspace root. Команда показывает эти результаты через Output Channel
 * и никогда не запускает Harness либо не меняет файлы workspace.
 */
export class ProjectStateService implements vscode.Disposable {
  private readonly states = new Map<string, ProjectState>();
  private readonly indexes = new Map<string, ArtifactIndex>();
  private readonly manifestWatchers = new Map<string, vscode.FileSystemWatcher>();
  private readonly artifactWatchers = new Map<string, vscode.FileSystemWatcher[]>();
  private readonly diagnosticSources = new Set<DiagnosticSource>();
  private readonly projectModelChangeEmitter = new vscode.EventEmitter<void>();

  /**
   * Единственный сигнал "derived project model устарела": срабатывает в
   * конце `refreshRoot` (после manifest re-detect и, при valid state, после
   * `ArtifactIndex.rebuild`) и после `handleArtifactWatcherEvent` внутри
   * artifact watcher-а. Views подписываются на него, чтобы перерисовать Tree
   * View без собственного parsing — единственный источник данных остаётся
   * `getIndex(folder)?.snapshot()`/`this.all`.
   */
  readonly onDidChangeProjectModel: vscode.Event<void> = this.projectModelChangeEmitter.event;

  constructor(
    workspaceFolders: readonly vscode.WorkspaceFolder[] | undefined,
    private readonly output: vscode.OutputChannel,
  ) {
    for (const folder of workspaceFolders ?? []) this.addRoot(folder);
  }

  /**
   * Подключает workspace root во время работы (без restart): detect,
   * index и manifest watcher проходят тот же путь, что и при activation.
   */
  addRoot(folder: vscode.WorkspaceFolder): void {
    const key = folder.uri.toString();
    if (this.manifestWatchers.has(key)) return;
    this.refreshRoot(folder);
    // Manifest наблюдается для каждого root, включая invalid/non-Harness.
    // Это позволяет перейти к valid state без перезапуска Extension Host.
    const watcher = vscode.workspace.createFileSystemWatcher(
      new vscode.RelativePattern(folder, '.harness/manifest.yaml'),
    );
    // Запоздавшее событие уже удалённого root не должно воскресить его state.
    const onManifestEvent = () => {
      if (this.manifestWatchers.has(key)) this.refreshRoot(folder);
    };
    watcher.onDidCreate(onManifestEvent);
    watcher.onDidChange(onManifestEvent);
    watcher.onDidDelete(onManifestEvent);
    this.manifestWatchers.set(key, watcher);
  }

  /** Read-only: число живых watchers root (manifest + artifact) для test seam. */
  getWatcherCount(folder: vscode.WorkspaceFolder): number {
    const key = folder.uri.toString();
    return (this.manifestWatchers.has(key) ? 1 : 0) + (this.artifactWatchers.get(key)?.length ?? 0);
  }

  /** Освобождает state, index и все watchers удалённого workspace root. */
  removeRoot(folder: vscode.WorkspaceFolder): void {
    const key = folder.uri.toString();
    this.manifestWatchers.get(key)?.dispose();
    this.manifestWatchers.delete(key);
    for (const watcher of this.artifactWatchers.get(key) ?? []) watcher.dispose();
    this.artifactWatchers.delete(key);
    this.states.delete(key);
    this.indexes.delete(key);
    this.projectModelChangeEmitter.fire();
  }

  get all(): readonly ProjectState[] {
    return [...this.states.values()];
  }

  /**
   * Пересобирает только derived state текущего root и не изменяет workspace.
   *
   * F-013: artifact watchers пересоздаются только когда root переходит в
   * valid state впервые либо когда фактически меняются configured paths.
   * Иначе уже существующие watchers (созданные на activation или на
   * предыдущем valid refresh) остаются нетронутыми — они гарантированно уже
   * "ready" к моменту следующего file change, в отличие от watcher,
   * пересозданного за миллисекунды до правки того же файла. Явный
   * `Harness: Refresh`, вызванный по всем root сразу, поэтому больше не
   * вносит гонку для root, у которого ничего не изменилось.
   */
  refreshRoot(folder: vscode.WorkspaceFolder): void {
    const key = folder.uri.toString();
    const previous = this.states.get(key);
    const project = detectProject(folder.uri.fsPath);
    this.states.set(key, project);
    if (project.kind !== 'valid') {
      for (const watcher of this.artifactWatchers.get(key) ?? []) watcher.dispose();
      this.artifactWatchers.delete(key);
      this.indexes.delete(key);
      this.projectModelChangeEmitter.fire();
      return;
    }
    const index = new ArtifactIndex();
    index.rebuild(project);
    this.indexes.set(key, index);
    const previousValid = previous?.kind === 'valid' ? previous : undefined;
    const watchersReusable =
      previousValid !== undefined &&
      this.artifactWatchers.has(key) &&
      configuredPathsEqual(previousValid.configuredPaths, project.configuredPaths);
    if (!watchersReusable) {
      for (const watcher of this.artifactWatchers.get(key) ?? []) watcher.dispose();
      this.createArtifactWatcher(folder, project);
    }
    this.projectModelChangeEmitter.fire();
  }

  getState(folder: vscode.WorkspaceFolder): ProjectState | undefined {
    return this.states.get(folder.uri.toString());
  }

  getIndex(folder: vscode.WorkspaceFolder): ArtifactIndex | undefined {
    return this.indexes.get(folder.uri.toString());
  }

  /**
   * Подключает внешний источник diagnostics. Он вызывается только для valid
   * roots и не влияет на `ProjectState`/ArtifactIndex.
   */
  registerDiagnosticSource(source: DiagnosticSource): vscode.Disposable {
    this.diagnosticSources.add(source);
    return new vscode.Disposable(() => {
      this.diagnosticSources.delete(source);
    });
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
    for (const [root, index] of this.indexes) {
      for (const item of index.snapshot().diagnostics) {
        const explanation = vscode.l10n.t(item.message, ...item.messageArguments);
        const line = `${root}: ${item.category} — ${explanation}`;
        this.output.appendLine(line);
        lines.push(line);
      }
    }
    for (const folder of vscode.workspace.workspaceFolders ?? []) {
      if (this.getState(folder)?.kind !== 'valid') continue;
      for (const source of this.diagnosticSources) {
        for (const item of source(folder)) {
          const explanation = vscode.l10n.t(item.message, ...item.messageArguments);
          const line = `${folder.uri.toString()}: ${item.category} — ${explanation}`;
          this.output.appendLine(line);
          lines.push(line);
        }
      }
    }
    this.output.show(true);
    return { states, summary, lines };
  }

  dispose(): void {
    this.disposeArtifactWatchers();
    for (const watcher of this.manifestWatchers.values()) watcher.dispose();
    this.manifestWatchers.clear();
    this.states.clear();
    this.indexes.clear();
    this.diagnosticSources.clear();
    this.projectModelChangeEmitter.dispose();
  }

  private createArtifactWatcher(folder: vscode.WorkspaceFolder, project: ValidProjectState): void {
    const update = (uri: vscode.Uri) => {
      const index = this.indexes.get(folder.uri.toString());
      if (index !== undefined) handleArtifactWatcherEvent(index, project, uri.fsPath);
      this.projectModelChangeEmitter.fire();
    };
    // Единственный recursive watcher на весь workspace root покрывает те же
    // Markdown-файлы, что и любой набор per-directory паттернов, потому что
    // каждый configured каталог — подкаталог root. Отдельные per-directory
    // watchers избыточны (полностью перекрываются этим `**/*.md`) и только
    // увеличивают число native watch handles без добавления coverage;
    // точность фильтрации остаётся за `isHarnessAwareMarkdown` внутри
    // `updatePath`, а не за глобом watcher-а.
    const watcher = vscode.workspace.createFileSystemWatcher(
      new vscode.RelativePattern(folder, '**/*.md'),
    );
    watcher.onDidCreate(update);
    watcher.onDidChange(update);
    watcher.onDidDelete(update);
    this.artifactWatchers.set(folder.uri.toString(), [watcher]);
  }

  private disposeArtifactWatchers(): void {
    for (const watchers of this.artifactWatchers.values())
      for (const watcher of watchers) watcher.dispose();
    this.artifactWatchers.clear();
  }
}

/** Структурное сравнение configured paths для решения о переиспользовании watchers. */
function configuredPathsEqual(left: ConfiguredPaths, right: ConfiguredPaths): boolean {
  return (Object.keys(left) as (keyof ConfiguredPaths)[]).every((key) => left[key] === right[key]);
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
