import type {
	AssistantFormDefinition,
	MaterialGraphNode,
	MaterialGraphPatch,
	MaterialGraphSnapshot
} from './types';

const failures = new Set([
	'failed',
	'failure',
	'error',
	'blocked',
	'budget_stopped',
	'budget_exceeded',
	'rejected',
	'cancelled',
	'canceled'
]);
export const MATERIAL_GRAPH_STATUS_HISTORY_LIMIT = 128;

export const isFailureOutcome = (value?: string | null) =>
	failures.has(
		String(value ?? '')
			.toLowerCase()
			.replaceAll('-', '_')
	);

export const outcomeLabel = (snapshot?: MaterialGraphSnapshot | null) => {
	const outcome = String(snapshot?.outcome ?? '')
		.toLowerCase()
		.replaceAll('-', '_');
	if (!snapshot?.done) return snapshot?.resync_required ? '正在同步执行流程' : '实时执行流程';
	if (
		snapshot.success === true ||
		['success', 'succeeded', 'complete', 'completed'].includes(outcome)
	)
		return '执行完成';
	return (
		(
			{
				failed: '执行失败',
				failure: '执行失败',
				error: '执行失败',
				blocked: '执行阻塞',
				budget_stopped: '预算停止',
				budget_exceeded: '预算停止',
				rejected: '执行被拒绝',
				cancelled: '执行取消',
				canceled: '执行取消'
			} as Record<string, string>
		)[outcome] ?? '执行已停止'
	);
};

const replaceNodes = (nodes: MaterialGraphNode[], updates: MaterialGraphNode[]) => {
	const byId = new Map(nodes.map((node, index) => [node.id, index]));
	const next = nodes.map((node) => ({ ...node }));
	for (const update of updates) {
		const index = byId.get(update.id);
		if (index === undefined) {
			byId.set(update.id, next.length);
			next.push({ ...update });
		} else {
			next[index] = { ...update };
		}
	}
	return next;
};

export const applyMaterialGraphPatch = (
	snapshot: MaterialGraphSnapshot,
	patch: MaterialGraphPatch
): MaterialGraphSnapshot => {
	const next = {
		...snapshot,
		nodes: [...(snapshot.nodes ?? [])],
		edges: [...(snapshot.edges ?? [])],
		logs: [...(snapshot.logs ?? [])]
	} as MaterialGraphSnapshot & Record<string, unknown>;
	if (patch.set) Object.assign(next, patch.set);
	for (const key of patch.unset ?? []) delete next[key];
	if (patch.node_updates?.length) next.nodes = replaceNodes(next.nodes, patch.node_updates);
	if (patch.logs !== undefined) next.logs = [...patch.logs];
	return next;
};

export const reduceMaterialGraph = (events: any[]): MaterialGraphSnapshot | null => {
	let result: MaterialGraphSnapshot | null = null;
	for (const event of events) {
		if (event?.action !== 'material_graph' || !event.run_id) continue;
		if (!result || result.run_id !== event.run_id)
			result = { run_id: event.run_id, nodes: [], edges: [], logs: [] };
		const previous = result;
		const kind = String(event.event_type ?? event.type ?? '').toLowerCase();
		const incomingVersion = Number.isInteger(event.graph_version)
			? Number(event.graph_version)
			: undefined;

		if (kind === 'graph_delta' && event.patch) {
			const baseVersion = Number.isInteger(event.base_version)
				? Number(event.base_version)
				: undefined;
			if (
				previous.graph_version === undefined ||
				baseVersion === undefined ||
				incomingVersion === undefined ||
				baseVersion !== previous.graph_version ||
				incomingVersion !== baseVersion + 1
			) {
				result = {
					...previous,
					resync_required: true,
					resync_url: event.resync_url ?? previous.resync_url
				};
				continue;
			}
			result = {
				...applyMaterialGraphPatch(previous, event.patch),
				graph_version: incomingVersion,
				contract_version: event.contract_version ?? previous.contract_version,
				resync_required: false,
				resync_url: undefined
			};
			continue;
		}

		if (
			incomingVersion !== undefined &&
			previous.graph_version !== undefined &&
			incomingVersion < previous.graph_version
		)
			continue;
		const workflow = event.workflow ?? event.workflow_definition;
		const fullSnapshot = kind === 'graph_snapshot';
		const next: MaterialGraphSnapshot = {
			...previous,
			...event,
			workflow: workflow ?? previous.workflow,
			workflow_definition: event.workflow_definition ?? previous.workflow_definition,
			nodes:
				fullSnapshot && Array.isArray(event.nodes)
					? event.nodes
					: event.nodes?.length
						? event.nodes
						: workflow?.nodes?.length
							? workflow.nodes
							: previous.nodes,
			edges:
				fullSnapshot && Array.isArray(event.edges)
					? event.edges
					: event.edges?.length
						? event.edges
						: workflow?.edges?.length
							? workflow.edges
							: previous.edges,
			logs: event.logs ?? previous.logs,
			resync_required: Boolean(event.resync_required)
		};
		if (next.done && isFailureOutcome(next.outcome)) next.success = false;
		result = next;
	}
	return result;
};

