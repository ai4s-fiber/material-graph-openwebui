import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';
import { compile } from 'svelte/compiler';

const chatPath = fileURLToPath(new URL('../../Chat.svelte', import.meta.url));
const messageInputPath = fileURLToPath(new URL('../../MessageInput.svelte', import.meta.url));
const chatSource = readFileSync(chatPath, 'utf8');
const messageInputSource = readFileSync(messageInputPath, 'utf8');

describe('Material Graph Studio message input', () => {
	it('threads studio mode from Chat into the navbar and message input', () => {
		expect(chatSource).toContain('export let studioMode = true;');
		expect(chatSource).toMatch(/<Navbar[\s\S]*?\{studioMode\}[\s\S]*?\/>/);
		expect(chatSource).toMatch(/<MessageInput[\s\S]*?\{studioMode\}[\s\S]*?\/>/);
	});

	it('keeps the compact text, attachment, send, and stop controls available', () => {
		expect(messageInputSource).toContain('export let studioMode = false;');
		expect(messageInputSource).toContain('id="chat-input"');
		expect(messageInputSource).toContain('id="studio-file-upload-button"');
		expect(messageInputSource).toContain('id="send-message-button"');
		expect(messageInputSource).toContain("content={$i18n.t('Stop')}");
	});

	it('gates Open WebUI integrations and advanced controls outside studio mode', () => {
		expect(messageInputSource).toContain('{#if !studioMode}');
		expect(messageInputSource).toMatch(/\{#if !studioMode\}[\s\S]*?<ToolServersModal/);
		expect(messageInputSource).toMatch(/\{#if !studioMode\}[\s\S]*?<SkillsModal/);
		expect(messageInputSource).toMatch(/\{:else\}\s*<InputMenu/);
		expect(messageInputSource).toMatch(
			/\{#if !studioMode && prompt !== ''[\s\S]*?create-note-button/
		);
		expect(messageInputSource).toMatch(
			/\{#if !studioMode && \(!history\?\.currentId[\s\S]*?<TerminalMenu/
		);
		expect(messageInputSource).toMatch(
			/\{#if !studioMode && prompt === ''[\s\S]*?aria-label=\{\$i18n\.t\('Voice mode'\)\}/
		);
		expect(messageInputSource).toContain('suggestions={studioMode ? [] : suggestions}');
		expect(messageInputSource).toContain('showFormattingToolbar={studioMode');
		expect(messageInputSource).toContain('autocomplete={!studioMode');
	});

	it('strips hidden Open WebUI capabilities from studio requests', () => {
		for (const requestField of ['filter_ids', 'tool_ids', 'skill_ids', 'terminal_id']) {
			expect(chatSource).toMatch(new RegExp(`${requestField}:[\\s\\S]{0,80}!studioMode`));
		}
		expect(chatSource).toContain('tool_servers: studioMode');
		expect(chatSource).toContain('features: studioMode ? {} : getFeatures()');
	});

	it('still compiles both Svelte components', () => {
		expect(() => compile(chatSource, { filename: chatPath, generate: 'ssr' })).not.toThrow();
		expect(() =>
			compile(messageInputSource, { filename: messageInputPath, generate: 'ssr' })
		).not.toThrow();
	});
});
