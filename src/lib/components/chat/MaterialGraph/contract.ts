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

export const appendMaterialGraphStatus = (
	history: any[] = [],
	event: any,
	limit = MATERIAL_GRAPH_STATUS_HISTORY_LIMIT
) => {
	const boundedLimit = Math.max(16, limit);
	const next = [...history, event];
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
	for (let index = statusHistory.length - 1; index >= 0; index--)
		if (statusHistory[index]?.action === 'assistant_form')
			return statusHistory[index]?.resolved ? null : statusHistory[index];
	return null;
};