export const materialGraphTopologyKey = (snapshot?: MaterialGraphSnapshot | null) =>
	JSON.stringify({
		nodes: (snapshot?.nodes ?? []).map((node) => [node.id, node.label]),
		edges: (snapshot?.edges ?? []).map((edge) => [edge.source, edge.target, edge.kind ?? ''])
	});

const assistantFormIdentity = (event: any) => {
	if (event?.action !== 'assistant_form') return null;
	return [event.run_id ?? '', event.checkpoint_id ?? 'checkpoint', event.form_id ?? 'form'].join(
		':'
	);
};

export const appendMaterialGraphStatus = (
	history: any[] = [],
	event: any,
	limit = MATERIAL_GRAPH_STATUS_HISTORY_LIMIT
) => {
	const boundedLimit = Math.max(16, limit);
	const identity = assistantFormIdentity(event);
	let next = [...history];
	if (identity) {
		const existingIndex = next.findIndex((item) => assistantFormIdentity(item) === identity);
		if (existingIndex >= 0) {
			const previous = next[existingIndex];
			// A stale replay must never resurrect a form already resolved by a
			// later authoritative graph event.
			if (previous?.resolved && !event?.resolved) return next;
			next[existingIndex] = { ...previous, ...event };
		} else next.push(event);
	} else next.push(event);
	if (next.length <= boundedLimit) return next;
	const graph = reduceMaterialGraph(next);
	const nonGraph = next
		.filter((item) => item?.action !== 'material_graph')
		.slice(-(boundedLimit - (graph ? 1 : 0)));
	if (!graph) return next.slice(-boundedLimit);
	return [
		...nonGraph,
		{
			...graph,
			action: 'material_graph',
			event_type: 'graph_snapshot',
			snapshot_reason: 'history_compaction'
		}
	];
};

export const latestMaterialGraph = (history: any): MaterialGraphSnapshot | null => {
	const events: any[] = [];
	for (const message of Object.values(history?.messages ?? {}) as any[])
		events.push(...(message?.statusHistory ?? []));
	return reduceMaterialGraph(events);
};

export const latestAssistantForm = (statusHistory: any[] = []): AssistantFormDefinition | null => {
	for (let index = statusHistory.length - 1; index >= 0; index--) {
		const form = statusHistory[index];
		if (form?.action === 'assistant_form' && !form.resolved) return form;
	}
	return null;
};

export type MaterialGraphResumeMerge = {
	message: any;
	/** Persist only after an authoritative resume boundary has resolved the original checkpoint. */
	persist: boolean;
};

let resumeEpochSequence = 0;

export const createMaterialGraphResumeEpoch = () => {
	resumeEpochSequence += 1;
	return `${Date.now().toString(36)}-${resumeEpochSequence.toString(36)}`;
};

const materialGraphRunId = (event: any) => String(event?.run_id ?? event?.runId ?? '').trim();

const directResumeAttempt = (message: any, runId: string) =>
	message?.materialGraphResumeAttempts?.[runId];

