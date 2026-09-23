import * as path from 'node:path';

/**
 * Vscode-независимая атрибуция вызова к bundle расширения по захваченному
 * `Error.stack`. Вызов считается extension-originated тогда и только тогда,
 * когда хотя бы один кадр stack имеет файл, РАВНЫЙ `bundleFile` после
 * нормализации. Prefix/`startsWith` по extensionPath намеренно не
 * используется: в dev-профиле extensionPath — корень репозитория, и префикс
 * покрыл бы out/test, .vscode-test/ и node_modules/mocha.
 */

const FRAME = /^\s*at\s+(?:.*?\s+\()?(.+?)(?::\d+){1,2}\)?\s*$/u;

/** Извлекает файлы кадров формы `at fn (file:line:col)` и `at file:line:col`. */
export function stackFiles(stack: string): string[] {
  const files: string[] = [];
  for (const line of stack.split('\n')) {
    const match = FRAME.exec(line);
    const file = match?.[1];
    if (file !== undefined) files.push(file);
  }
  return files;
}

function fileUrlToPath(file: string, platform: NodeJS.Platform): string {
  if (!file.startsWith('file://')) return file;
  let decoded = decodeURIComponent(file.slice('file://'.length));
  // `file:///C:/x` -> `/C:/x` -> `C:/x` (только для Windows-путей с drive letter).
  if (/^\/[A-Za-z]:/u.test(decoded) && platform === 'win32') decoded = decoded.slice(1);
  return decoded;
}

export function normalizeFrameFile(file: string, platform: NodeJS.Platform): string {
  const flavour = platform === 'win32' ? path.win32 : path.posix;
  const normalized = flavour.normalize(fileUrlToPath(file, platform));
  return platform === 'win32' ? normalized.toLowerCase() : normalized;
}

export function isBundleOriginated(
  stack: string,
  bundleFile: string,
  platform: NodeJS.Platform = process.platform,
): boolean {
  const expected = normalizeFrameFile(bundleFile, platform);
  return stackFiles(stack).some((file) => normalizeFrameFile(file, platform) === expected);
}
