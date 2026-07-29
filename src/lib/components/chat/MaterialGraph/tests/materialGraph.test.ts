import { describe, expect, it } from 'vitest';
import {
	appendMaterialGraphStatus,
	latestAssistantForm,
	mergeMaterialGraphResumeEvent,
	materialGraphTopologyKey,
	reduceMaterialGraph,
	outcomeLabel
} from '../contract';
import { layoutWorkflow } from '../layout';

describe('Material Graph contracts', () => {
	it('preserves a complete workflow across partial events', () => {
		const graph = reduceMaterialGraph([
			{
				action: 'material_graph',
				run_id: 'r1',
				workflow: {
					nodes: [
						{ id: 'intake', label: 'Intake' },
						{ id: 'gate', label: 'Gate' }
					],
					edges: [{ source: 'intake', target: 'gate' }]
				},
				nodes: [],
				edges: []
			},
			{
				action: 'material_graph',
				run_id: 'r1',
				current_node: 'gate',
				nodes: [
					{ id: 'intake', label: 'Intake' },
					{ id: 'gate', label: 'Gate', status: 'awaiting_review' }
				],
				edges: []
			}
		]);
		expect(graph?.nodes.map((node) => node.id)).toEqual(['intake', 'gate']);
		expect(graph?.edges).toHaveLength(1);
		expect(layoutWorkflow(graph!.nodes, graph!.edges).nodes).toHaveLength(2);
	});
	it.each(['failed', 'blocked', 'budget_stopped', 'rejected'])(
		'does not present %s as success',
		(outcome) => {
			expect(
				outcomeLabel({ run_id: 'r', nodes: [], edges: [], done: true, success: false, outcome })
			).not.toBe('执行完成');
		}
	);
	it('selects only unresolved latest forms', () => {
		expect(
			latestAssistantForm([
				{ action: 'assistant_form', form_id: 'old', run_id: 'r', resolved: true },
				{ action: 'assistant_form', form_id: 'new', run_id: 'r' }
			])?.form_id
		).toBe('new');
	});
	it('keeps a replacement form visible after the prior checkpoint is resolved', () => {
		let history: any[] = [];
		history = appendMaterialGraphStatus(history, {
			action: 'assistant_form',
			run_id: 'r',
			checkpoint_id: 'cp-1',
			form_id: 'first'
		});
		history = appendMaterialGraphStatus(history, {
			action: 'assistant_form',
			run_id: 'r',
			checkpoint_id: 'cp-2',
			form_id: 'second'
		});
		history = appendMaterialGraphStatus(history, {
			action: 'assistant_form',
			run_id: 'r',
			checkpoint_id: 'cp-1',
			form_id: 'first',
			resolved: true
		});
		expect(latestAssistantForm(history)?.form_id).toBe('second');
	});
	it('merges resume events into canonical history across a stale source race', () => {
		const oldForm = {
			action: 'assistant_form',
			run_id: 'run-race',
			checkpoint_id: 'cp-input',
			form_id: 'task-spec:run-race',
			status: 'awaiting_input'
		};
		const history: any = {
			messages: {
				assistant: {
					id: 'assistant',
					content: '',
					statusHistory: [
						{
							action: 'material_graph',
							event_type: 'graph_snapshot',
							run_id: 'run-race',
							graph_version: 1,
							current_node: 'task_structure',
							status: 'awaiting_input'
						},
						oldForm
					]
				}
			}
		};

		const graphMerge = mergeMaterialGraphResumeEvent(history, 'assistant', {
			status: {
				action: 'material_graph',
				event_type: 'graph_snapshot',
				run_id: 'run-race',
				graph_version: 2,
				current_node: 'human_review',
				status: 'awaiting_review'
			}
		});
		const reviewMerge = mergeMaterialGraphResumeEvent(history, 'assistant', {
			status: {
				action: 'assistant_form',
				run_id: 'run-race',
				checkpoint_id: 'cp-review',
				form_id: 'human-review:run-race',
				status: 'awaiting_review'
			}
		});

		// The original pipe finishes after the resume stream and contributes
		// stale task-structure events to the same canonical message.
		history.messages.assistant.statusHistory = appendMaterialGraphStatus(
			history.messages.assistant.statusHistory,
			{
				action: 'material_graph',
				event_type: 'terminal',
				run_id: 'run-race',
				graph_version: 3,
				current_node: 'task_structure',
				status: 'awaiting_input'
			}
		);
		history.messages.assistant.statusHistory = appendMaterialGraphStatus(
			history.messages.assistant.statusHistory,
			oldForm
		);

		const resolvedMerge = mergeMaterialGraphResumeEvent(history, 'assistant', {
			status: { ...oldForm, resolved: true }
		});
		// A clone refreshed from Chat.svelte's canonical source must retain the
		// replacement form instead of reverting to the old intake checkpoint.
		const refreshed = structuredClone(history.messages.assistant);
		expect(latestAssistantForm(refreshed.statusHistory)?.form_id).toBe('human-review:run-race');
		expect(graphMerge?.persist).toBe(false);
		expect(reviewMerge?.persist).toBe(false);
		expect(resolvedMerge?.persist).toBe(true);
	});
	it('requests persistence once, only when the original form is resolved', () => {
		const history: any = {
			messages: { assistant: { id: 'assistant', content: '', statusHistory: [] } }
		};
		const events = [
			{ token: '方案已生成' },
			{
				status: {
					action: 'material_graph',
					run_id: 'run-persist',
					current_node: 'human_review',
					status: 'awaiting_review'
				}
			},
			{
				status: {
					action: 'assistant_form',
					run_id: 'run-persist',
					checkpoint_id: 'cp-review',
					form_id: 'human-review:run-persist'
				}
			},
			{
				status: {
					action: 'assistant_form',
					run_id: 'run-persist',
					checkpoint_id: 'cp-input',
					form_id: 'task-spec:run-persist',
					resolved: true
				}
			}
		];
		const persistCount = events
			.map((event) => mergeMaterialGraphResumeEvent(history, 'assistant', event))
			.filter((result) => result?.persist).length;

		expect(persistCount).toBe(1);
		expect(history.messages.assistant.content).toBe('方案已生成');
		expect(latestAssistantForm(history.messages.assistant.statusHistory)?.form_id).toBe(
			'human-review:run-persist'
		);
	});
	it('reconstructs versioned snapshot and delta events', () => {
		const graph = reduceMaterialGraph([
			{
				action: 'material_graph',
				event_type: 'graph_snapshot',
				run_id: 'r2',
				graph_version: 1,
				nodes: [
					{ id: 'intake', label: 'Intake', status: 'running' },
					{ id: 'gate', label: 'Gate', status: 'pending' }
				],
				edges: [{ source: 'intake', target: 'gate' }],
				logs: []
			},
			{
				action: 'material_graph',
				event_type: 'graph_delta',
				run_id: 'r2',
				base_version: 1,
				graph_version: 2,
				patch: {
					set: { current_node: 'gate', elapsed_ms: 800 },
					node_updates: [
						{ id: 'intake', label: 'Intake', status: 'complete' },
						{ id: 'gate', label: 'Gate', status: 'running' }
					],
					logs: [{ node_id: 'intake', message: 'done' }]
				}
			}
		]);
		expect(graph?.graph_version).toBe(2);
		expect(graph?.current_node).toBe('gate');
		expect(graph?.nodes.map((node) => node.status)).toEqual(['complete', 'running']);
		expect(graph?.logs?.[0].message).toBe('done');
		expect(graph?.resync_required).toBe(false);
	});
	it('marks a version gap for resynchronization', () => {
		const graph = reduceMaterialGraph([
			{
				action: 'material_graph',
				event_type: 'graph_snapshot',
				run_id: 'r3',
				graph_version: 1,
				nodes: [],
				edges: []
			},
			{
				action: 'material_graph',
				event_type: 'graph_delta',
				run_id: 'r3',
				base_version: 2,
				graph_version: 3,
				resync_url: '/runs/r3/graph',
				patch: { set: { current_node: 'gate' } }
			}
		]);
		expect(graph?.graph_version).toBe(1);
		expect(graph?.resync_required).toBe(true);
		expect(graph?.resync_url).toBe('/runs/r3/graph');
	});
	it('compacts status history without losing the latest graph', () => {
		let history: any[] = [];
		for (let version = 1; version <= 300; version++)
			history = appendMaterialGraphStatus(history, {
				action: 'material_graph',
				event_type: 'graph_snapshot',
				run_id: 'r4',
				graph_version: version,
				current_node: 'intake',
				nodes: [
					{ id: 'intake', label: 'Intake', status: version === 300 ? 'complete' : 'running' }
				],
				edges: [],
				logs: []
			});
		expect(history.length).toBeLessThanOrEqual(128);
		expect(reduceMaterialGraph(history)?.graph_version).toBe(300);
	});
	it('changes the layout key only when topology changes', () => {
		const running = {
			run_id: 'r5',
			current_node: 'intake',
			nodes: [{ id: 'intake', label: 'Intake', status: 'running' }],
			edges: []
		};
		const complete = { ...running, nodes: [{ id: 'intake', label: 'Intake', status: 'complete' }] };
		const expanded = {
			...complete,
			nodes: [...complete.nodes, { id: 'gate', label: 'Gate', status: 'pending' }]
		};
		expect(materialGraphTopologyKey(running)).toBe(materialGraphTopologyKey(complete));
		expect(materialGraphTopologyKey(expanded)).not.toBe(materialGraphTopologyKey(complete));
	});
});
