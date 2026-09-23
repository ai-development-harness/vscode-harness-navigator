import * as vscode from 'vscode';
import { createLifecycleRegistry, LifecycleRegistry } from './lifecycle/disposableRegistry';
import { ProjectStateService } from './projectModel/projectStateService';
import type { ProjectState } from './projectModel/projectState';
import type { Artifact, ArtifactSnapshot } from './projectModel/artifactIndex';
import {
  ArtifactsTreeDataProvider,
  runClearFilters,
  runSetFilter,
  runSetSortOrder,
} from './views/artifactsView';
import { FocusTreeDataProvider } from './views/focusView';
import { registerGoToArtifactCommand } from './commands/goToArtifact';
import { registerCopyArtifactCommands } from './commands/copyArtifact';
import { registerFindAllReferencesCommand } from './commands/findAllReferences';
import { registerShowRelationsCommand } from './commands/showRelations';
import { NavigationContext, MARKDOWN_FILE_SELECTOR } from './navigation/harnessScope';
import { HarnessDefinitionProvider } from './navigation/definitionProvider';
import { HarnessDocumentLinkProvider } from './navigation/documentLinkProvider';
import { HarnessHoverProvider } from './navigation/hoverProvider';
import { HarnessCompletionProvider } from './navigation/completionProvider';
import { HarnessReferenceProvider } from './navigation/referenceProvider';
import {
  HARNESS_TOKEN_LEGEND,
  HarnessSemanticTokensProvider,
} from './navigation/semanticTokensProvider';
import { UnknownIdDiagnostics } from './navigation/unknownIdDiagnostics';
import { CommandCatalogService } from './commandCatalog/commandCatalogService';
import { CommandsTreeDataProvider, type CommandsTreeNode } from './commandCatalog/commandsView';
import { registerCopyCommand } from './commandCatalog/copyCommand';
import { registerFindCommand } from './commandCatalog/findCommand';
import type { CatalogState } from './commandCatalog/commandGraph';

/**
 * Минимальный, test-observable результат активации. Намеренно ограничен
 * состоянием активации и счётчиком зарегистрированных disposable, чтобы
 * disposal можно было доказать наблюдаемым поведением (activate →
 * deactivate → повторный activate), а не обращением к приватному
 * состоянию расширения.
 */
export interface ActivationResult {
  readonly state: 'activated';
  readonly registeredDisposableCount: number;
  readonly activatedLogMessage: string;
  readonly fallbackLogMessage: string;
  readonly projectStates: readonly ProjectState[];
}

let activeRegistry: LifecycleRegistry | undefined;
let activeProjectStates: ProjectStateService | undefined;
let activeArtifactsTreeView: vscode.TreeView<unknown> | undefined;
let activeFocusTreeView: vscode.TreeView<unknown> | undefined;
let activeArtifactsProvider: ArtifactsTreeDataProvider | undefined;
let activeFocusProvider: FocusTreeDataProvider | undefined;
let activeCatalogs: CommandCatalogService | undefined;
let activeCommandsProvider: CommandsTreeDataProvider | undefined;
let activeCommandsTreeView: vscode.TreeView<unknown> | undefined;
let artifactsTreeDataChangeCount = 0;

/**
 * Точка входа расширения. Намеренно не читает workspace, не запускает
 * процессы или не выполняет команды Harness. STEP-003 добавляет только
 * read-only derived indexes и их lifecycle без записи canonical files.
 * Каждый disposable, которым владеет это расширение, создаётся здесь и
 * проходит через lifecycle-реестр.
 */
