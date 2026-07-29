import { describe, expect, it } from 'vitest';

import {
	AGENT_VIEW_ROLES,
	MAX_VISIBLE_KNOWLEDGE_NODES_PER_ROLE,
	latestKnowledgeGraph,
	normalizeKnowledgeGraph
} from '../knowledgeGraph';

describe('Material knowledge graph contract', () => {
	it('normalizes all six explicit agent views and retrieval hits', () => {
		const graph = normalizeKnowledgeGraph({
			type: 'knowledge_signal',
			run_id: 'run-knowledge',
			nodes: [],
			edges: [],
			knowledge_graph: {
				nodes: [
					{ id: 'n-material', label: '聚酰亚胺', agent_view: 'material_design' },
					{ id: 'n-process', label: '热亚胺化', agent_role: 'process' },
					{
						id: 'n-testing',
						label: '介电测试',
						agent: 'performance_prediction'
					},
					{ id: 'n-safety', label: '热失控风险', role: 'safety_quality' },
					{ id: 'n-evaluation', label: '证据质量', agent_view: 'evaluation' },
					{ id: 'n-experiment', label: '正交实验', agent_view: 'experiment_design' }
				],
				edges: [
					{
						id: 'edge-material-process',
						source: 'n-material',
						target: 'n-process',
						relation: 'processed_by'
					},
					{
						id: 'edge-testing-evaluation',
						source: 'n-testing',
						target: 'n-evaluation',
						relation: 'supports'
					}
				],
				retrieval_events: [
					{
						id: 'retrieval-1',
						kind: 'recalled',
						node_ids: ['n-material', 'n-process'],
						edge_ids: ['edge-material-process'],
						agent_view: 'material'
					}
				]
			}
		});

		expect(graph).not.toBeNull();
		expect(new Set(graph?.nodes.map((node) => node.agentView))).toEqual(new Set(AGENT_VIEW_ROLES));
		expect(graph?.nodes.find((node) => node.id === 'n-material')?.hit).toBe(true);
		expect(graph?.nodes.find((node) => node.id === 'n-evaluation')?.hit).toBe(false);
		expect(graph?.edges.find((edge) => edge.id === 'edge-material-process')?.active).toBe(true);
		expect(graph?.edges.find((edge) => edge.id === 'edge-testing-evaluation')?.active).toBe(false);
	});

	it('accepts the real knowledge_signal projection with agent_roles and edge pulses', () => {
		const graph = normalizeKnowledgeGraph({
			type: 'knowledge_signal',
			event_type: 'knowledge_signal',
			run_id: 'run-real-projection',
			phase: 'agent_execution',
			active_agents: ['material'],
			nodes: [
				{
					id: 'material-1',
					label: '6FDA',
					agent_roles: ['material'],
					retrieved: true
				},
				{
					id: 'shared-1',
					label: '任务证据',
					agent_roles: [],
					retrieved: true
				}
			],
			edges: [
				{
					id: 'real-edge',
					source: 'material-1',
					target: 'shared-1',
					relation: 'supported_by',
					agent_roles: ['material'],
					retrieved: true
				}
			],
			pulse: [{ source: 'material-1', target: 'shared-1', agent_role: 'material' }],
			stats: { total_nodes: 2, total_edges: 1 }
		});

		expect(graph?.nodes.find((node) => node.id === 'material-1')?.agentView).toBe('material');
		expect(graph?.nodes.find((node) => node.id === 'shared-1')?.agentView).toBe('shared_retrieval');
		expect(graph?.edges[0]).toMatchObject({ id: 'real-edge', active: true, pulse: true });
	});

	it('unwraps a persisted status envelope without accepting unrelated status events', () => {
		const graph = latestKnowledgeGraph({
			messages: {
				one: {
					statusHistory: [
						{
							event: { type: 'status', data: { action: 'material_graph', event_type: 'progress' } }
						},
						{
							event: {
								type: 'status',
								data: {
									action: 'material_graph',
									event_type: 'knowledge_signal',
									run_id: 'persisted-run',
									nodes: [{ id: 'node', label: '真实节点', agent_roles: ['material'] }],
									edges: []
								}
							}
						}
					]
				}
			}
		});

		expect(graph?.runId).toBe('persisted-run');
		expect(graph?.nodes[0]?.agentView).toBe('material');
	});

	it('does not invent nodes from workflow or task-subgraph counts', () => {
		expect(
			normalizeKnowledgeGraph({
				run_id: 'counts-only',
				nodes: [{ id: 'graph_retrieval', label: '图谱检索', status: 'complete' }],
				edges: [],
				evidence_count: 42,
				task_subgraph: {
					node_count: 120,
					edge_count: 240,
					source_count: 8
				}
			})
		).toBeNull();
	});

	it('keeps unassigned retrieval neutral and drops genuinely dangling edges', () => {
		const graph = normalizeKnowledgeGraph({
			type: 'knowledge_signal',
			run_id: 'strict-roles',
			nodes: [],
			edges: [],
			knowledge_graph: {
				nodes: [
					{ id: 'known', label: 'Known', agent_view: 'material' },
					{ id: 'unassigned', label: 'Unassigned' }
				],
				edges: [
					{ id: 'valid', source: 'known', target: 'unassigned' },
					{ id: 'dangling', source: 'known', target: 'missing' }
				]
			}
		});

		expect(graph?.nodes.map((node) => node.id)).toEqual(['known', 'unassigned']);
		expect(graph?.nodes.find((node) => node.id === 'unassigned')?.agentView).toBe(
			'shared_retrieval'
		);
		expect(graph?.edges.map((edge) => edge.id)).toEqual(['valid']);
		expect(graph?.omittedNodeCount).toBe(0);
		expect(graph?.omittedEdgeCount).toBe(1);
	});

	it('bounds each cluster and reports the received totals', () => {
		const nodes = Array.from({ length: MAX_VISIBLE_KNOWLEDGE_NODES_PER_ROLE + 5 }, (_, index) => ({
			id: `material-${String(index).padStart(3, '0')}`,
			label: `Material ${index}`,
			agent_view: 'material',
			retrieved: index === MAX_VISIBLE_KNOWLEDGE_NODES_PER_ROLE + 4
		}));
		const graph = normalizeKnowledgeGraph({
			type: 'knowledge_signal',
			run_id: 'bounded',
			nodes: [],
			edges: [],
			knowledge_graph: { nodes, edges: [], node_count: 409_416 }
		});

		expect(graph?.nodes).toHaveLength(MAX_VISIBLE_KNOWLEDGE_NODES_PER_ROLE);
		expect(graph?.nodes.some((node) => node.id === nodes.at(-1)?.id)).toBe(true);
		expect(graph?.receivedNodeCount).toBe(409_416);
		expect(graph?.truncated).toBe(true);
	});
});
