// Извлекает extension/** из уже собранного VSIX в out/packaged/extension
// (zip-slip guard), пишет out/packaged/extracted-entries.json (entry -> SHA-256)
// вне каталога расширения и копирует скомпилированные integration suites в
// out/packaged/extension/__packaged_tests__ (тот же instance vscode API, что и
// у bundle). Ничего не собирает и не публикует.
// Запуск: node --import tsx scripts/prepare-packaged-extension.ts

import * as crypto from 'node:crypto';
import * as fs from 'node:fs';
import * as path from 'node:path';
import { isDirectoryEntry, readZipEntries, readZipEntryData } from './packageArchive';

const repoRoot = path.resolve(__dirname, '..');
const packagedRoot = path.join(repoRoot, 'out', 'packaged');
const extensionRoot = path.join(packagedRoot, 'extension');

function guarded(target: string): string {
  const resolved = path.resolve(target);
  if (resolved !== packagedRoot && !resolved.startsWith(packagedRoot + path.sep))
    throw new Error(`Refusing to write outside ${packagedRoot}: ${resolved}`);
  return resolved;
}

function main(): void {
  const manifest = JSON.parse(fs.readFileSync(path.join(repoRoot, 'package.json'), 'utf8')) as {
    name: string;
    version: string;
  };
  const archivePath = path.join(repoRoot, `${manifest.name}-${manifest.version}.vsix`);
  if (!fs.existsSync(archivePath))
    throw new Error(`VSIX not found: ${archivePath} (run yarn package first)`);
  const compiledTests = path.join(repoRoot, 'out', 'test');
  if (!fs.existsSync(compiledTests))
    throw new Error('out/test is missing (run yarn compile:tests first)');

  fs.rmSync(guarded(packagedRoot), { recursive: true, force: true });
  fs.mkdirSync(guarded(extensionRoot), { recursive: true });

  const buffer = fs.readFileSync(archivePath);
  const hashes: Record<string, string> = {};
  for (const entry of readZipEntries(buffer)) {
    if (isDirectoryEntry(entry) || !entry.name.startsWith('extension/')) continue;
    const data = readZipEntryData(buffer, entry);
    const target = guarded(path.join(packagedRoot, entry.name));
    fs.mkdirSync(path.dirname(target), { recursive: true });
    fs.writeFileSync(target, data);
    hashes[entry.name] = crypto.createHash('sha256').update(data).digest('hex');
  }
  fs.writeFileSync(
    guarded(path.join(packagedRoot, 'extracted-entries.json')),
    `${JSON.stringify(hashes, null, 2)}\n`,
  );
  fs.cpSync(compiledTests, guarded(path.join(extensionRoot, '__packaged_tests__')), {
    recursive: true,
  });
  process.stdout.write(
    `packaged extension prepared at ${extensionRoot} (${Object.keys(hashes).length} entries)\n`,
  );
}

main();