export function activate(context: vscode.ExtensionContext): ActivationResult {
  const registry = createLifecycleRegistry(context.subscriptions);

  // Lifecycle-only marker disposable. Доказывает, что disposable,
  // созданные во время активации, отслеживаются реестром и освобождаются
  // при деактивации; не хранит product-состояние и не выполняет I/O.
  registry.register(markerDisposable());

  const output = registry.register(vscode.window.createOutputChannel('Harness Navigator'));
  const projectStates = registry.register(
    new ProjectStateService(vscode.workspace.workspaceFolders, output),
  );
  registry.register(
    vscode.commands.registerCommand('harnessNavigator.showDiagnostics', () =>
      projectStates.showDiagnostics(),
    ),
  );
  registry.register(
    vscode.commands.registerCommand('harnessNavigator.refresh', () => {
      for (const folder of vscode.workspace.workspaceFolders ?? []) {
        projectStates.refreshRoot(folder);
      }
    }),
  );

  const artifactsProvider = registry.register(new ArtifactsTreeDataProvider(projectStates));
  const artifactsTreeView = registry.register(
    vscode.window.createTreeView('harnessNavigator.artifacts', {
      treeDataProvider: artifactsProvider,
    }),
  );
  const focusProvider = registry.register(new FocusTreeDataProvider(projectStates));
  const focusTreeView = registry.register(
    vscode.window.createTreeView('harnessNavigator.focus', {
      treeDataProvider: focusProvider,
    }),
  );
  const refreshTreeMessages = () => {
    artifactsTreeView.message = artifactsProvider.computeMessage();
    focusTreeView.message = focusProvider.computeMessage();
  };
  refreshTreeMessages();
  registry.register(artifactsProvider.onDidChangeTreeData(refreshTreeMessages));
  registry.register(focusProvider.onDidChangeTreeData(refreshTreeMessages));
  // Узкий read-only counter (не внутреннее состояние provider-а), чтобы
  // Extension Host тест мог доказать, что `workspace.onDidChangeConfiguration`
  // действительно доходит до `onDidChangeTreeData` (а не только что
  // `provider.getChildren()` возвращает новые данные при прямом вызове).
  registry.register(
    artifactsProvider.onDidChangeTreeData(() => {
      artifactsTreeDataChangeCount += 1;
    }),
  );

  // STEP-006: read-only Command Catalog; сервис создаётся до view.
  const catalogs = registry.register(new CommandCatalogService(projectStates, output));
  registry.register(
    projectStates.registerDiagnosticSource((folder) => catalogs.diagnosticsFor(folder)),
  );
  const commandsProvider = registry.register(new CommandsTreeDataProvider(catalogs));
  const commandsTreeView = registry.register(
    vscode.window.createTreeView('harnessNavigator.commands', {
      treeDataProvider: commandsProvider,
    }),
  );
  const refreshCommandsMessage = () => {
    commandsTreeView.message = commandsProvider.computeMessage();
  };
  refreshCommandsMessage();
  registry.register(commandsProvider.onDidChangeTreeData(refreshCommandsMessage));
  registry.register(registerFindCommand(catalogs));
  registry.register(registerCopyCommand(catalogs));

  registry.register(registerGoToArtifactCommand(projectStates));
  registry.register(
    vscode.commands.registerCommand('harnessNavigator.setSortOrder', () => runSetSortOrder()),
  );
  registry.register(
    vscode.commands.registerCommand('harnessNavigator.setFilter', () =>
      runSetFilter(projectStates),
    ),
  );
  registry.register(
    vscode.commands.registerCommand('harnessNavigator.clearFilters', () =>
      runClearFilters(projectStates),
    ),
  );
  for (const disposable of registerCopyArtifactCommands()) registry.register(disposable);

  // STEP-005: один provider на язык; root резолвится по документу (multi-root).
  const navigation = new NavigationContext(projectStates, output);
  registry.register(
    vscode.languages.registerDefinitionProvider(
      MARKDOWN_FILE_SELECTOR,
      new HarnessDefinitionProvider(navigation),
    ),
  );
  registry.register(
    vscode.languages.registerDocumentLinkProvider(
      MARKDOWN_FILE_SELECTOR,
      new HarnessDocumentLinkProvider(navigation),
    ),
  );
  registry.register(
    vscode.languages.registerHoverProvider(
      MARKDOWN_FILE_SELECTOR,
      new HarnessHoverProvider(navigation),
    ),
  );
  registry.register(
    vscode.languages.registerCompletionItemProvider(
      MARKDOWN_FILE_SELECTOR,
      new HarnessCompletionProvider(navigation),
      '-',
    ),
  );
  registry.register(
    vscode.languages.registerReferenceProvider(
      MARKDOWN_FILE_SELECTOR,
      new HarnessReferenceProvider(navigation),
    ),
  );
  const semanticTokens = registry.register(new HarnessSemanticTokensProvider(navigation));
  registry.register(
    vscode.languages.registerDocumentSemanticTokensProvider(
      MARKDOWN_FILE_SELECTOR,
      semanticTokens,
      HARNESS_TOKEN_LEGEND,
    ),
  );
  const unknownIdDiagnostics = registry.register(new UnknownIdDiagnostics(navigation));
  registry.register(
    projectStates.onDidChangeProjectModel(() => {
      semanticTokens.fire();
      unknownIdDiagnostics.refreshAll();
    }),
  );
  registry.register(registerFindAllReferencesCommand(navigation));
  registry.register(registerShowRelationsCommand(navigation));

  activeRegistry = registry;
  activeProjectStates = projectStates;
  activeArtifactsTreeView = artifactsTreeView;
  activeFocusTreeView = focusTreeView;
  activeArtifactsProvider = artifactsProvider;
  activeFocusProvider = focusProvider;
  activeCatalogs = catalogs;
  activeCommandsProvider = commandsProvider;
  activeCommandsTreeView = commandsTreeView;

  const activatedLogMessage = vscode.l10n.t('Harness Navigator extension activated.');
  const fallbackLogMessage = vscode.l10n.t('Harness Navigator localization fallback is active.');

  return {
    state: 'activated',
    registeredDisposableCount: registry.count,
    activatedLogMessage,
    fallbackLogMessage,
    projectStates: projectStates.all,
  };
}

