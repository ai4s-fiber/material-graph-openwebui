import { mkdir, mkdtemp, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

import { afterEach, describe, expect, it } from 'vitest';

import { resolveAuthoritativePyodideVersion } from '../prepare-pyodide.js';

const temporaryDirectories: string[] = [];

async function createVersionFixture({
	dependencyRange,
	lockedVersion,
	installedVersion
}: {
	dependencyRange: string;
	lockedVersion: string;
	installedVersion: string;
}) {
	const root = await mkdtemp(join(tmpdir(), 'prepare-pyodide-'));
	temporaryDirectories.push(root);
	const installedPackageDirectory = join(root, 'node_modules', 'pyodide');
	await mkdir(installedPackageDirectory, { recursive: true });

	const packageLockPath = join(root, 'package-lock.json');
	const installedPackagePath = join(installedPackageDirectory, 'package.json');
	await Promise.all([
		writeFile(
			join(root, 'package.json'),
			JSON.stringify({ dependencies: { pyodide: dependencyRange } }),
			'utf8'
		),
		writeFile(
			packageLockPath,
			JSON.stringify({
				lockfileVersion: 3,
				packages: {
					'': { dependencies: { pyodide: dependencyRange } },
					'node_modules/pyodide': { version: lockedVersion }
				}
			}),
			'utf8'
		),
		writeFile(installedPackagePath, JSON.stringify({ version: installedVersion }), 'utf8')
	]);

	return { installedPackagePath, packageLockPath };
}

afterEach(async () => {
	await Promise.all(
		temporaryDirectories
			.splice(0)
			.map((directory) => rm(directory, { recursive: true, force: true }))
	);
});

describe('resolveAuthoritativePyodideVersion', () => {
	it('uses the installed lockfile version instead of the dependency range lower bound', async () => {
		const paths = await createVersionFixture({
			dependencyRange: '^0.28.2',
			lockedVersion: '0.28.3',
			installedVersion: '0.28.3'
		});

		await expect(resolveAuthoritativePyodideVersion(paths)).resolves.toBe('0.28.3');
	});

	it('fails closed when the installed package differs from package-lock', async () => {
		const paths = await createVersionFixture({
			dependencyRange: '^0.28.2',
			lockedVersion: '0.28.3',
			installedVersion: '0.28.2'
		});

		await expect(resolveAuthoritativePyodideVersion(paths)).rejects.toThrow(
			'Installed Pyodide version 0.28.2 does not match package-lock version 0.28.3'
		);
	});
});
