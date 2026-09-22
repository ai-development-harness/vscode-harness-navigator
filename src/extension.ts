import * as vscode from 'vscode';
import { createLifecycleRegistry, LifecycleRegistry } from './lifecycle/disposableRegistry';
import { ProjectStateService } from './projectModel/projectStateService';
import type { ProjectState } from './projectModel/projectState';
import type { ArtifactSnapshot } from './projectModel/artifactIndex';

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

  activeRegistry = registry;
  activeProjectStates = projectStates;

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
  }
}

function markerDisposable(): vscode.Disposable {
  return new vscode.Disposable(() => {
    // Намеренно пусто: это только маркер lifecycle wiring.
  });
}
