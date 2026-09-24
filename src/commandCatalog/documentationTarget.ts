import { lstatSync, realpathSync, statSync } from 'node:fs';
import * as path from 'node:path';

/**
 * Чистый (без `vscode`) резолв поля `documentation` формата `путь#якорь`
 * с containment-проверками ADR-005: абсолютный путь, `..` и symlink за root
 * отклоняются до открытия файла.
 */
export type DocumentationRef =
  | { readonly kind: 'empty' }
  | { readonly kind: 'ref'; readonly relativePath: string; readonly anchor: string };

export type DocumentationResolution =
  | { readonly kind: 'empty' }
  | { readonly kind: 'unsafe' }
  | { readonly kind: 'missing'; readonly relativePath: string }
  | { readonly kind: 'ok'; readonly fsPath: string; readonly anchor: string };

export function parseDocumentationRef(value: string): DocumentationRef {
  const trimmed = value.trim();
  if (trimmed === '') return { kind: 'empty' };
  const hash = trimmed.indexOf('#');
  const relativePath = (hash === -1 ? trimmed : trimmed.slice(0, hash)).trim();
  const anchor = hash === -1 ? '' : trimmed.slice(hash + 1).trim();
  if (relativePath === '') return { kind: 'empty' };
  return { kind: 'ref', relativePath, anchor };
}

function contained(root: string, candidate: string): boolean {
  const relative = path.relative(root, candidate);
  return (
    relative !== '' &&
    relative !== '..' &&
    !relative.startsWith(`..${path.sep}`) &&
    !path.isAbsolute(relative)
  );
}

export function resolveDocumentationPath(
  rootFsPath: string,
  value: string,
): DocumentationResolution {
  const ref = parseDocumentationRef(value);
  if (ref.kind === 'empty') return ref;
  const { relativePath, anchor } = ref;
  if (
    path.isAbsolute(relativePath) ||
    path.win32.isAbsolute(relativePath) ||
    path.posix.isAbsolute(relativePath) ||
    relativePath.split(/[\\/]+/).includes('..')
  ) {
    return { kind: 'unsafe' };
  }
  let realRoot: string;
  try {
    realRoot = realpathSync(rootFsPath);
  } catch {
    return { kind: 'unsafe' };
  }
  const resolved = path.resolve(realRoot, relativePath);
  if (!contained(realRoot, resolved)) return { kind: 'unsafe' };
  let realFile: string;
  try {
    realFile = realpathSync(resolved);
  } catch (error) {
    const code = (error as NodeJS.ErrnoException).code;
    if (code !== 'ENOENT' && code !== 'ENOTDIR') return { kind: 'unsafe' };
    // Dangling symlink: сам путь — ссылка, цель недоступна.
    if (isDanglingLink(resolved)) return { kind: 'unsafe' };
    return { kind: 'missing', relativePath };
  }
  if (!contained(realRoot, realFile)) return { kind: 'unsafe' };
  try {
    if (!statSync(realFile).isFile()) return { kind: 'missing', relativePath };
  } catch {
    return { kind: 'missing', relativePath };
  }
  return { kind: 'ok', fsPath: realFile, anchor };
}

function isDanglingLink(target: string): boolean {
  try {
    return lstatSync(target).isSymbolicLink();
  } catch {
    return false;
  }
}

const slug = (heading: string): string =>
  heading
    .trim()
    .toLowerCase()
    .replace(/[^\p{L}\p{N}\s_-]/gu, '')
    .replace(/\s/g, '-');

/** 0-based строка секции по якорю; `undefined`, если якорь не найден. */
export function findAnchorLine(text: string, anchor: string): number | undefined {
  if (anchor === '') return undefined;
  const lines = text.split(/\r\n|\r|\n/);
  const htmlAnchor = /<a\s+[^>]*\b(?:id|name)\s*=\s*["']([^"']*)["'][^>]*>/gi;
  for (const [index, line] of lines.entries()) {
    htmlAnchor.lastIndex = 0;
    for (let match = htmlAnchor.exec(line); match; match = htmlAnchor.exec(line)) {
      if (match[1] !== anchor) continue;
      const next = lines[index + 1];
      return next !== undefined && /^#{1,6}\s/.test(next) ? index + 1 : index;
    }
  }
  const wanted = anchor.toLowerCase();
  for (const [index, line] of lines.entries()) {
    const heading = /^#{1,6}\s+(.*?)\s*#*\s*$/.exec(line);
    if (heading?.[1] !== undefined && slug(heading[1]) === wanted) return index;
  }
  return undefined;
}
