// Zero-dependency чтение ZIP (VSIX) через central directory: EOCD,
// stored/deflate через node:zlib. Содержимое не исполняется. Отказ на
// ZIP64, шифровании и небезопасных именах entries (zip-slip).

import * as zlib from 'node:zlib';

export class ZipFormatError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'ZipFormatError';
  }
}

export interface ZipEntry {
  readonly name: string;
  readonly size: number;
  readonly compressedSize: number;
  readonly method: number;
  readonly localHeaderOffset: number;
}

const EOCD_SIGNATURE = 0x06054b50;
const ZIP64_LOCATOR_SIGNATURE = 0x07064b50;
const CENTRAL_SIGNATURE = 0x02014b50;
const LOCAL_SIGNATURE = 0x04034b50;
const MAX_ENTRIES = 1024;
export const MAX_ARCHIVE_BYTES = 8 * 1024 * 1024;
export const MAX_ENTRY_BYTES = 8 * 1024 * 1024;
export const MAX_TOTAL_UNCOMPRESSED_BYTES = 16 * 1024 * 1024;

/** Отвергает абсолютные пути, `..` сегменты и backslash (zip-slip). */
export function assertSafeEntryName(name: string): void {
  if (name.length === 0) throw new ZipFormatError('empty entry name');
  if (name.includes('\\')) throw new ZipFormatError(`entry name contains a backslash: ${name}`);
  if (name.startsWith('/') || /^[A-Za-z]:/u.test(name))
    throw new ZipFormatError(`entry name is absolute: ${name}`);
  if (name.split('/').includes('..'))
    throw new ZipFormatError(`entry name contains a traversal segment: ${name}`);
  if (name.includes('\0')) throw new ZipFormatError('entry name contains NUL');
}

function findEndOfCentralDirectory(buffer: Buffer): number {
  const minimum = Math.max(0, buffer.length - 22 - 0xffff);
  for (let offset = buffer.length - 22; offset >= minimum; offset -= 1)
    if (buffer.readUInt32LE(offset) === EOCD_SIGNATURE) return offset;
  throw new ZipFormatError('end of central directory not found');
}

export function readZipEntries(buffer: Buffer): ZipEntry[] {
  if (buffer.length > MAX_ARCHIVE_BYTES) throw new ZipFormatError('archive is too large');
  const eocd = findEndOfCentralDirectory(buffer);
  if (eocd >= 20 && buffer.readUInt32LE(eocd - 20) === ZIP64_LOCATOR_SIGNATURE)
    throw new ZipFormatError('ZIP64 archives are not supported');
  const total = buffer.readUInt16LE(eocd + 10);
  const directorySize = buffer.readUInt32LE(eocd + 12);
  const directoryOffset = buffer.readUInt32LE(eocd + 16);
  if (total === 0xffff || directorySize === 0xffffffff || directoryOffset === 0xffffffff)
    throw new ZipFormatError('ZIP64 archives are not supported');
  if (total > MAX_ENTRIES) throw new ZipFormatError('too many entries');
  const entries: ZipEntry[] = [];
  let cursor = directoryOffset;
  let totalSize = 0;
  for (let index = 0; index < total; index += 1) {
    if (cursor + 46 > buffer.length || buffer.readUInt32LE(cursor) !== CENTRAL_SIGNATURE)
      throw new ZipFormatError('malformed central directory');
    const flags = buffer.readUInt16LE(cursor + 8);
    if ((flags & 0x1) !== 0) throw new ZipFormatError('encrypted entries are not supported');
    const method = buffer.readUInt16LE(cursor + 10);
    const compressedSize = buffer.readUInt32LE(cursor + 20);
    const size = buffer.readUInt32LE(cursor + 24);
    const nameLength = buffer.readUInt16LE(cursor + 28);
    const extraLength = buffer.readUInt16LE(cursor + 30);
    const commentLength = buffer.readUInt16LE(cursor + 32);
    const localHeaderOffset = buffer.readUInt32LE(cursor + 42);
    if (compressedSize === 0xffffffff || size === 0xffffffff || localHeaderOffset === 0xffffffff)
      throw new ZipFormatError('ZIP64 entries are not supported');
    const name = buffer.toString('utf8', cursor + 46, cursor + 46 + nameLength);
    assertSafeEntryName(name);
    if (size > MAX_ENTRY_BYTES) throw new ZipFormatError(`entry is too large: ${name}`);
    totalSize += size;
    if (totalSize > MAX_TOTAL_UNCOMPRESSED_BYTES)
      throw new ZipFormatError('total uncompressed size is too large');
    entries.push({ name, size, compressedSize, method, localHeaderOffset });
    cursor += 46 + nameLength + extraLength + commentLength;
  }
  return entries;
}

function decompress(raw: Buffer, entry: ZipEntry): Buffer {
  try {
    return zlib.inflateRawSync(raw, { maxOutputLength: Math.max(entry.size, 1) });
  } catch (error) {
    throw new ZipFormatError(
      `cannot inflate ${entry.name}: ${error instanceof Error ? error.message : String(error)}`,
    );
  }
}

export function readZipEntryData(buffer: Buffer, entry: ZipEntry): Buffer {
  const offset = entry.localHeaderOffset;
  if (offset + 30 > buffer.length || buffer.readUInt32LE(offset) !== LOCAL_SIGNATURE)
    throw new ZipFormatError(`malformed local header for ${entry.name}`);
  const start = offset + 30 + buffer.readUInt16LE(offset + 26) + buffer.readUInt16LE(offset + 28);
  const raw = buffer.subarray(start, start + entry.compressedSize);
  let data: Buffer;
  if (entry.method === 0) data = raw;
  else if (entry.method === 8) data = decompress(raw, entry);
  else throw new ZipFormatError(`unsupported compression method ${entry.method}`);
  if (data.length !== entry.size) throw new ZipFormatError(`size mismatch for ${entry.name}`);
  return data;
}

export function isDirectoryEntry(entry: ZipEntry): boolean {
  return entry.name.endsWith('/');
}
