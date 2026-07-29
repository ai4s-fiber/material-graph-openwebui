import type {
	MaterialGraphKnowledgeAgent,
	MaterialGraphKnowledgeEdge,
	MaterialGraphKnowledgeGraph,
	MaterialGraphKnowledgeNode,
	MaterialGraphKnowledgeZone
} from './types';

export const AGENT_VIEW_ROLES = [
	'material',
	'process',
	'performance_testing',
	'safety_quality',
	'evaluation',
	'experiment_design'
] as const;

export type AgentViewRole = (typeof AGENT_VIEW_ROLES)[number];
export const SHARED_RETRIEVAL_ZONE = 'shared_retrieval' as const;
export type KnowledgeGraphZone = AgentViewRole | typeof SHARED_RETRIEVAL_ZONE;

export const AGENT_VIEW_META: Record<
	KnowledgeGraphZone,
	{ label: string; color: string; soft: string }
> = {
	material: { label: '材料设计', color: '#e88b55', soft: '#fff1e9' },
	process: { label: '工艺设计', color: '#5c9fd6', soft: '#eaf5ff' },
	performance_testing: { label: '性能测试', color: '#8e7bd8', soft: '#f2efff' },
	safety_quality: { label: '安全质量', color: '#d36882', soft: '#fff0f3' },
	evaluation: { label: '综合评价', color: '#46a89a', soft: '#eafaf7' },
	experiment_design: { label: '实验设计', color: '#c19a42', soft: '#fff9e8' },
	shared_retrieval: { label: '共同召回', color: '#748f87', soft: '#edf3f0' }
};

export const MAX_VISIBLE_KNOWLEDGE_NODES_PER_ROLE = 14;
export const MAX_VISIBLE_KNOWLEDGE_EDGES = 80;

const roleAliases: Record<string, AgentViewRole> = {
	material: 'material',
	material_design: 'material',
	material_designer: 'material',
	process: 'process',
	process_design: 'process',
	process_designer: 'process',
	performance: 'performance_testing',
	performance_prediction: 'performance_testing',
	performance_testing: 'performance_testing',
	performance_test: 'performance_testing',
	safety: 'safety_quality',
	safety_quality: 'safety_quality',
	quality: 'safety_quality',
	evaluation: 'evaluation',
	experiment: 'experiment_design',
	experiment_design: 'experiment_design',
	experiment_designer: 'experiment_design'
};

const asRecord = (value: unknown): Record<string, any> | null =>
	value && typeof value === 'object' ? (value as Record<string, any>) : null;

const asRole = (value: unknown): AgentViewRole | null => {
	const key = String(value ?? '')
		.trim()
		.toLowerCase()
		.replaceAll('-', '_');
	return roleAliases[key] ?? null;
};

const rolesFor = (row: Record<string, any>): MaterialGraphKnowledgeAgent[] => {
	const values = [
		...(Array.isArray(row.agent_roles) ? row.agent_roles : []),
		...(Array.isArray(row.agent_views) ? row.agent_views : []),
		row.agent_view,
		row.agent_role,
		row.agent,
		row.role,
		row.view_id
	];
	const roles = values
		.map(asRole)
		.filter((value): value is MaterialGraphKnowledgeAgent => Boolean(value));
	return AGENT_VIEW_ROLES.filter((role) => roles.includes(role));
};

const pairKey = (source: unknown, target: unknown) => `${String(source)}\u0000${String(target)}`;

const eventPayload = (raw: unknown): Record<string, any> | null => {
	let event = asRecord(raw);
	if (!event) return null;
	if (event.event?.type === 'knowledge_signal') event = asRecord(event.event.data) ?? event;
	if (event.event?.type === 'status') event = asRecord(event.event.data) ?? event;
	if (event.data?.type === 'knowledge_signal') event = asRecord(event.data.data) ?? event;
	if (event.data?.type === 'status') event = asRecord(event.data.data) ?? event;
	if (event.payload?.type === 'knowledge_signal') event = asRecord(event.payload) ?? event;
	return event;
};

