import * as vscode from 'vscode';
import { MAXIMUM_MARKDOWN_SIZE_BYTES } from '../projectModel/artifactIndex';
import { scanIds } from './idMatcher';
import type { NavigationContext } from './harnessScope';
import { NAVIGATION_MESSAGES } from './navigationMessages';

/** Кликабельные ссылки на canonical файлы известных ID (без чтения диска). */
export class HarnessDocumentLinkProvider implements vscode.DocumentLinkProvider {
  constructor(private readonly context: NavigationContext) {}

  provideDocumentLinks(document: vscode.TextDocument): vscode.DocumentLink[] {
    return this.context.guard(
      'documentLinks',
      () => {
        const scope = this.context.resolveScope(document);
        if (scope === undefined) return [];
        const text = document.getText();
        if (text.length > MAXIMUM_MARKDOWN_SIZE_BYTES) return [];
        const links: vscode.DocumentLink[] = [];
        for (const match of scanIds(text)) {
          const artifact = scope.index.get(match.id);
          if (artifact === undefined || artifact.file === document.uri.fsPath) continue;
          const link = new vscode.DocumentLink(
            new vscode.Range(
              match.line,
              match.character,
              match.line,
              match.character + match.length,
            ),
            vscode.Uri.file(artifact.file),
          );
          link.tooltip = vscode.l10n.t(NAVIGATION_MESSAGES.documentLinkTooltip, match.id);
          links.push(link);
        }
        return links;
      },
      [],
    );
  }
}
