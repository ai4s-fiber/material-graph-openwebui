import { readFileSync } from 'node:fs';
import { compile } from 'svelte/compiler';
import { describe, expect, it } from 'vitest';

import { shouldShowChatCompletionNotification } from '../notificationPolicy';

const rootLayoutSource = readFileSync(
	new URL('../../../../../routes/+layout.svelte', import.meta.url),
	'utf8'
);

describe('Material Graph completion notification isolation', () => {
	it('suppresses another chat completion in the shared no-auth shell', () => {
		expect(
			shouldShowChatCompletionNotification({
				authEnabled: false,
				currentChatId: 'chat-current',
				eventChatId: 'chat-background'
			})
		).toBe(false);
	});

	it('allows the current chat completion in the shared no-auth shell', () => {
		expect(
			shouldShowChatCompletionNotification({
				authEnabled: false,
				currentChatId: 'chat-current',
				eventChatId: 'chat-current'
			})
		).toBe(true);
	});

	it('fails closed when a no-auth completion cannot be scoped to a current chat', () => {
		expect(
			shouldShowChatCompletionNotification({
				authEnabled: false,
				currentChatId: null,
				eventChatId: 'chat-background'
			})
		).toBe(false);
		expect(
			shouldShowChatCompletionNotification({
				authEnabled: false,
				currentChatId: 'chat-current',
				eventChatId: null
			})
		).toBe(false);
	});

	it('preserves existing background notifications for authenticated deployments', () => {
		expect(
			shouldShowChatCompletionNotification({
				authEnabled: true,
				currentChatId: 'chat-current',
				eventChatId: 'chat-background'
			})
		).toBe(true);
		expect(
			shouldShowChatCompletionNotification({
				authEnabled: undefined,
				currentChatId: 'chat-current',
				eventChatId: 'chat-background'
			})
		).toBe(true);
	});

	it('applies the gate before deriving notification content without blocking history refreshes', () => {
		const gateIndex = rootLayoutSource.indexOf('!shouldShowChatCompletionNotification({');
		const previewIndex = rootLayoutSource.indexOf('const contentPreview =');
		const titleRefreshIndex = rootLayoutSource.indexOf("type === 'chat:title'", previewIndex);

		expect(gateIndex).toBeGreaterThan(-1);
		expect(previewIndex).toBeGreaterThan(gateIndex);
		expect(titleRefreshIndex).toBeGreaterThan(previewIndex);
		expect(rootLayoutSource).toContain('authEnabled: $config?.features?.auth');
		expect(rootLayoutSource).toContain(
			'await chats.set(await getChatList(localStorage.token, $currentChatPage));'
		);
	});

	it('keeps the root event layout compilable', () => {
		expect(() => compile(rootLayoutSource, { generate: 'client' })).not.toThrow();
	});
});