const selectedIds = (items: unknown[], keys: string[]) => {
	const result = new Set<string>();
	for (const item of items ?? []) {
		if (typeof item === 'string') result.add(item);
		const row = asRecord(item);
		if (!row) continue;
		for (const key of keys) if (row[key] != null) result.add(String(row[key]));
		for (const key of ['node_ids', 'nodes', 'edge_ids', 'edges']) {
			if (Array.isArray(row[key]))
				for (const id of row[key]) if (typeof id === 'string') result.add(id);
		}
	}
	return result;
};

/** Normalize explicit backend graph entities, including authoritative empty knowledge signals. */
export const normalizeKnowledgeGraph = (raw: unknown): MaterialGraphKnowledgeGraph | null => {
	const payload = eventPayload(raw);
	if (
		!payload ||
		(payload.type !== 'knowledge_signal' && payload.event_type !== 'knowledge_signal')
	)
		return null;
	const source = asRecord(payload.knowledge_graph) ?? payload;
	const rawNodes = Array.isArray(source.nodes) ? source.nodes : [];
	const rawEdges = Array.isArray(source.edges) ? source.edges : [];
	const rawPulses = Array.isArray(payload.pulse)
		? payload.pulse
		: Array.isArray(source.pulse)
			? source.pulse
			: [];
	const retrieved = selectedIds(
		[
			...(Array.isArray(payload.retrieval_events) ? payload.retrieval_events : []),
			...(Array.isArray(source.retrieval_events) ? source.retrieval_events : []),
			...(Array.isArray(payload.retrieved_nodes) ? payload.retrieved_nodes : []),
			...(Array.isArray(payload.retrieved_edges) ? payload.retrieved_edges : [])
		],
		['id', 'node_id', 'edge_id']
	);
	const activeEdgeIds = selectedIds(rawPulses, ['id', 'pulse_id', 'edge_id']);
	const pulseNodeIds = selectedIds(rawPulses, ['node_id', 'source', 'target']);
	const activeEdgePairs = new Set(
		rawPulses
			.map((value) => asRecord(value))
			.filter((value): value is Record<string, any> =>
				Boolean(value?.source != null && value?.target != null)
			)
			.map((value) => pairKey(value.source, value.target))
	);

	const nodes: MaterialGraphKnowledgeNode[] = [];
	const seenNodes = new Set<string>();
	for (const value of rawNodes) {
		const row = asRecord(value);
		if (!row || row.id == null) continue;
		const id = String(row.id);
		const agentViews = rolesFor(row);
		const agentView: MaterialGraphKnowledgeZone = agentViews[0] ?? SHARED_RETRIEVAL_ZONE;
		if (seenNodes.has(id)) continue;
		seenNodes.add(id);
		nodes.push({
			id,
			label: String(row.label ?? row.name ?? row.title ?? id),
			agentView,
			agentViews,
			description: row.description ?? row.summary ?? row.type ?? row.entity_type,
			hit: Boolean(row.hit ?? row.retrieved ?? row.recalled ?? retrieved.has(id)),
			active: Boolean(row.active ?? row.in_use ?? pulseNodeIds.has(id)),
			metadata: row.metadata ?? row.provenance ?? undefined
		});
	}

	const nodeById = new Map(nodes.map((node) => [node.id, node]));
	const edges: MaterialGraphKnowledgeEdge[] = [];
	const seenEdges = new Set<string>();
	for (const value of rawEdges) {
		const row = asRecord(value);
		if (!row || row.source == null || row.target == null) continue;
		const sourceId = String(row.source);
		const targetId = String(row.target);
		if (!nodeById.has(sourceId) || !nodeById.has(targetId)) continue;
		const id = String(row.id ?? `${sourceId}->${targetId}`);
		if (seenEdges.has(id)) continue;
		seenEdges.add(id);
		edges.push({
			id,
			source: sourceId,
			target: targetId,
			relation: row.relation ?? row.kind ?? row.label,
			agentViews: rolesFor(row),
			active: Boolean(
				(row.active ?? row.retrieved ?? row.recalled ?? activeEdgeIds.has(id)) || retrieved.has(id)
			),
			pulse: Boolean(
				row.pulse ??
				row.streaming ??
				(activeEdgeIds.has(id) || activeEdgePairs.has(pairKey(sourceId, targetId)))
			)
		});
	}

	// The counters describe the payload that actually arrived from the backend.  When
	// the producer did not send counters, retain invalid / dangling explicit records
	// in that total so the UI can truthfully report that it deliberately withheld them.
	// Never derive these from a workflow state or a global graph count.
	const receivedNodeCount =
		Number(source.node_count ?? payload.stats?.total_nodes ?? rawNodes.length) || rawNodes.length;
	const receivedEdgeCount =
		Number(source.edge_count ?? payload.stats?.total_edges ?? rawEdges.length) || rawEdges.length;
	const kept: MaterialGraphKnowledgeNode[] = [];
	for (const role of [...AGENT_VIEW_ROLES, SHARED_RETRIEVAL_ZONE] as KnowledgeGraphZone[]) {
		const candidates = nodes.filter((node) => node.agentView === role);
		const ranked = candidates
			.map((node, index) => ({ node, index }))
			.sort(
				(left, right) =>
					Number(Boolean(right.node.active || right.node.hit)) -
						Number(Boolean(left.node.active || left.node.hit)) || left.index - right.index
			)
			.slice(0, MAX_VISIBLE_KNOWLEDGE_NODES_PER_ROLE)
			.sort((left, right) => left.index - right.index);
		kept.push(...ranked.map(({ node }) => node));
	}
	const keptIds = new Set(kept.map((node) => node.id));
	const boundedEdges = edges
		.filter((edge) => keptIds.has(edge.source) && keptIds.has(edge.target))
		.slice(0, MAX_VISIBLE_KNOWLEDGE_EDGES);
	const omittedNodeCount = Math.max(0, receivedNodeCount - kept.length);
	const omittedEdgeCount = Math.max(0, receivedEdgeCount - boundedEdges.length);

	return {
		runId: String(payload.run_id ?? source.run_id ?? ''),
		phase: String(payload.phase ?? source.phase ?? 'graph_retrieval'),
		workflowNode: payload.workflow_node ?? source.workflow_node,
		graphId: payload.graph_id ?? source.graph_id,
		graphVersionLabel: payload.graph_version_label ?? source.graph_version_label,
		activeAgents: Array.isArray(payload.active_agents) ? payload.active_agents.map(String) : [],
		nodes: kept,
		edges: boundedEdges,
		pulse: rawPulses
			.map((value) => asRecord(value))
			.filter((value): value is Record<string, any> => Boolean(value))
			.filter((value) => value.edge_id || value.source || value.target),
		receivedNodeCount,
		receivedEdgeCount,
		omittedNodeCount,
		omittedEdgeCount,
		truncated: omittedNodeCount > 0 || omittedEdgeCount > 0,
		updatedAt: payload.timestamp ?? payload.updated_at
	};
};

export const latestKnowledgeGraph = (history: any): MaterialGraphKnowledgeGraph | null => {
	const events: unknown[] = [];
	for (const message of Object.values(history?.messages ?? {}) as any[]) {
		// Status envelopes vary between the direct pipe and the persisted chat
		// transport.  Let the strict normalizer unwrap each one instead of making
		// a brittle outer-shape guess here.
		events.push(...(message?.statusHistory ?? []));
	}
	for (let index = events.length - 1; index >= 0; index--) {
		const normalized = normalizeKnowledgeGraph(events[index]);
		if (normalized) return normalized;
	}
	return null;
};
