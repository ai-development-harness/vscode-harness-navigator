// CLI: читает <name>-<version>.vsix из package.json, печатает отсортированный
// список entries с SHA-256 и violations. Только чтение, без сети и записи.
// Запуск: yarn inspect:package

import * as crypto from 'node:crypto';
import * as fs from 'node:fs';
import * as path from 'node:path';
import { isDirectoryEntry, readZipEntries, readZipEntryData } from './packageArchive';
import { compareReadmeWithSource, inspectPackage, inspectReadmeText } from './packageInspection';

const repoRoot = path.resolve(__dirname, '..');

function main(): number {
  const manifest = JSON.parse(fs.readFileSync(path.join(repoRoot, 'package.json'), 'utf8')) as {
    name: string;
    version: string;
  };
  const archivePath = path.join(repoRoot, `${manifest.name}-${manifest.version}.vsix`);
  if (!fs.existsSync(archivePath)) {
    process.stderr.write(`VSIX not found: ${archivePath} (run yarn package first)\n`);
    return 1;
  }
  const buffer = fs.readFileSync(archivePath);
  const entries = readZipEntries(buffer)
    .filter((entry) => !isDirectoryEntry(entry))
    .sort((left, right) => left.name.localeCompare(right.name));

  const textEntries = new Map<string, string>();
  const binaryEntries = new Map<string, Uint8Array>();
  let packageJson: unknown = {};
  let bundle = '';
  process.stdout.write(`archive: ${path.basename(archivePath)} (${buffer.length} bytes)\n`);
  for (const entry of entries) {
    const data = readZipEntryData(buffer, entry);
    const hash = crypto.createHash('sha256').update(data).digest('hex');
    process.stdout.write(`${hash}  ${String(entry.size).padStart(8)}  ${entry.name}\n`);
    if (entry.name === 'extension/package.json')
      packageJson = JSON.parse(data.toString('utf8')) as unknown;
    else if (entry.name === 'extension/dist/extension.js') bundle = data.toString('utf8');
    else if (entry.name.toLowerCase().endsWith('.png')) binaryEntries.set(entry.name, data);
    else textEntries.set(entry.name, data.toString('utf8'));
  }
  const violations = inspectPackage({
    entryNames: entries.map((entry) => entry.name),
    archiveBytes: buffer.length,
    packageJson,
    bundle,
    textEntries,
    binaryEntries,
  });
  const readmeSource = path.join(repoRoot, 'docs', 'marketplace', 'README.md');
  const sourceText = fs.existsSync(readmeSource)
    ? fs.readFileSync(readmeSource, 'utf8')
    : undefined;
  if (sourceText !== undefined)
    for (const item of inspectReadmeText(sourceText)) violations.push(`source README: ${item}`);
  const comparison = compareReadmeWithSource(textEntries.get('extension/readme.md'), sourceText);
  process.stdout.write(`readme comparison: ${comparison.status} (${comparison.message})\n`);
  if (comparison.status === 'differs') violations.push(comparison.message);
  if (violations.length === 0) {
    process.stdout.write('package inspection: PASS (0 violations)\n');
    return 0;
  }
  for (const violation of violations) process.stderr.write(`violation: ${violation}\n`);
  process.stderr.write(`package inspection: FAIL (${violations.length} violations)\n`);
  return 1;
}

process.exitCode = main();
