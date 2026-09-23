import * as crypto from 'node:crypto';
import * as path from 'node:path';
import { originalFs } from './originalApis';

/**
 * SHA-256 дерево всех файлов каталога (относительный путь -> hash). Symlink
 * хешируется по тексту цели и не разыменовывается. Использует только
 * оригинальные read-функции, сохранённые до установки boundary spies.
 */
export function hashTree(root: string): Record<string, string> {
  const result: Record<string, string> = {};
  const walk = (directory: string): void => {
    for (const entry of originalFs.readdirSync(directory, { withFileTypes: true })) {
      const full = path.join(directory, entry.name);
      const relative = path.relative(root, full);
      if (entry.isSymbolicLink()) result[relative] = `symlink:${originalFs.readlinkSync(full)}`;
      else if (entry.isDirectory()) walk(full);
      else if (entry.isFile())
        result[relative] = crypto
          .createHash('sha256')
          .update(originalFs.readFileSync(full))
          .digest('hex');
    }
  };
  walk(root);
  return result;
}

/** Hash дерева нескольких roots, ключ — путь root. */
export function hashRoots(roots: readonly string[]): Record<string, Record<string, string>> {
  const result: Record<string, Record<string, string>> = {};
  for (const root of roots) {
    try {
      result[root] = hashTree(root);
    } catch {
      // Недоступный root (например mvp-unreadable) хешируется как отсутствующий.
      result[root] = {};
    }
  }
  return result;
}
