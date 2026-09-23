import * as vscode from 'vscode';
import { isHarnessAwareMarkdown, type ArtifactIndex } from '../projectModel/artifactIndex';
import type { TextRange } from '../projectModel/artifactIndex';
import type { ProjectStateService } from '../projectModel/projectStateService';

export interface NavigationScope {
  readonly folder: vscode.WorkspaceFolder;
  readonly index: ArtifactIndex;
}

/**
 * Общий контекст navigation providers: единственная точка определения
 * Harness-aware области (REQ-001, REQ-005) и единая защита от исключений
 * (reliability: исключение provider-а не должно ронять Extension Host).
 */
export class NavigationContext {
  constructor(
    readonly projectStates: ProjectStateService,
    private readonly output: vscode.OutputChannel,
  ) {}

  /**
   * Возвращает root/index только для `file` markdown в valid Harness root и
   * Harness-aware области; иначе undefined — providers возвращают пусто.
   * Cross-file данные берутся из индекса, текст активного документа —
   * из самого документа (dirty правки); это различие намеренное.
   */
  resolveScope(document: {
    readonly uri: vscode.Uri;
    readonly languageId: string;
  }): NavigationScope | undefined {
    if (document.uri.scheme !== 'file' || document.languageId !== 'markdown') return undefined;
    const folder = vscode.workspace.getWorkspaceFolder(document.uri);
    if (folder === undefined) return undefined;
    const state = this.projectStates.getState(folder);
    const index = this.projectStates.getIndex(folder);
    if (state?.kind !== 'valid' || index === undefined) return undefined;
    if (!isHarnessAwareMarkdown(state.workspaceRoot, document.uri.fsPath, state.configuredPaths))
      return undefined;
    return { folder, index };
  }

  guard<T>(name: string, action: () => T, fallback: T): T {
    try {
      return action();
    } catch (error) {
      this.output.appendLine(
        `${name}: ${error instanceof Error ? (error.stack ?? error.message) : String(error)}`,
      );
      return fallback;
    }
  }
}

export function toVscodeRange(range: TextRange): vscode.Range {
  return new vscode.Range(range.startLine, range.startCharacter, range.endLine, range.endCharacter);
}

export const MARKDOWN_FILE_SELECTOR: vscode.DocumentSelector = {
  language: 'markdown',
  scheme: 'file',
};
