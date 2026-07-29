import { readdir, readFile, writeFile } from 'node:fs/promises';
import { join, resolve } from 'node:path';
import { pathToFileURL } from 'node:url';

const TRAILING_SOURCE_MAP_DIRECTIVE =
	/(^|\r?\n)[ \t]*\/\/[#@][ \t]*sourceMappingURL=[^\r\n]*(?:\r?\n)*$/u;

/**
 * @param {string} content
 * @returns {string}
 */
export function stripTrailingSourceMapDirectives(content) {
	let sanitized = content;
	while (TRAILING_SOURCE_MAP_DIRECTIVE.test(sanitized)) {
		sanitized = sanitized.replace(TRAILING_SOURCE_MAP_DIRECTIVE, '$1');
	}
	return sanitized;
}

/**
 * @param {string} directory
 * @returns {Promise<{ scannedFiles: number; modifiedFiles: number }>}
 */
export async function stripSourceMapDirectivesInDirectory(directory) {
	let scannedFiles = 0;
	let modifiedFiles = 0;

	for (const entry of await readdir(directory, { withFileTypes: true })) {
		const path = join(directory, entry.name);
		if (entry.isDirectory()) {
			const nested = await stripSourceMapDirectivesInDirectory(path);
			scannedFiles += nested.scannedFiles;
			modifiedFiles += nested.modifiedFiles;
			continue;
		}
		if (!entry.isFile() || !(entry.name.endsWith('.js') || entry.name.endsWith('.mjs'))) {
			continue;
		}

		scannedFiles += 1;
		const content = await readFile(path, 'utf8');
		const sanitized = stripTrailingSourceMapDirectives(content);
		if (sanitized !== content) {
			await writeFile(path, sanitized, 'utf8');
			modifiedFiles += 1;
		}
	}

	return { scannedFiles, modifiedFiles };
}

async function main() {
	const outputDirectory = resolve(process.argv[2] ?? 'build');
	const result = await stripSourceMapDirectivesInDirectory(outputDirectory);
	console.log(
		`Sanitized ${result.modifiedFiles} of ${result.scannedFiles} JavaScript assets in ${outputDirectory}`
	);
}

const invokedPath = process.argv[1] ? pathToFileURL(resolve(process.argv[1])).href : undefined;
if (invokedPath === import.meta.url) {
	await main();
}
