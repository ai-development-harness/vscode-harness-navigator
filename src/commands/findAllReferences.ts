import * as vscode from 'vscode';
import type { NavigationContext } from '../navigation/harnessScope';
import { NAVIGATION_MESSAGES } from '../navigation/navigationMessages';
import { referenceToLocation } from '../navigation/referenceProvider';
import { resolveNavigationTarget } from './navigationTarget';

/**
 * `Harness: Find All References` — палитра, editor context menu, tree node и
 * Show Relations. Данные только из общего Reference Index (без открытия и
 * scan файлов); результат показывается штатным peek. Возвращает Locations
 * для Extension Host тестов.
 */
export function registerFindAllReferencesCommand(context: NavigationContext): vscode.Disposable {
  return vscode.commands.registerCommand(
    'harnessNavigator.findAllReferences',
    async (argument?: unknown) => {
      const target = resolveNavigationTarget(context, argument);
      if (target === undefined) {
        void vscode.window.showInformationMessage(vscode.l10n.t(NAVIGATION_MESSAGES.noTarget));
        return undefined;
      }
      const artifact = target.index.get(target.id);
      if (artifact === undefined) {
        void vscode.window.showInformationMessage(
          vscode.l10n.t(NAVIGATION_MESSAGES.unknownTarget, target.id),
        );
        return undefined;
      }
      const locations = target.index.referencesTo(target.id, false).map(referenceToLocation);
      if (locations.length === 0) {
        void vscode.window.showInformationMessage(
          vscode.l10n.t(NAVIGATION_MESSAGES.referencesEmpty, target.id),
        );
        return locations;
      }
      const definition = target.index.definitionRangesOf(target.id)[0];
      const anchor = target.anchor ?? {
        uri: vscode.Uri.file(artifact.file),
        position: new vscode.Position(definition?.startLine ?? 0, definition?.startCharacter ?? 0),
      };
      await vscode.commands.executeCommand(
        'editor.action.peekLocations',
        anchor.uri,
        anchor.position,
        locations,
        'peek',
      );
      return locations;
    },
  );
}