/**
 * Возвращает число активных registration без раскрытия lifecycle-реестра.
 * Этот узкий observable нужен integration-тесту STEP-001, чтобы проверить
 * фактический переход после `deactivate()`, а не только отсутствие ошибки.
 */
export function getActiveRegistrationCount(): number {
  return activeRegistry?.count ?? 0;
}

/** Узкая read-only observability для Extension Host tests и будущих consumers. */
export function getActiveArtifactSnapshot(
  folder: vscode.WorkspaceFolder,
): ArtifactSnapshot | undefined {
  return activeProjectStates?.getIndex(folder)?.snapshot();
}

/**
 * Узкий read-only test seam для Artifacts View/Focus View (в духе
 * `getActiveArtifactSnapshot`): раскрывает только уже публичный,
 * read-only `TreeView.message` — не внутреннее состояние provider-ов.
 */
export function getActiveTreeViewMessages(): {
  readonly artifacts: string | undefined;
  readonly focus: string | undefined;
} {
  return {
    artifacts: activeArtifactsTreeView?.message,
    focus: activeFocusTreeView?.message,
  };
}

/** Сериализуемый, read-only снимок одного узла Artifacts/Focus View для тестов. */
export interface TreeNodeSnapshot {
  readonly label: string;
  readonly description: string | undefined;
  readonly contextValue: string | undefined;
  /** `fsPath` файла, который открывает `vscode.open` команда узла (только у leaf artifact items). */
  readonly resourceFsPath: string | undefined;
  readonly children: readonly TreeNodeSnapshot[];
}

interface MinimalTreeProvider<T> {
  getTreeItem(node: T): vscode.TreeItem;
  getChildren(node?: T): T[];
}

function snapshotNode<T>(provider: MinimalTreeProvider<T>, node: T): TreeNodeSnapshot {
  const item = provider.getTreeItem(node);
  return {
    label: treeItemLabel(item),
    description: typeof item.description === 'string' ? item.description : undefined,
    contextValue: item.contextValue,
    resourceFsPath: treeItemResourceFsPath(item),
    children: provider.getChildren(node).map((child) => snapshotNode(provider, child)),
  };
}

function treeItemLabel(item: vscode.TreeItem): string {
  if (typeof item.label === 'string') return item.label;
  if (item.label !== undefined && typeof item.label === 'object') return item.label.label;
  return '';
}

function treeItemResourceFsPath(item: vscode.TreeItem): string | undefined {
  const args = item.command?.arguments;
  const first = Array.isArray(args) ? (args as unknown[])[0] : undefined;
  return first instanceof vscode.Uri ? first.fsPath : undefined;
}

/**
 * Узкий read-only test seam: полный snapshot текущего дерева Artifacts View
 * (не raw provider) для Extension Host сценариев STEP-004 — группировка,
 * порядок, sort/filter и empty state наблюдаемы без обращения к приватному
 * состоянию provider-а.
 */
export function getArtifactsViewSnapshot(): readonly TreeNodeSnapshot[] {
  const provider = activeArtifactsProvider;
  if (provider === undefined) return [];
  return provider.getChildren().map((node) => snapshotNode(provider, node));
}

/** Тот же test seam для Focus View. */
export function getFocusViewSnapshot(): readonly TreeNodeSnapshot[] {
  const provider = activeFocusProvider;
  if (provider === undefined) return [];
  return provider.getChildren().map((node) => snapshotNode(provider, node));
}

/**
 * Сколько раз `ArtifactsTreeDataProvider.onDidChangeTreeData` реально
 * сработало с начала активации. Узкий read-only test seam: доказывает, что
 * `workspace.onDidChangeConfiguration` подписка провайдера действительно
 * триггерит refresh event (а не только что снимок дерева меняется при
 * прямом вызове `getChildren()` в обход событийного пути, от которого
 * зависит реальный `TreeView` в VS Code).
 */
