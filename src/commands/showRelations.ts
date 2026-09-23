import * as vscode from 'vscode';
import type { NavigationContext } from '../navigation/harnessScope';
import { toVscodeRange } from '../navigation/harnessScope';
import { NAVIGATION_MESSAGES } from '../navigation/navigationMessages';
import { buildRelations, type RelationItem } from '../navigation/relationsService';
import { resolveNavigationTarget } from './navigationTarget';

interface RelationsQuickPickItem extends vscode.QuickPickItem {
  readonly action?: 'findAllReferences';
  readonly open?: { readonly file: string; readonly range?: vscode.Range };
}

function relationItem(item: RelationItem): RelationsQuickPickItem {
  if (item.unresolved)
    return {
      label: item.id,
      description: vscode.l10n.t(NAVIGATION_MESSAGES.relationsUnresolved),
    };
  return {
    label: item.id,
    description: item.title ?? '',
    detail: item.kind ?? '',
    open: {
      file: item.file as string,
      ...(item.range === undefined ? {} : { range: toVscodeRange(item.range) }),
    },
  };
}

/**
 * `Harness: Show Relations` на нативном QuickPick с separators
 * Outgoing/Incoming/Mentions. Выбор открывает artifact либо mention;
 * пункт Find All References вызывает ту же команду, что editor/tree.
 */
export function registerShowRelationsCommand(context: NavigationContext): vscode.Disposable {
  return vscode.commands.registerCommand(
    'harnessNavigator.showRelations',
    async (argument?: unknown) => {
      const target = resolveNavigationTarget(context, argument);
      if (target === undefined) {
        void vscode.window.showInformationMessage(vscode.l10n.t(NAVIGATION_MESSAGES.noTarget));
        return;
      }
      const relations = buildRelations(target.index, target.id);
      const artifact = target.index.get(target.id);
      if (relations === undefined || artifact === undefined) {
        void vscode.window.showInformationMessage(
          vscode.l10n.t(NAVIGATION_MESSAGES.unknownTarget, target.id),
        );
        return;
      }
      const separator = (label: string): RelationsQuickPickItem => ({
        label,
        kind: vscode.QuickPickItemKind.Separator,
      });
      const items: RelationsQuickPickItem[] = [
        {
          label: `$(references) ${vscode.l10n.t(NAVIGATION_MESSAGES.relationsFindAllReferences)}`,
          action: 'findAllReferences',
        },
      ];
      if (relations.outgoing.length > 0) {
        items.push(separator(vscode.l10n.t(NAVIGATION_MESSAGES.relationsOutgoing)));
        items.push(...relations.outgoing.map(relationItem));
      }
      if (relations.incoming.length > 0) {
        items.push(separator(vscode.l10n.t(NAVIGATION_MESSAGES.relationsIncoming)));
        items.push(...relations.incoming.map(relationItem));
      }
      if (relations.mentions.length > 0) {
        items.push(separator(vscode.l10n.t(NAVIGATION_MESSAGES.relationsMentions)));
        for (const group of relations.mentions) {
          const first = group.references[0];
          items.push({
            label: vscode.workspace.asRelativePath(group.file),
            description: vscode.l10n.t(
              NAVIGATION_MESSAGES.relationsMentionCount,
              group.references.length,
            ),
            open: {
              file: group.file,
              ...(first === undefined ? {} : { range: toVscodeRange(first) }),
            },
          });
        }
      }
      const picked = await vscode.window.showQuickPick(items, {
        placeHolder: vscode.l10n.t(NAVIGATION_MESSAGES.relationsPlaceholder, target.id),
        matchOnDescription: true,
      });
      if (picked === undefined) return;
      if (picked.action === 'findAllReferences') {
        await vscode.commands.executeCommand('harnessNavigator.findAllReferences', {
          artifact,
          folder: target.folder,
        });
        return;
      }
      if (picked.open !== undefined) {
        const options: vscode.TextDocumentShowOptions =
          picked.open.range === undefined ? {} : { selection: picked.open.range };
        await vscode.commands.executeCommand(
          'vscode.open',
          vscode.Uri.file(picked.open.file),
          options,
        );
      }
    },
  );
}
