export type ChatCompletionNotificationContext = {
	eventChatId?: string | null;
	currentChatId?: string | null;
	authEnabled?: boolean | null;
};

/**
 * The no-auth Material Graph shell is a shared session, so a completion from
 * another chat must never expose its title or response body in the active page.
 * Authenticated Open WebUI deployments keep their existing background alerts.
 */
export function shouldShowChatCompletionNotification({
	eventChatId,
	currentChatId,
	authEnabled
}: ChatCompletionNotificationContext): boolean {
	if (authEnabled !== false) {
		return true;
	}

	return Boolean(eventChatId && currentChatId && eventChatId === currentChatId);
}
