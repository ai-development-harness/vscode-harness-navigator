import * as vscode from 'vscode';
import { idAtOffset } from './idMatcher';
import type { NavigationContext } from './harnessScope';
import { NAVIGATION_MESSAGES } from './navigationMessages';
import { buildHoverModel } from './navigationViewModel';

/** Локализованный hover: title/kind/status/число relations. Unknown → пусто. */
export class HarnessHoverProvider implements vscode.HoverProvider {
  constructor(private readonly context: NavigationContext) {}

  provideHover(document: vscode.TextDocument, position: vscode.Position): vscode.Hover | undefined {
    return this.context.guard(
      'hover',
      () => {
        const scope = this.context.resolveScope(document);
        if (scope === undefined) return undefined;
        const hit = idAtOffset(document.lineAt(position.line).text, position.character);
        if (hit === undefined) return undefined;
        const artifact = scope.index.get(hit.id);
        if (artifact === undefined) return undefined;
        const model = buildHoverModel(artifact, scope.index.referencesTo(hit.id, false).length);
        const markdown = new vscode.MarkdownString();
        markdown.appendMarkdown(`**${model.id}** — `);
        // Title приходит из недоверенного Markdown: только appendText (escape).
        markdown.appendText(model.title);
        markdown.appendMarkdown('\n\n');
        markdown.appendText(vscode.l10n.t(NAVIGATION_MESSAGES.hoverKind, model.kind));
        markdown.appendMarkdown('  \n');
        markdown.appendText(vscode.l10n.t(NAVIGATION_MESSAGES.hoverStatus, model.status));
        markdown.appendMarkdown('  \n');
        markdown.appendText(
          vscode.l10n.t(
            NAVIGATION_MESSAGES.hoverRelations,
            model.outgoing,
            model.incoming,
            model.mentions,
          ),
        );
        return new vscode.Hover(
          markdown,
          new vscode.Range(position.line, hit.start, position.line, hit.end),
        );
      },
      undefined,
    );
  }
}
