import * as assert from 'node:assert/strict';
import * as path from 'node:path';
import * as vscode from 'vscode';
import { originalFs } from './originalApis';

export const EXTENSION_ID = 'ai-development-harness.vscode-harness-navigator';

export const isRussian = (): boolean => vscode.env.language.toLowerCase().startsWith('ru');

/** Структурная форма `TreeNodeSnapshot` / `CommandNodeSnapshot` из `src/extension.ts`. */
export interface TreeNodeSnapshotLike {
  readonly id?: string | undefined;
  readonly label: string;
  readonly description: string | undefined;
  readonly contextValue: string | undefined;
  readonly resourceFsPath?: string | undefined;
  readonly hasCommand?: boolean;
  readonly children: readonly TreeNodeSnapshotLike[];
}

export interface SnapshotLike {
  readonly artifacts: readonly {
    id: string;
    file: string;
    title: string;
    kind: string;
    status: string | undefined;
  }[];
  readonly diagnostics: readonly { category: string }[];
  readonly references: readonly { targetId: string; file: string }[];
}

export interface StatusBarSnapshotLike {
  readonly text: string;
  readonly tooltip: string;
  readonly command: string | undefined;
  readonly visible: boolean;
  readonly counts: { active: number; blocked: number; openQuestions: number };
}

/** Узкие read-only test seams `src/extension.ts` (именованные CJS exports bundle). */
export interface ExtensionSeams {
  activate: (context: vscode.ExtensionContext) => unknown;
  deactivate: () => void;
  getActiveRegistrationCount: () => number;
  getActiveArtifactSnapshot: (folder: vscode.WorkspaceFolder) => SnapshotLike | undefined;
  getArtifactsViewSnapshot: () => readonly TreeNodeSnapshotLike[];
  getFocusViewSnapshot: () => readonly TreeNodeSnapshotLike[];
  getSummaryViewSnapshot: () => readonly TreeNodeSnapshotLike[];
  getStatusBarSnapshot: () => StatusBarSnapshotLike | undefined;
  getWatcherCount: (folder: vscode.WorkspaceFolder) => number;
  getCommandsViewSnapshot: () => readonly TreeNodeSnapshotLike[];
  getCommandCatalogState: (folder: vscode.WorkspaceFolder) => { kind: string } | undefined;
  getCommandsViewCommandNodes: () => readonly unknown[];
  getArtifactsViewArtifactNodes: () => readonly {
    folder: vscode.WorkspaceFolder;
    artifact: { id: string; kind: string };
  }[];
}

export interface DiagnosticsReportLike {
  readonly states: readonly {
    kind: string;
    workspaceRoot: string;
    detectedRelease?: string;
    minimumRelease?: string;
    diagnostic: { category: string; message: string; messageArguments: readonly unknown[] };
  }[];
  readonly summary: string;
  readonly lines: readonly string[];
}

export async function activateExtension(): Promise<ExtensionSeams> {
  const extension = vscode.extensions.getExtension(EXTENSION_ID);
  assert.ok(extension, `extension "${EXTENSION_ID}" was not found by the Extension Host`);
  await extension.activate();
  // Путь к bundle известен только в runtime (extensionPath).
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  return require(extension.extensionPath + '/dist/extension.js') as ExtensionSeams;
}

export function extensionPath(): string {
  const extension = vscode.extensions.getExtension(EXTENSION_ID);
  assert.ok(extension);
  return extension.extensionPath;
}

export function folderByName(name: string): vscode.WorkspaceFolder {
  const folder = vscode.workspace.workspaceFolders?.find((item) => item.name === name);
  assert.ok(folder, `workspace folder "${name}" is not open`);
  return folder;
}

export const sleep = (ms: number): Promise<void> =>
  new Promise((resolve) => setTimeout(resolve, ms));

export async function showDiagnostics(): Promise<DiagnosticsReportLike> {
  return vscode.commands.executeCommand<DiagnosticsReportLike>('harnessNavigator.showDiagnostics');
}

export const refresh = (): Thenable<unknown> =>
  vscode.commands.executeCommand('harnessNavigator.refresh');

