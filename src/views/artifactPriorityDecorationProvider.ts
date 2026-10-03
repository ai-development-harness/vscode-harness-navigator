import * as vscode from 'vscode';
import type { ProjectStateService } from '../projectModel/projectStateService';
import { artifactPriorityPresentation } from './artifactPriorityPresentation';
import {
  parseArtifactPriorityResourceUri,
  ARTIFACT_PRIORITY_RESOURCE_SCHEME,
} from './artifactTreeItem';
import { VIEW_MESSAGES } from './viewMessages';

/**
 * Отдельный provider использует synthetic URI только Artifacts View. Это не
 * позволяет глобальному FileDecoration API изменить Explorer либо Focus View.
 */
export class ArtifactPriorityDecorationProvider
  implements vscode.FileDecorationProvider, vscode.Disposable
{
  private readonly changes = new vscode.EventEmitter<vscode.Uri[] | undefined>();
  readonly onDidChangeFileDecorations = this.changes.event;
  private readonly listener: vscode.Disposable;

  constructor(private readonly projectStates: ProjectStateService) {
    this.listener = projectStates.onDidChangeProjectModel(() => this.changes.fire(undefined));
  }

  provideFileDecoration(uri: vscode.Uri): vscode.FileDecoration | undefined {
    if (uri.scheme !== ARTIFACT_PRIORITY_RESOURCE_SCHEME) return undefined;
    const identity = parseArtifactPriorityResourceUri(uri);
    if (identity === undefined) return undefined;
    const folder = (vscode.workspace.workspaceFolders ?? []).find(
      (candidate) => candidate.uri.toString() === identity.folderUri,
    );
    const artifact =
      folder === undefined
        ? undefined
        : this.projectStates.getIndex(folder)?.getByFile(identity.file);
    const presentation = artifactPriorityPresentation(artifact?.metadata.priority);
    if (presentation === undefined) return undefined;
    const decoration = new vscode.FileDecoration(
      presentation.badge,
      vscode.l10n.t(VIEW_MESSAGES.priorityTooltip, vscode.l10n.t(presentation.label)),
      new vscode.ThemeColor(presentation.colorId),
    );
    // Decoration относится только к synthetic leaf URI и не наследуется реальными папками/файлами.
    // Это сохраняет изоляцию от Explorer и всех view вне Harness Artifacts.
    decoration.propagate = false;
    return decoration;
  }

  dispose(): void {
    this.listener.dispose();
    this.changes.dispose();
  }
}
