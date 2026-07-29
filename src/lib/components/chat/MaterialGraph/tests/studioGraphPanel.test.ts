import { describe, expect, it } from 'vitest';
import { hasStartedMaterialGraphWorkflow } from '../panelState';

describe('Material Graph workflow panel state', () => {
	it('keeps a zero-value placeholder in the honest idle state', () => {
		expect(
			hasStartedMaterialGraphWorkflow({
				run_id: '',
				nodes: [],
				edges: [],
				logs: [],
				elapsed_ms: 0,
				evidence_count: 0,
				done: true,
				success: true,
				outcome: 'completed'
			})
		).toBe(false);
	});

	it('keeps null and topology-free ordinary chat state idle', () => {
		expect(hasStartedMaterialGraphWorkflow(null)).toBe(false);
		expect(
			hasStartedMaterialGraphWorkflow({
				run_id: 'ordinary-chat-placeholder',
				nodes: [],
				edges: [],
				logs: []
			})
		).toBe(false);
	});

	it('shows a workflow only after real topology or checkpoint activity exists', () => {
		expect(
			hasStartedMaterialGraphWorkflow({
				run_id: 'run-topology',
				nodes: [{ id: 'task_structure', label: '任务结构化', status: 'pending' }],
				edges: []
			})
		).toBe(true);
		expect(
			hasStartedMaterialGraphWorkflow({
				run_id: 'run-checkpoint',
				current_node: 'task_structure',
				nodes: [],
				edges: []
			})
		).toBe(true);
		expect(
			hasStartedMaterialGraphWorkflow({
				run_id: 'run-definition',
				nodes: [],
				edges: [],
				workflow_definition: {
					nodes: [{ id: 'task_structure', label: '任务结构化' }],
					edges: []
				}
			})
		).toBe(true);
	});
});