/** Фиксированное окно и шаг poll: таймаут = FAIL, без скрытых повторов. */
export const WATCHER_WINDOW_MS = 15000;
export const POLL_INTERVAL_MS = 100;

export async function pollUntil(
  predicate: () => boolean | Promise<boolean>,
  timeoutMs: number = WATCHER_WINDOW_MS,
  intervalMs: number = POLL_INTERVAL_MS,
): Promise<boolean> {
  const deadline = Date.now() + timeoutMs;
  for (;;) {
    if (await predicate()) return true;
    if (Date.now() >= deadline) return false;
    await sleep(intervalMs);
  }
}

export async function pollFor(
  predicate: () => boolean | Promise<boolean>,
  description: string,
  timeoutMs: number = WATCHER_WINDOW_MS,
): Promise<void> {
  assert.ok(await pollUntil(predicate, timeoutMs), `timed out waiting for: ${description}`);
}

export type ConvergePath = 'watcher' | 'refresh fallback';

/**
 * Сначала ждёт watcher-only окно, затем документированный refresh fallback
 * (REQ-009). Возвращает фактический путь, который логируется для Evidence.
 */
export async function converge(
  predicate: () => boolean | Promise<boolean>,
  label: string,
  watcherWindowMs = 8000,
): Promise<ConvergePath | undefined> {
  let result: ConvergePath | undefined;
  if (await pollUntil(predicate, watcherWindowMs)) result = 'watcher';
  else {
    await refresh();
    if (await pollUntil(predicate, 5000)) result = 'refresh fallback';
  }
  console.log(`[converge] ${label}: ${result ?? 'NOT CONVERGED'} (platform ${process.platform})`);
  return result;
}

/** Маркеры fixtures, которые OS отказалась создать на этапе подготовки. */
export function readSkipMarkers(): Readonly<Record<string, string>> {
  const workspaceFile = vscode.workspace.workspaceFile;
  assert.ok(workspaceFile, 'mvp workspace file is expected');
  const marker = path.join(path.dirname(workspaceFile.fsPath), 'skipped-fixtures.json');
  const markers = JSON.parse(originalFs.readFileSync(marker, 'utf8')) as Record<string, string>;
  // Allowlist по platform: на Linux/macOS все fixtures обязаны создаваться. Единственное
  // допустимое исключение — mvp-unreadable под uid 0 (chmod 000 не ограничивает root).
  if (process.platform === 'linux' || process.platform === 'darwin') {
    const allowed = process.getuid?.() === 0 ? ['mvp-unreadable'] : [];
    const unexpected = Object.keys(markers).filter((name) => !allowed.includes(name));
    assert.deepEqual(unexpected, [], `unexpected skipped fixtures: ${JSON.stringify(markers)}`);
  }
  return markers;
}

/** Абсолютный каталог mvp-workspace (родитель roots и mvp-external). */
export function mvpDirectory(): string {
  const workspaceFile = vscode.workspace.workspaceFile;
  assert.ok(workspaceFile, 'mvp workspace file is expected');
  return path.dirname(workspaceFile.fsPath);
}

/** Плоский список узлов дерева (label + description) для проверок. */
export function flatten(nodes: readonly TreeNodeSnapshotLike[]): TreeNodeSnapshotLike[] {
  return nodes.flatMap((node) => [node, ...flatten(node.children)]);
}

export function artifactIds(snapshot: SnapshotLike | undefined): string[] {
  return (snapshot?.artifacts ?? []).map((artifact) => artifact.id).sort();
}

export const doc = (id: string, fields: string, title: string): string =>
  `---\nschema: 1\nid: ${id}\n${fields}---\n\n# ${id} — ${title}\n`;

type ShowQuickPickFn = typeof vscode.window.showQuickPick;

/**
 * Подменяет `vscode.window.showQuickPick` детерминированным ответом
 * (реальный UI блокировал бы тест). Возвращает restore; предложенные items
 * доступны через `offered`.
 */
