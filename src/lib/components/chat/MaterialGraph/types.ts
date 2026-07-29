export type MaterialGraphNodeStatus =
	| 'pending'
	| 'running'
	| 'complete'
	| 'completed'
	| 'awaiting_input'
	| 'awaiting_review'
	| 'failed'
	| 'blocked'
	| 'budget_stopped'
	| 'rejected'
	| 'error'
	| string;
export interface MaterialGraphNode {
	id: string;
	label: string;
	status?: MaterialGraphNodeStatus;
	description?: string;
	summary?: string;
	duration_ms?: number;
	duration?: string;
	[key: string]: unknown;
}
export interface MaterialGraphEdge {
	id?: string;
	source: string;
	target: string;
	kind?: string;
}
export interface MaterialGraphLog {
	node_id?: string;
	message: string;
	status?: string;
	timestamp?: string;
}
export interface WorkflowDefinition {
	id?: string;
	version?: string;
	nodes: MaterialGraphNode[];
	edges: MaterialGraphEdge[];
	[key: string]: unknown;
}
export interface MaterialGraphPatch {
	set?: Record<string, unknown>;
	unset?: string[];
	node_updates?: MaterialGraphNode[];
	logs?: MaterialGraphLog[];
}
export interface MaterialGraphSnapshot {
	action?: 'material_graph';
	event_type?: string;
	run_id: string;
	contract_version?: string;
	graph_version?: number;
	base_version?: number;
	patch?: MaterialGraphPatch;
	resync_required?: boolean;
	resync_url?: string;
	workflow?: WorkflowDefinition;
	workflow_definition?: WorkflowDefinition;
	checkpoint_id?: string;
	form_id?: string;
	current_node?: string | null;
	route_signal?: string | null;
	nodes: MaterialGraphNode[];
	edges: MaterialGraphEdge[];
	elapsed_ms?: number;
	logs?: MaterialGraphLog[];
	evidence_count?: number;
	done?: boolean;
	success?: boolean;
	outcome?: string;
	error_code?: string;
	retryable?: boolean;
	retry_after_seconds?: number;
}

export type MaterialGraphKnowledgeAgent =
	| 'material'
	| 'process'
	| 'performance_testing'
	| 'safety_quality'
	| 'evaluation'
	| 'experiment_design';

/**
 * `shared_retrieval` is deliberately not an Agent. It is the neutral staging
 * area used before the backend has supplied a real Agent View membership. That
 * lets the UI show an early, real retrieval without attributing it to an Agent.
 */
export type MaterialGraphKnowledgeZone = MaterialGraphKnowledgeAgent | 'shared_retrieval';

export interface MaterialGraphKnowledgeNode {
	id: string;
	label: string;
	agentView: MaterialGraphKnowledgeZone;
	agentViews?: MaterialGraphKnowledgeAgent[];
	description?: string;
	hit?: boolean;
	active?: boolean;
	metadata?: Record<string, unknown>;
}

export interface MaterialGraphKnowledgeEdge {
	id: string;
	source: string;
	target: string;
	relation?: string;
	agentViews?: MaterialGraphKnowledgeAgent[];
	active?: boolean;
	pulse?: boolean;
}

export interface MaterialGraphKnowledgeGraph {
	runId: string;
	phase: string;
	workflowNode?: string;
	graphId?: string;
	graphVersionLabel?: string;
	activeAgents: string[];
	nodes: MaterialGraphKnowledgeNode[];
	edges: MaterialGraphKnowledgeEdge[];
	pulse: Array<Record<string, any>>;
	receivedNodeCount: number;
	receivedEdgeCount: number;
	omittedNodeCount: number;
	omittedEdgeCount: number;
	truncated: boolean;
	updatedAt?: string;
}

/**
 * Raw, evidence-backed knowledge projection carried over SSE.
 *
 * It deliberately uses a distinct action so workflow reducers cannot mistake
 * recalled knowledge nodes for execution-graph nodes.
 */
export interface MaterialGraphKnowledgeSignal {
	action: 'material_graph_knowledge';
	type?: 'knowledge_signal';
	event_type: 'knowledge_signal';
	run_id: string;
	phase?: string;
	workflow_node?: string;
	graph_id?: string;
	graph_version_label?: string;
	active_agents?: string[];
	nodes?: Array<Record<string, unknown>>;
	edges?: Array<Record<string, unknown>>;
	pulse?: Array<Record<string, unknown>>;
	stats?: Record<string, unknown>;
	[key: string]: unknown;
}

export interface AssistantFormField {
	name?: string;
	key?: string;
	id?: string;
	label?: string;
	description?: string;
	type?: string;
	required?: boolean;
	default?: unknown;
	placeholder?: string;
	minimum?: number;
	maximum?: number;
	minItems?: number;
	maxItems?: number;
	multiple?: boolean;
	options?: Array<unknown | { value: unknown; label?: string }>;
}
export interface AssistantFormDefinition {
	action: 'assistant_form';
	form_id: string;
	run_id: string;
	contract_version?: string;
	checkpoint_id?: string;
	/** Authoritative status carried by a form event, when available. */
	status?: MaterialGraphNodeStatus | string;
	/** Current graph node/checkpoint metadata mirrored into the form event. */
	current_node?: string | null;
	graph_version?: number;
	outcome?: string;
	done?: boolean;
	resolved?: boolean;
	title?: string;
	description?: string;
	fields?: AssistantFormField[];
	schema?: Record<string, any>;
	defaults?: Record<string, unknown>;
	submit?: { method?: string; path?: string; url?: string; stream_path?: string };
	submission?: Record<string, unknown>;
	endpoint?: string;
	requires_response?: boolean;
}
export type ResumeEvent = {
	token?: string;
	/** Replace the stale awaiting-input summary with an authoritative final message. */
	replaceContent?: boolean;
	status?: MaterialGraphSnapshot | MaterialGraphKnowledgeSignal | AssistantFormDefinition;
	raw?: unknown;
	/** Direct-resume events outrank the older Pipe stream for the same run. */
	source?: 'direct_resume';
	/** A unique client epoch fences stale events from earlier resume attempts. */
	epoch?: string;
	phase?: 'begin' | 'event';
	run_id?: string;
};

/**
 * Result of a resume request. `advanced` is deliberately separate from the
 * HTTP/SSE transport succeeding: a stream can be healthy while the graph is
 * still waiting for the same input checkpoint.
 */
export interface ResumeResult {
	streamed: boolean;
	authoritative: boolean;
	advanced: boolean;
	awaitingInput: boolean;
	terminal: boolean;
	status?: string;
	outcome?: string;
	current_node?: string | null;
	graph_version?: number;
	checkpoint_id?: string | null;
	form_id?: string | null;
	fieldErrors?: Record<string, string>;
	message?: string;
}
export {
	appendMaterialGraphStatus,
	createMaterialGraphResumeEpoch,
	latestAssistantForm,
	mergeMaterialGraphResumeEvent,
	latestMaterialGraph,
	materialGraphTopologyKey,
	shouldAcceptMaterialGraphStatus
} from './contract';
export { latestKnowledgeGraph, normalizeKnowledgeGraph } from './knowledgeGraph';
