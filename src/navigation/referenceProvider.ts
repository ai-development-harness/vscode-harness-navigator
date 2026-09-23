import * as vscode from 'vscode';
import { idAtOffset } from './idMatcher';
import { toVscodeRange, type NavigationContext } from './harnessScope';
import type { ArtifactReference } from '../projectModel/artifactIndex';

export function referenceToLocation(reference: ArtifactReference): vscode.Location {
  return new vscode.Location(vscode.Uri.file(reference.file), toVscodeRange(reference));
}

/**
 * Find All References на общем Reference Index. `includeDeclaration`
 * уважается: definition (frontmatter id + H1) исключается только когда
 * пользователь не запрашивал declaration.
 */
export class HarnessReferenceProvider implements vscode.ReferenceProvider {
  constructor(private readonly context: NavigationContext) {}

  provideReferences(
    document: vscode.TextDocument,
    position: vscode.Position,
    referenceContext: vscode.ReferenceContext,
  ): vscode.Location[] {
    return this.context.guard(
      'references',
      () => {
        const scope = this.context.resolveScope(document);
        if (scope === undefined) return [];
        const hit = idAtOffset(document.lineAt(position.line).text, position.character);
        if (hit === undefined || scope.index.get(hit.id) === undefined) return [];
        return scope.index
          .referencesTo(hit.id, referenceContext.includeDeclaration)
          .map(referenceToLocation);
      },
      [],
    );
  }
}