export function stubQuickPick(choose: (items: readonly vscode.QuickPickItem[]) => unknown): {
  readonly offered: () => readonly vscode.QuickPickItem[];
  readonly restore: () => void;
} {
  const original = vscode.window.showQuickPick;
  let lastOffered: readonly vscode.QuickPickItem[] = [];
  const stub: unknown = async (items: unknown) => {
    lastOffered = (await Promise.resolve(items)) as readonly vscode.QuickPickItem[];
    return choose(lastOffered);
  };
  (vscode.window as { showQuickPick: ShowQuickPickFn }).showQuickPick = stub as ShowQuickPickFn;
  return {
    offered: () => lastOffered,
    restore: () => {
      (vscode.window as { showQuickPick: ShowQuickPickFn }).showQuickPick = original;
    },
  };
}

export function textOfHover(hovers: readonly vscode.Hover[]): string {
  return hovers
    .flatMap((hover) => hover.contents)
    .map((content) => (typeof content === 'string' ? content : content.value))
    .join('\n')
    .replace(/&nbsp;/gu, ' ');
}

/** Позиция первого вхождения `needle` в документе (внутри токена). */
export function positionOf(
  document: vscode.TextDocument,
  needle: string,
  offset = 2,
): vscode.Position {
  const index = document.getText().indexOf(needle);
  assert.ok(index >= 0, `"${needle}" not found in ${document.uri.fsPath}`);
  return document.positionAt(index + offset);
}

/** Локализованный текст Status Bar для заданных counts (как формирует расширение). */
export function expectedStatusText(active: number, blocked: number, openQuestions: number): string {
  return isRussian()
    ? `$(list-tree) Harness · активных: ${active} · заблокированных: ${blocked} · OQ: ${openQuestions}`
    : `$(list-tree) Harness · ${active} active · ${blocked} blocked · ${openQuestions} OQ`;
}

/**
 * Status Bar и Summary view считаются из тех же derived indexes, что и
 * `getActiveArtifactSnapshot`: counts обязаны совпадать со snapshot каждого
 * valid root.
 */
export function assertDerivedCountsConsistent(seams: ExtensionSeams): void {
  let active = 0;
  let blocked = 0;
  let openQuestions = 0;
  for (const folder of vscode.workspace.workspaceFolders ?? []) {
    const snapshot = seams.getActiveArtifactSnapshot(folder);
    if (snapshot === undefined) continue;
    const steps = snapshot.artifacts.filter((artifact) => artifact.kind === 'STEP');
    const step = (status: string) => steps.filter((artifact) => artifact.status === status).length;
    const rootActive = step('in_progress');
    const rootBlocked = step('blocked');
    const rootOpen = snapshot.artifacts.filter(
      (artifact) => artifact.kind === 'OQ' && artifact.status === 'open',
    ).length;
    active += rootActive;
    blocked += rootBlocked;
    openQuestions += rootOpen;
    const group = seams.getSummaryViewSnapshot().find((node) => node.label === folder.name);
    const value = (label: string) =>
      group?.children.find((child) => child.label === label)?.description;
    assert.equal(value('STEP'), String(steps.length), `${folder.name}: summary STEP count`);
    assert.equal(
      value('REQ'),
      String(snapshot.artifacts.filter((artifact) => artifact.kind === 'REQ').length),
    );
    assert.equal(
      value('ADR'),
      String(snapshot.artifacts.filter((artifact) => artifact.kind === 'ADR').length),
    );
    assert.equal(value(isRussian() ? 'В работе' : 'In progress'), String(rootActive));
    assert.equal(value(isRussian() ? 'Заблокировано' : 'Blocked'), String(rootBlocked));
    assert.equal(value(isRussian() ? 'Открытые OQ' : 'Open OQ'), String(rootOpen));
    assert.equal(
      value(isRussian() ? 'Диагностика' : 'Diagnostics'),
      String(snapshot.diagnostics.length),
    );
  }
  const status = seams.getStatusBarSnapshot();
  assert.ok(status?.visible, 'status bar must be visible for a workspace with valid roots');
  assert.deepEqual(status.counts, { active, blocked, openQuestions });
  assert.equal(status.text, expectedStatusText(active, blocked, openQuestions));
  assert.equal(status.command, 'workbench.view.extension.harnessNavigator');
}
