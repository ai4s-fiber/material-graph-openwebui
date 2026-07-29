import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';
import { compile } from 'svelte/compiler';

const sidebarPath = fileURLToPath(new URL('../StudioSidebar.svelte', import.meta.url));
const layoutPath = fileURLToPath(
	new URL('../../../../routes/(app)/+layout.svelte', import.meta.url)
);
const sidebarSource = readFileSync(sidebarPath, 'utf8');
const layoutSource = readFileSync(layoutPath, 'utf8');

describe('Material Graph Studio shell', () => {
	it('compiles the dedicated sidebar', () => {
		expect(() =>
			compile(sidebarSource, { filename: sidebarPath, generate: 'server' })
		).not.toThrow();
	});

	it('limits the sidebar to new chat, history search, and chat history', () => {
		expect(sidebarSource).toContain(
			"STUDIO_SIDEBAR_SURFACES = ['new-chat', 'history-search', 'chat-history']"
		);
		expect(sidebarSource).toContain('id="sidebar-new-chat-button"');
		expect(sidebarSource).toContain('id="sidebar-search-button"');
		expect(sidebarSource).toContain('<ChatItem');

		for (const forbiddenSurface of [
			'UserMenu',
			'PinnedModelList',
			'PinnedNoteList',
			'/workspace',
			'/notes',
			'/channels',
			'/automations',
			'/calendar',
			'/playground'
		]) {
			expect(sidebarSource).not.toContain(forbiddenSurface);
		}
	});

	it('hard-gates settings and model-selection entry points in the app layout', () => {
		expect(layoutSource).toContain(
			"import StudioSidebar from '$lib/components/layout/StudioSidebar.svelte'"
		);
		expect(layoutSource).toContain('<StudioSidebar />');

		for (const disabledEntryPoint of [
			'SettingsModal',
			'OPEN_SETTINGS',
			'OPEN_MODEL_SELECTOR',
			'SHOW_SHORTCUTS',
			'NEW_TEMPORARY_CHAT'
		]) {
			expect(layoutSource).not.toContain(disabledEntryPoint);
		}
	});
});
