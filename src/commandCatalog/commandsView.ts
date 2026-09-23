import * as vscode from 'vscode';
import { VIEW_MESSAGES } from '../views/viewMessages';
import { COMMAND_CATALOG_MESSAGES as M } from './commandCatalogMessages';
import type { CommandCatalogService } from './commandCatalogService';
import type { CatalogCommand } from './commandGraph';
import {
  commandDescription,
  commandTooltip,
  computeCommandsMessage,
  type CatalogKind,
} from './commandViewModel';

export type CommandsTreeNode =
  | { readonly type: 'root'; readonly folder: vscode.WorkspaceFolder }
  | { readonly type: 'domain'; readonly folder: vscode.WorkspaceFolder; readonly domain: string }
  | {
      readonly type: 'command';
      readonly folder: vscode.WorkspaceFolder;
      readonly command: CatalogCommand;
    };

const translate = (message: string, ...args: (string | number)[]): string =>
  vscode.l10n.t(message, ...args);

/**
 * Read-only Harness Commands View. Читает только готовое состояние
 * `CommandCatalogService` (никакого I/O в getChildren) и ничего не выполняет:
 * у узлов нет `TreeItem.command`.
 */
export class CommandsTreeDataProvider
  implements vscode.TreeDataProvider<CommandsTreeNode>, vscode.Disposable
{
  private readonly changeEmitter = new vscode.EventEmitter<void>();
  readonly onDidChangeTreeData = this.changeEmitter.event;
  private readonly listener: vscode.Disposable;

  constructor(private readonly catalogs: CommandCatalogService) {
    this.listener = catalogs.onDidChangeCatalog(() => this.changeEmitter.fire());
  }

  getTreeItem(element: CommandsTreeNode): vscode.TreeItem {
    switch (element.type) {
      case 'root':
        return this.buildRoot(element.folder);
      case 'domain': {
        const item = new vscode.TreeItem(element.domain, vscode.TreeItemCollapsibleState.Expanded);
        item.id = `harnessNavigator.commandDomain:${element.folder.uri.toString()}:${element.domain}`;
        item.iconPath = new vscode.ThemeIcon('layers');
        item.contextValue = 'harnessCommandDomainItem';
        return item;
      }
      case 'command': {
        const { command } = element;
        const item = new vscode.TreeItem(command.canonical, vscode.TreeItemCollapsibleState.None);
        item.id = `harnessNavigator.command:${element.folder.uri.toString()}:${command.domain}:${command.operation}`;
        item.description = commandDescription(command, translate);
        item.tooltip = commandTooltip(command, translate);
        item.iconPath = new vscode.ThemeIcon('symbol-method');
        item.contextValue = 'harnessCommandItem';
        return item;
      }
    }
  }

  getChildren(element?: CommandsTreeNode): CommandsTreeNode[] {
    const folders = this.validFolders();
    if (element === undefined) {
      if (folders.length > 1) return folders.map((folder) => ({ type: 'root', folder }) as const);
      const only = folders[0];
      return only === undefined ? [] : this.domainsFor(only);
    }
    if (element.type === 'root') return this.domainsFor(element.folder);
    if (element.type === 'domain') {
      const state = this.catalogs.getCatalog(element.folder);
      const domain =
        state?.kind === 'ready'
          ? state.catalog.domains.find((candidate) => candidate.name === element.domain)
          : undefined;
      return (domain?.commands ?? []).map(
        (command) => ({ type: 'command', folder: element.folder, command }) as const,
      );
    }
    return [];
  }

  /** Локализованное `TreeView.message`; `''` — сообщение не нужно. */
  computeMessage(): string {
    const states = this.validFolders().map((folder) => {
      const state = this.catalogs.getCatalog(folder);
      const kind: CatalogKind = state?.kind ?? 'readError';
      return { kind, commandCount: state?.kind === 'ready' ? state.catalog.commands.length : 0 };
    });
    return computeCommandsMessage(states, translate, VIEW_MESSAGES.noHarnessProject);
  }

  dispose(): void {
    this.listener.dispose();
    this.changeEmitter.dispose();
  }

  private validFolders(): vscode.WorkspaceFolder[] {
    return (vscode.workspace.workspaceFolders ?? []).filter(
      (folder) => this.catalogs.getCatalog(folder) !== undefined,
    );
  }

  private domainsFor(folder: vscode.WorkspaceFolder): CommandsTreeNode[] {
    const state = this.catalogs.getCatalog(folder);
    if (state?.kind !== 'ready') return [];
    return state.catalog.domains
      .filter((domain) => domain.commands.length > 0)
      .map((domain) => ({ type: 'domain', folder, domain: domain.name }) as const);
  }

  private buildRoot(folder: vscode.WorkspaceFolder): vscode.TreeItem {
    const item = new vscode.TreeItem(folder.name, vscode.TreeItemCollapsibleState.Expanded);
    item.id = `harnessNavigator.commandRoot:${folder.uri.toString()}`;
    item.iconPath = new vscode.ThemeIcon('root-folder');
    item.contextValue = 'harnessCommandRootItem';
    if (this.catalogs.getCatalog(folder)?.kind !== 'ready')
      item.description = vscode.l10n.t(M.viewGraphErrorDescription);
    return item;
  }
}
