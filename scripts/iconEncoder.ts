// Чистый детерминированный генератор иконки: глиф навигатора (дерево узлов на
// сплошном фоне) в RGBA-буфер и минимальный PNG-кодировщик. Без побочных
// эффектов при импорте и без внешних зависимостей (только node:zlib).

import * as zlib from 'node:zlib';

export const ICON_SIZE = 256;
export const PNG_SIGNATURE: Buffer = Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]);

type Color = readonly [number, number, number];

const BACKGROUND: Color = [0x1f, 0x29, 0x37];
const LINE: Color = [0x93, 0xc5, 0xfd];
const NODE: Color = [0xf9, 0xfa, 0xfb];
const ACCENT: Color = [0x38, 0xbd, 0xf8];

interface Point {
  readonly x: number;
  readonly y: number;
}

// Координаты заданы в долях стороны иконки (0..1).
const ROOT: Point = { x: 0.5, y: 0.24 };
const BRANCHES: readonly Point[] = [
  { x: 0.26, y: 0.52 },
  { x: 0.74, y: 0.52 },
];
const LEAVES: readonly Point[] = [
  { x: 0.14, y: 0.8 },
  { x: 0.38, y: 0.8 },
  { x: 0.62, y: 0.8 },
  { x: 0.86, y: 0.8 },
];

const SEGMENTS: readonly (readonly [Point, Point])[] = [
  [ROOT, BRANCHES[0] as Point],
  [ROOT, BRANCHES[1] as Point],
  [BRANCHES[0] as Point, LEAVES[0] as Point],
  [BRANCHES[0] as Point, LEAVES[1] as Point],
  [BRANCHES[1] as Point, LEAVES[2] as Point],
  [BRANCHES[1] as Point, LEAVES[3] as Point],
];

function distanceToSegment(px: number, py: number, a: Point, b: Point): number {
  const dx = b.x - a.x;
  const dy = b.y - a.y;
  const t = Math.max(0, Math.min(1, ((px - a.x) * dx + (py - a.y) * dy) / (dx * dx + dy * dy)));
  return Math.hypot(px - (a.x + t * dx), py - (a.y + t * dy));
}

function sample(x: number, y: number): Color {
  for (const [radius, points, color] of [
    [0.085, [ROOT], ACCENT],
    [0.065, BRANCHES, NODE],
    [0.05, LEAVES, NODE],
  ] as const)
    for (const point of points) if (Math.hypot(x - point.x, y - point.y) <= radius) return color;
  for (const [a, b] of SEGMENTS) if (distanceToSegment(x, y, a, b) <= 0.017) return LINE;
  return BACKGROUND;
}

/** Рисует иконку в RGBA (4 байта на пиксель), суперсэмплинг 3x3 для сглаживания. */
export function renderIconRgba(size: number = ICON_SIZE): Uint8Array {
  const pixels = new Uint8Array(size * size * 4);
  const grid = 3;
  for (let row = 0; row < size; row++)
    for (let column = 0; column < size; column++) {
      let red = 0;
      let green = 0;
      let blue = 0;
      for (let sy = 0; sy < grid; sy++)
        for (let sx = 0; sx < grid; sx++) {
          const [r, g, b] = sample(
            (column + (sx + 0.5) / grid) / size,
            (row + (sy + 0.5) / grid) / size,
          );
          red += r;
          green += g;
          blue += b;
        }
      const offset = (row * size + column) * 4;
      const count = grid * grid;
      pixels[offset] = Math.round(red / count);
      pixels[offset + 1] = Math.round(green / count);
      pixels[offset + 2] = Math.round(blue / count);
      pixels[offset + 3] = 255;
    }
  return pixels;
}

const CRC_TABLE: Uint32Array = (() => {
  const table = new Uint32Array(256);
  for (let index = 0; index < 256; index++) {
    let value = index;
    for (let bit = 0; bit < 8; bit++) value = value & 1 ? 0xedb88320 ^ (value >>> 1) : value >>> 1;
    table[index] = value >>> 0;
  }
  return table;
})();

export function crc32(data: Uint8Array): number {
  let crc = 0xffffffff;
  for (const byte of data) crc = (CRC_TABLE[(crc ^ byte) & 0xff] as number) ^ (crc >>> 8);
  return (crc ^ 0xffffffff) >>> 0;
}

/** Собирает PNG-чанк: длина, тип, данные, CRC32 от типа и данных. */
export function pngChunk(type: string, data: Uint8Array): Buffer {
  const typeBytes = Buffer.from(type, 'latin1');
  const chunk = Buffer.alloc(12 + data.length);
  chunk.writeUInt32BE(data.length, 0);
  typeBytes.copy(chunk, 4);
  Buffer.from(data).copy(chunk, 8);
  chunk.writeUInt32BE(crc32(chunk.subarray(4, 8 + data.length)), 8 + data.length);
  return chunk;
}

/** Кодирует RGBA 8 бит в PNG (фильтр 0, IDAT через zlib level 9). */
export function encodePng(width: number, height: number, rgba: Uint8Array): Buffer {
  if (rgba.length !== width * height * 4) throw new RangeError('RGBA buffer size mismatch');
  const header = Buffer.alloc(13);
  header.writeUInt32BE(width, 0);
  header.writeUInt32BE(height, 4);
  header[8] = 8; // bit depth
  header[9] = 6; // color type RGBA
  const stride = width * 4;
  const raw = Buffer.alloc((stride + 1) * height);
  for (let row = 0; row < height; row++)
    Buffer.from(rgba.buffer, rgba.byteOffset + row * stride, stride).copy(
      raw,
      row * (stride + 1) + 1,
    );
  return Buffer.concat([
    PNG_SIGNATURE,
    pngChunk('IHDR', header),
    pngChunk('IDAT', zlib.deflateSync(raw, { level: 9 })),
    pngChunk('IEND', Buffer.alloc(0)),
  ]);
}

/** PNG иконки расширения (256x256 RGBA). */
export function buildIconPng(): Buffer {
  return encodePng(ICON_SIZE, ICON_SIZE, renderIconRgba(ICON_SIZE));
}
