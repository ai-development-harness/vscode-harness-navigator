import * as vscode from 'vscode';
import { COMMAND_CATALOG_MESSAGES as M } from './commandCatalogMessages';
import type { CommandCatalogService } from './commandCatalogService';
import type { CatalogCommand } from './commandGraph';
import {
  commandDescription,
  commandDetail,
  renderCommandTemplate,
  stepCommands,
} from './commandViewModel';

const translate = (message: string, ...args: (string | number)[]): string =>
  vscode.l10n.t(message, ...args);

interface CommandNode {
  readonly type: 'command';
  readonly command: CatalogCommand;
}

interface ArtifactNode {
  readonly folder: vscode.WorkspaceFolder;
  readonly artifact: { readonly id: string; readonly kind: string };
}

function isCommandNode(value: unknown): value is CommandNode {
  if (typeof value !== 'object' || value === null) return false;
  const candidate = value as Partial<CommandNode>;
  return (
    candidate.type === 'command' &&
    typeof candidate.command === 'object' &&
    candidate.command !== null &&
    typeof candidate.command.canonical === 'string'
  );
}

function isArtifactNode(value: unknown): value is ArtifactNode {
  if (typeof value !== 'object' || value === null) return false;
  const candidate = value as Partial<ArtifactNode>;
  return (
    typeof candidate.folder === 'object' &&
    candidate.folder !== null &&
    typeof candidate.artifact === 'object' &&
    candidate.artifact !== null
  );
}

/**
 * Единственный побочный эффект команд каталога — запись строки в clipboard.
 * Команда Harness никогда не выполняется: без terminal/tasks/child_process.
 */
export async function copyToClipboard(text: string): Promise<void> {
  try {
    await vscode.env.clipboard.writeText(text);
  } catch {
    void vscode.window.showErrorMessage(vscode.l10n.t(M.copyFailed));
    return;
  }
  void vscode.window.showInformationMessage(vscode.l10n.t(M.copied, text));
}

/**
 * `harnessNavigator.copyCommand`: из узла Commands View копирует шаблон;
 * из STEP-узла Artifacts/Focus View предлагает команды с target `step` и
 * копирует вариант с фактическим STEP ID.
 */
export function registerCopyCommand(catalogs: CommandCatalogService): vscode.Disposable {
  return vscode.commands.registerCommand('harnessNavigator.copyCommand', async (node: unknown) => {
    if (isCommandNode(node)) {
      await copyToClipboard(renderCommandTemplate(node.command));
      return;
    }
    if (!isArtifactNode(node)) return;
    if (node.artifact.kind !== 'STEP') {
      void vscode.window.showInformationMessage(vscode.l10n.t(M.copyNotStep));
      return;
    }
    const state = catalogs.getCatalog(node.folder);
    const commands = state?.kind === 'ready' ? stepCommands(state.catalog) : [];
    if (commands.length === 0) {
      void vscode.window.showInformationMessage(vscode.l10n.t(M.copyNoStepCommands));
      return;
    }
    const stepId = node.artifact.id;
    const items = commands.map((command) => ({
      label: renderCommandTemplate(command, { stepId }),
      description: commandDescription(command, translate),
      detail: commandDetail(command),
    }));
    const picked = await vscode.window.showQuickPick(items, {
      placeHolder: vscode.l10n.t(M.copyPickStepCommand, stepId),
      matchOnDescription: true,
      matchOnDetail: true,
    });
    if (picked === undefined) return;
    await copyToClipboard(picked.label);
  });
}