const resolveDirectResumeForm = (history: any[], attempt: any, epoch: string) => {
	if (!attempt || attempt.epoch !== epoch) return history;
	return history.map((entry) => {
		if (
			entry?.action !== 'assistant_form' ||
			String(entry?.run_id ?? '') !== String(attempt.run_id ?? '') ||
			String(entry?.checkpoint_id ?? '') !== String(attempt.checkpoint_id ?? '') ||
			String(entry?.form_id ?? '') !== String(attempt.form_id ?? '')
		)
			return entry;
		return {
			...entry,
			resolved: true,
			material_graph_source: 'direct_resume',
			material_graph_epoch: epoch
		};
	});
};

export const shouldAcceptMaterialGraphStatus = (
	message: any,
	event: any,
	source: 'pipe' | 'direct_resume',
	epoch?: string
) => {
	const runId = materialGraphRunId(event);
	if (!runId) return true;
	const activeEpoch = message?.materialGraphResumeEpochs?.[runId];
	if (!activeEpoch) return true;
	return source === 'direct_resume' && epoch === activeEpoch;
};

/**
 * Merge resume-stream events into the message owned by the chat history.
 *
 * ResponseMessage keeps a local clone for rendering, but Chat.svelte treats
 * history.messages as canonical and can refresh that clone while the original
 * pipe stream is winding down. Updating only the clone therefore loses the
 * replacement human-review form. This helper performs one canonical assignment
 * per resume event so a later render always starts from the merged history.
 */
export const mergeMaterialGraphResumeEvent = (
	history: any,
	messageId: string,
	event: any
): MaterialGraphResumeMerge | null => {
	const current = history?.messages?.[messageId];
	if (!current) return null;

	const next = { ...current };
	const runId = String(event?.run_id ?? event?.status?.run_id ?? '').trim();
	const source = event?.source;
	const epoch = String(event?.epoch ?? '').trim();
	if (source === 'direct_resume' && event?.phase === 'begin') {
		if (!runId || !epoch) return null;
		const submittedForm =
			event?.status?.action === 'assistant_form'
				? event.status
				: latestAssistantForm(current.statusHistory ?? []);
		next.materialGraphResumeEpochs = {
			...(current.materialGraphResumeEpochs ?? {}),
			[runId]: epoch
		};
		if (submittedForm) {
			next.materialGraphResumeAttempts = {
				...(current.materialGraphResumeAttempts ?? {}),
				[runId]: {
					run_id: runId,
					epoch,
					checkpoint_id: submittedForm.checkpoint_id ?? '',
					form_id: submittedForm.form_id ?? ''
				}
			};
		}
		history.messages[messageId] = next;
		return { message: next, persist: false };
	}
	if (
		source === 'direct_resume' &&
		(!runId ||
			!epoch ||
			!shouldAcceptMaterialGraphStatus(current, { run_id: runId }, source, epoch))
	)
		return null;

	if (event?.token)
		next.content = event.replaceContent ? event.token : `${current.content ?? ''}${event.token}`;
	const status =
		event?.status && source === 'direct_resume'
			? {
					...event.status,
					material_graph_source: source,
					material_graph_epoch: epoch
				}
			: event?.status;
	if (status) next.statusHistory = appendMaterialGraphStatus(current.statusHistory ?? [], status);
	const eventKind = String(
		status?.event_type ?? status?.type ?? event?.raw?.event_type ?? event?.raw?.type ?? ''
	)
		.trim()
		.toLowerCase()
		.replaceAll('-', '_');
	const authoritativeBoundary =
		source === 'direct_resume' &&
		(['terminal', 'done'].includes(eventKind) || status?.done === true);
	if (authoritativeBoundary) {
		next.statusHistory = resolveDirectResumeForm(
			next.statusHistory ?? current.statusHistory ?? [],
			directResumeAttempt(current, runId),
			epoch
		);
	}

	history.messages[messageId] = next;
	return {
		message: next,
		persist:
			authoritativeBoundary ||
			Boolean(status?.action === 'assistant_form' && status.resolved === true)
	};
};
