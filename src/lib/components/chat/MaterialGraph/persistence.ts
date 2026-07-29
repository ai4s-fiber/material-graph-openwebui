type SaveMessage = (messageId: string, message: any) => Promise<unknown> | unknown;

export type MaterialGraphResumePersistenceOptions = {
	history: any;
	messageId: string;
	saveMessage: SaveMessage;
	/**
	 * ResponseMessage supplies Svelte's `tick` so all synchronously merged SSE
	 * events have reached the canonical history object before it is cloned.
	 * Tests can omit it and remain framework-independent.
	 */
	settle?: () => Promise<unknown>;
};

/**
 * Persist one authoritative resume checkpoint from the canonical chat message.
 *
 * Resume events are merged into `history.messages[messageId]`, not into an
 * isolated rendering clone.  Reading that canonical object only after the
 * current UI turn has settled guarantees that the saved payload contains the
 * final assistant summary, execution graph, knowledge signals and replacement
 * human-review form as one atomic chat update.
 */
export const persistMaterialGraphResume = async ({
	history,
	messageId,
	saveMessage,
	settle = async () => undefined
}: MaterialGraphResumePersistenceOptions) => {
	await settle();
	const canonical = history?.messages?.[messageId];
	if (!canonical) throw new Error('Material Graph assistant message is no longer available');
	const snapshot = structuredClone(canonical);
	await saveMessage(messageId, snapshot);
	return snapshot;
};