export function getArtifactsViewChangeEventCount(): number {
  return artifactsTreeDataChangeCount;
}

interface RawArtifactNode {
  readonly folder: vscode.WorkspaceFolder;
  readonly artifact: Artifact;
}

/**
 * Плоский список leaf-узлов Artifacts View в том же представлении
 * `{ type: 'artifact', folder, artifact }`, которое `getTreeItem` передаёт
 * `TreeItem.command`/`contextValue`-действиям — то есть то же самое, что
 * `harnessNavigator.copyArtifactId`/`copyArtifactPath` получают как `node`
 * аргумент в реальном UI. Узкий read-only test seam: без него Extension
 * Host тест мог проверить только регистрацию copy-команд, не их фактическое
 * поведение с реальным tree node.
 */
export function getArtifactsViewArtifactNodes(): readonly RawArtifactNode[] {
  const provider = activeArtifactsProvider;
  if (provider === undefined) return [];
  const nodes: RawArtifactNode[] = [];
  const walk = (node?: Parameters<ArtifactsTreeDataProvider['getChildren']>[0]): void => {
    for (const child of provider.getChildren(node)) {
      if (child.type === 'artifact') nodes.push({ folder: child.folder, artifact: child.artifact });
      else walk(child);
    }
  };
  walk(undefined);
  return nodes;
}

/** Read-only снимок состояния каталога root для Extension Host tests. */
export function getCommandCatalogState(folder: vscode.WorkspaceFolder): CatalogState | undefined {
  return activeCatalogs?.getCatalog(folder);
}

/** Сериализуемый read-only снимок узла Commands View. */
export interface CommandNodeSnapshot {
  readonly label: string;
  readonly description: string | undefined;
  readonly tooltip: string | undefined;
  readonly contextValue: string | undefined;
  /** `true`, если у узла есть `TreeItem.command` (должно быть всегда `false`). */
  readonly hasCommand: boolean;
  readonly children: readonly CommandNodeSnapshot[];
}

function snapshotCommandNode(
  provider: CommandsTreeDataProvider,
  node: CommandsTreeNode,
): CommandNodeSnapshot {
  const item = provider.getTreeItem(node);
  return {
    label: treeItemLabel(item),
    description: typeof item.description === 'string' ? item.description : undefined,
    tooltip: typeof item.tooltip === 'string' ? item.tooltip : undefined,
    contextValue: item.contextValue,
    hasCommand: item.command !== undefined,
    children: provider.getChildren(node).map((child) => snapshotCommandNode(provider, child)),
  };
}

/** Test seam: полный snapshot Commands View. */
export function getCommandsViewSnapshot(): readonly CommandNodeSnapshot[] {
  const provider = activeCommandsProvider;
  if (provider === undefined) return [];
  return provider.getChildren().map((node) => snapshotCommandNode(provider, node));
}

/** Test seam: `TreeView.message` Commands View. */
export function getCommandsViewMessage(): string | undefined {
  return activeCommandsTreeView?.message;
}

/** Test seam: raw leaf-узлы Commands View в форме, которую получает `copyCommand`. */
export function getCommandsViewCommandNodes(): readonly CommandsTreeNode[] {
  const provider = activeCommandsProvider;
  if (provider === undefined) return [];
  const nodes: CommandsTreeNode[] = [];
  const walk = (node?: CommandsTreeNode): void => {
    for (const child of provider.getChildren(node)) {
      if (child.type === 'command') nodes.push(child);
      else walk(child);
    }
  };
  walk(undefined);
  return nodes;
}

/**
 * Точка деактивации. Идемпотентна и никогда не бросает исключения:
 * освобождает lifecycle-реестр, созданный в `activate`, и безопасна для
 * вызова даже если `activate` ни разу не запускался или уже отработал
 * повторно.
 */
export function deactivate(): void {
  try {
    activeRegistry?.dispose();
  } finally {
    activeRegistry = undefined;
    activeProjectStates = undefined;
    activeArtifactsTreeView = undefined;
    activeFocusTreeView = undefined;
    activeArtifactsProvider = undefined;
    activeFocusProvider = undefined;
    activeCatalogs = undefined;
    activeCommandsProvider = undefined;
    activeCommandsTreeView = undefined;
    artifactsTreeDataChangeCount = 0;
  }
}

function markerDisposable(): vscode.Disposable {
  return new vscode.Disposable(() => {
    // Намеренно пусто: это только маркер lifecycle wiring.
  });
}
