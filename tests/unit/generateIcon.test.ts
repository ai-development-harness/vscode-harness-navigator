import { test } from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import * as fs from 'node:fs';
import * as path from 'node:path';
import * as zlib from 'node:zlib';
import {
  ICON_SIZE,
  PNG_SIGNATURE,
  buildIconPng,
  crc32,
  encodePng,
} from '../../scripts/iconEncoder';

interface Chunk {
  type: string;
  data: Buffer;
  crc: number;
}

function parseChunks(png: Buffer): Chunk[] {
  assert.ok(png.subarray(0, 8).equals(PNG_SIGNATURE));
  const chunks: Chunk[] = [];
  let offset = 8;
  while (offset < png.length) {
    const length = png.readUInt32BE(offset);
    chunks.push({
      type: png.toString('latin1', offset + 4, offset + 8),
      data: png.subarray(offset + 8, offset + 8 + length),
      crc: png.readUInt32BE(offset + 8 + length),
    });
    offset += 12 + length;
  }
  return chunks;
}

function inflatedPixels(png: Buffer): Buffer {
  const idat = parseChunks(png).filter((chunk) => chunk.type === 'IDAT');
  return zlib.inflateSync(Buffer.concat(idat.map((chunk) => chunk.data)));
}

test('кодировщик даёт валидный PNG: сигнатура, IHDR 256x256 RGBA, CRC всех чанков', () => {
  const png = buildIconPng();
  const chunks = parseChunks(png);
  assert.deepEqual(
    chunks.map((chunk) => chunk.type),
    ['IHDR', 'IDAT', 'IEND'],
  );
  const header = chunks[0]?.data as Buffer;
  assert.equal(header.readUInt32BE(0), ICON_SIZE);
  assert.equal(header.readUInt32BE(4), ICON_SIZE);
  assert.equal(header[8], 8);
  assert.equal(header[9], 6);
  for (const chunk of chunks)
    assert.equal(
      chunk.crc,
      crc32(Buffer.concat([Buffer.from(chunk.type, 'latin1'), chunk.data])),
      chunk.type,
    );
  assert.equal(inflatedPixels(png).length, (ICON_SIZE * 4 + 1) * ICON_SIZE);
  assert.ok(png.length <= 200 * 1024);
});

test('crc32 совпадает с эталонным значением и вывод детерминирован', () => {
  assert.equal(crc32(Buffer.from('123456789')), 0xcbf43926);
  assert.ok(buildIconPng().equals(buildIconPng()));
  assert.throws(() => encodePng(2, 2, new Uint8Array(3)), RangeError);
});

test('закоммиченный resources/icon.png соответствует генератору (IHDR и распакованные данные)', () => {
  const committed = fs.readFileSync(path.resolve(__dirname, '../../resources/icon.png'));
  const generated = buildIconPng();
  assert.ok(
    parseChunks(committed)[0]?.data.equals(parseChunks(generated)[0]?.data as Buffer),
    'IHDR',
  );
  assert.ok(inflatedPixels(committed).equals(inflatedPixels(generated)), 'pixel data');
});

test('импорт iconEncoder не пишет файлов и не печатает вывода', () => {
  const target = path.resolve(__dirname, '../../resources/icon.png');
  const before = fs.statSync(target).mtimeMs;
  const result = spawnSync(
    process.execPath,
    ['--import', 'tsx', '-e', "import('./scripts/iconEncoder.ts')"],
    { cwd: path.resolve(__dirname, '../..'), encoding: 'utf8' },
  );
  assert.equal(result.status, 0, result.stderr);
  assert.equal(result.stdout, '');
  assert.equal(fs.statSync(target).mtimeMs, before);
});
