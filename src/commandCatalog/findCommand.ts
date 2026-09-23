import * as vscode from 'vscode';
import { COMMAND_CATALOG_MESSAGES as M } from './commandCatalogMessages';
import type { CommandCatalogService } from './commandCatalogService';
import { copyToClipboard } from './copyCommand';
import { commandDescription, commandDetail, renderCommandTemplate } from './commandViewModel';

const translate = (message: string, ...args: (string | number)[]): string =>
  vscode.l10n.t(message, ...args);

/** `harnessNavigator.findCommand`: Quick Pick по каталогу; выбор копирует шаблон. */
export function registerFindCommand(catalogs: CommandCatalogService): vscode.Disposable {
  return vscode.commands.registerCommand('harnessNavigator.findCommand', async () => {
    const seen = new Set<string>();
    const items: { label: string; description: string; detail: string; template: string }[] = [];
    for (const folder of vscode.workspace.workspaceFolders ?? []) {
      const state = catalogs.getCatalog(folder);
      if (state?.kind !== 'ready') continue;
      for (const command of state.catalog.commands) {
        if (seen.has(command.canonical)) continue;
        seen.add(command.canonical);
        items.push({
          label: command.canonical,
          description: commandDescription(command, translate),
          detail: commandDetail(command),
          template: renderCommandTemplate(command),
        });
      }
    }
    if (items.length === 0) {
      void vscode.window.showInformationMessage(vscode.l10n.t(M.findEmpty));
      return;
    }
    const picked = await vscode.window.showQuickPick(items, {
      placeHolder: vscode.l10n.t(M.findPlaceholder),
      matchOnDescription: true,
      matchOnDetail: true,
    });
    if (picked === undefined) return;
    await copyToClipboard(picked.template);
  });
}
