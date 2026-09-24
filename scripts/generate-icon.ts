// CLI: пишет только resources/icon.png. Запуск: yarn generate:icon

import * as fs from 'node:fs';
import * as path from 'node:path';
import { buildIconPng } from './iconEncoder';

const target = path.resolve(__dirname, '..', 'resources', 'icon.png');
fs.mkdirSync(path.dirname(target), { recursive: true });
const png = buildIconPng();
fs.writeFileSync(target, png);
process.stdout.write(`wrote ${target} (${png.length} bytes)\n`);
