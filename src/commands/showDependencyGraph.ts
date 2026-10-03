import * as vscode from 'vscode';
import { DependencyGraphPanel } from '../projectGraph/dependencyGraphPanel';
import type { ProjectGraphService } from '../projectGraph/projectStateService';
import type { ProjectStateService } from '../projectModel/projectStateService';

const panels = new Map<string, DependencyGraphPanel>();
interface GraphTarget {
  readonly folder?: vscode.WorkspaceFolder;
  readonly artifact?: { readonly id?: string };
}
/** Отдельный panel на root; Palette явно предлагает выбор, context сохраняет owning root. */
export function registerShowDependencyGraph(
  graphs: ProjectGraphService,
  projects: ProjectStateService,
): vscode.Disposable {
  const show = async (target?: GraphTarget) => {
    const folders = (vscode.workspace.workspaceFolders ?? []).filter(
      (f) => projects.getState(f)?.kind === 'valid',
    );
    let folder = target?.folder;
    if (folder) {
      folder = folders.find((f) => f.uri.toString() === target?.folder?.uri.toString());
      if (!folder) return;
    }
    if (!folder) {
      if (folders.length === 1) folder = folders[0];
      else if (folders.length > 1)
        folder = (
          await vscode.window.showQuickPick(
            folders.map((f) => ({ label: f.name, description: f.uri.fsPath, folder: f })),
            { placeHolder: vscode.l10n.t('Select a Harness workspace root.') },
          )
        )?.folder;
    }
    if (!folder) {
      if (!folders.length)
        void vscode.window.showInformationMessage(
          vscode.l10n.t('No Harness workspace folder is open.'),
        );
      return;
    }
    const key = folder.uri.toString(),
      focus = target?.artifact?.id;
    const existing = panels.get(key);
    if (existing) existing.reveal(focus);
    else panels.set(key, new DependencyGraphPanel(folder, graphs, focus, () => panels.delete(key)));
  };
  const commands = [
    vscode.commands.registerCommand('harnessNavigator.showDependencyGraph', show),
    vscode.commands.registerCommand('harnessNavigator.showInDependencyGraph', show),
    vscode.workspace.onDidChangeWorkspaceFolders((e) => {
      for (const folder of e.removed) {
        const key = folder.uri.toString();
        panels.get(key)?.dispose();
        panels.delete(key);
      }
    }),
  ];
  return {
    dispose: () => {
      for (const panel of panels.values()) panel.dispose();
      panels.clear();
      for (const c of commands) c.dispose();
    },
  };
}

/** Снимок и narrow message seam доказывают production panel без обхода его валидатора. */
export function getDependencyGraphPanelSnapshot(folder: vscode.WorkspaceFolder) {
  return panels.get(folder.uri.toString())?.getSnapshot();
}
export async function dispatchDependencyGraphMessage(
  folder: vscode.WorkspaceFolder,
  message: unknown,
) {
  await panels.get(folder.uri.toString())?.handleMessage(message);
}
