import { readFileSync } from 'node:fs';

import { compile } from 'svelte/compiler';
import { describe, expect, it } from 'vitest';

const readRoute = (relativePath: string) =>
	readFileSync(new URL(relativePath, import.meta.url), { encoding: 'utf8' });

describe('Material Graph Studio route hardening', () => {
	it.each([
		['auth', '../auth/+page.svelte'],
		['admin', '../(app)/admin/+layout.svelte'],
		['workspace', '../(app)/workspace/+layout.svelte']
	])('keeps the %s route compilable', (_name, relativePath) => {
		const source = readRoute(relativePath);
		const result = compile(source, { generate: 'client' });

		expect(result.warnings).toEqual([]);
	});

	it('renders only session initialization while auth is disabled', () => {
		const source = readRoute('../auth/+page.svelte');

		expect(source).toContain('$config?.features?.auth !== true');
		expect(source).toContain('data-testid="studio-session-init"');
		expect(source).toContain('正在建立研究会话');
		expect(source).toContain('await signInHandler()');
	});

	it.each([
		['admin', '../(app)/admin/+layout.svelte'],
		['workspace', '../(app)/workspace/+layout.svelte']
	])('redirects direct %s navigation without rendering product controls', (_name, relativePath) => {
		const source = readRoute(relativePath);

		expect(source).toContain("void goto('/', { replaceState: true })");
		expect(source).not.toContain('<slot');
		expect(source).not.toContain('<nav');
	});
});
