import * as fs from 'node:fs';
import * as vscode from 'vscode';

/**
 * Оригинальные функции записи fs / vscode.workspace.fs, сохранённые при
 * загрузке модуля, то есть до установки boundary spies. Собственные изменения
 * файлов теста (watcher-сценарии, подготовка и восстановление fixtures)
 * выполняются только через них: они не проходят через recorder и не
 * считаются нарушением границы расширения.
 */
const workspaceFs = vscode.workspace.fs;

export const originalFs = {
  writeFileSync: fs.writeFileSync.bind(fs),
  mkdirSync: fs.mkdirSync.bind(fs),
  rmSync: fs.rmSync.bind(fs),
  symlinkSync: fs.symlinkSync.bind(fs),
  cpSync: fs.cpSync.bind(fs),
  readFileSync: fs.readFileSync.bind(fs),
  readdirSync: fs.readdirSync.bind(fs),
  lstatSync: fs.lstatSync.bind(fs) as typeof fs.lstatSync,
  readlinkSync: fs.readlinkSync.bind(fs),
  existsSync: fs.existsSync.bind(fs),
};

export const originalWorkspaceFs = {
  writeFile: workspaceFs.writeFile.bind(workspaceFs),
  readFile: workspaceFs.readFile.bind(workspaceFs),
  delete: workspaceFs.delete.bind(workspaceFs),
  createDirectory: workspaceFs.createDirectory.bind(workspaceFs),
  stat: workspaceFs.stat.bind(workspaceFs),
};

const encoder = new TextEncoder();

/** Пишет текст файла оригинальным `vscode.workspace.fs.writeFile` (доходит до file watchers как обычная правка). */
export async function writeText(uri: vscode.Uri, text: string): Promise<void> {
  await originalWorkspaceFs.writeFile(uri, encoder.encode(text));
}

export async function removePath(uri: vscode.Uri): Promise<void> {
  await Promise.resolve(originalWorkspaceFs.delete(uri, { recursive: true, useTrash: false })).then(
    () => undefined,
    () => undefined,
  );
}
