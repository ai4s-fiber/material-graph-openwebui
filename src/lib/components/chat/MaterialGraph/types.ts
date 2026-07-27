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
	status?: MaterialGraphSnapshot | AssistantFormDefinition;
	raw?: unknown;
};
export {
	appendMaterialGraphStatus,
	latestAssistantForm,
	latestMaterialGraph,
	materialGraphTopologyKey
} from './contract';
