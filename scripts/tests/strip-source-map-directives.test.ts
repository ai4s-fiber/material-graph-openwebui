import { mkdir, mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

import { describe, expect, it } from 'vitest';

import { stripSourceMapDirectivesInDirectory } from '../strip-source-map-directives.js';

describe('production source-map directive sanitizer', () => {
	it('removes only trailing directives from JavaScript assets recursively', async () => {
		const directory = await mkdtemp(join(tmpdir(), 'material-graph-source-maps-'));
		const nested = join(directory, 'assets');

		try {
			await mkdir(nested);
			await writeFile(
				join(directory, 'app.js'),
				'const app = true;\n//# sourceMappingURL=app.js.map\n'
			);
			await writeFile(
				join(nested, 'worker.mjs'),
				'export default true;\r\n//@ sourceMappingURL=worker.mjs.map\r\n'
			);
			await writeFile(
				join(nested, 'legacy.js'),
				'const legacy = true;\n//# sourceMappingURL=first.map\n//@ sourceMappingURL=second.map\n'
			);
			await writeFile(
				join(nested, 'untouched.js'),
				'const label = "sourceMappingURL=part-of-content";\n'
			);
			await writeFile(
				join(nested, 'styles.css'),
				'body {}\n/*# sourceMappingURL=styles.css.map */\n'
			);

			await expect(stripSourceMapDirectivesInDirectory(directory)).resolves.toEqual({
				scannedFiles: 4,
				modifiedFiles: 3
			});
			await expect(readFile(join(directory, 'app.js'), 'utf8')).resolves.toBe(
				'const app = true;\n'
			);
			await expect(readFile(join(nested, 'worker.mjs'), 'utf8')).resolves.toBe(
				'export default true;\r\n'
			);
			await expect(readFile(join(nested, 'legacy.js'), 'utf8')).resolves.toBe(
				'const legacy = true;\n'
			);
			await expect(readFile(join(nested, 'untouched.js'), 'utf8')).resolves.toBe(
				'const label = "sourceMappingURL=part-of-content";\n'
			);
			await expect(readFile(join(nested, 'styles.css'), 'utf8')).resolves.toBe(
				'body {}\n/*# sourceMappingURL=styles.css.map */\n'
			);
		} finally {
			await rm(directory, { recursive: true, force: true });
		}
	});
});
