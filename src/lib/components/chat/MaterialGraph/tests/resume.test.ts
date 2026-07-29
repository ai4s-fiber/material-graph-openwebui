import { describe, expect, it, vi } from 'vitest';
import { mergeMaterialGraphResumeEvent, reduceMaterialGraph } from '../contract';
import { latestKnowledgeGraph } from '../knowledgeGraph';
import { resumeKey, resumeRun } from '../resume';
const form: any = {
	action: 'assistant_form',
	form_id: 'f',
	run_id: 'run-1',
	checkpoint_id: 'cp-1',
	endpoint: 'https://api.test',
	submit: { path: '/runs/run-1/resume' }
};
const response = (body: string, status = 200, type = 'application/json') =>
	new Response(body, { status, headers: { 'content-type': type } });
describe('resume adapter', () => {
	it('prefers resume stream and preserves the authoritative run', async () => {
		const fetcher = vi
			.fn()
			.mockResolvedValue(
				response(
					[
						'data: {"event":{"type":"status","data":{"action":"material_graph","run_id":"run-1","current_node":"next","nodes":[],"edges":[]}}}',
						'data: {"action":"material_graph","event_type":"terminal","run_id":"run-1","status":"awaiting_review","current_node":"next","done":true,"nodes":[],"edges":[]}'
					].join('\n\n') + '\n\n',
					200,
					'text/event-stream'
				)
			);
		const events: any[] = [];
		const result = await resumeRun(form, { x: 1 }, (e) => events.push(e), fetcher);
		expect(result).toEqual(
			expect.objectContaining({ streamed: true, authoritative: true, advanced: true })
		);
		expect(JSON.parse(fetcher.mock.calls[0][1].body)).toEqual(
			expect.objectContaining({
				run_id: 'run-1',
				form_id: 'f',
				checkpoint_id: 'cp-1',
				values: { x: 1 }
			})
		);
		expect(fetcher.mock.calls[0][0]).toBe('https://api.test/runs/run-1/resume/stream');
		expect(events[0].status.current_node).toBe('next');
		expect((fetcher.mock.calls[0][1].headers as any)['Idempotency-Key']).toBe(resumeKey(form));
	});
	it('falls back only when the stream route is unavailable', async () => {
		const fetcher = vi
			.fn()
			.mockResolvedValueOnce(response('{}', 404))
			.mockResolvedValueOnce(response('{"run_id":"run-1"}'));
		const result = await resumeRun(form, {}, () => {}, fetcher);
		expect(result).toEqual(
			expect.objectContaining({ streamed: false, authoritative: false, advanced: false })
		);
		expect(fetcher).toHaveBeenCalledTimes(2);
	});
	it('rejects a fake run returned by legacy resume', async () => {
		const fetcher = vi
			.fn()
			.mockResolvedValueOnce(response('{}', 405))
			.mockResolvedValueOnce(response('{"run_id":"fake"}'));
		await expect(resumeRun(form, {}, () => {}, fetcher)).rejects.toThrow('run_id');
	});
	it('keeps the same form when authoritative validation remains awaiting input', async () => {
		const fetcher = vi
			.fn()
			.mockResolvedValue(
				response(
					[
						'data: {"action":"assistant_form","run_id":"run-1","form_id":"f","checkpoint_id":"cp-1","status":"awaiting_input","validation_error":"Need a value"}',
						'event: done\ndata: {"run_id":"run-1","status":"awaiting_input"}'
					].join('\n\n') + '\n\n',
					200,
					'text/event-stream'
				)
			);
		const events: any[] = [];
		const result = await resumeRun(form, {}, (event) => events.push(event), fetcher);
		expect(result).toEqual(
			expect.objectContaining({ authoritative: true, advanced: false, message: 'Need a value' })
		);
		expect(events[0].status).toEqual(expect.objectContaining({ form_id: 'f', run_id: 'run-1' }));
	});
	it('does not treat a same-checkpoint graph version replay as form progress', async () => {
		const fetcher = vi
			.fn()
			.mockResolvedValue(
				response(
					[
						'data: {"action":"material_graph","event_type":"graph_delta","run_id":"run-1","status":"awaiting_input","graph_version":3,"patch":{"set":{"elapsed_ms":1200}}}',
						'event: done\ndata: {"run_id":"run-1","status":"awaiting_input"}'
					].join('\n\n') + '\n\n',
					200,
					'text/event-stream'
				)
			);
		const result = await resumeRun(
			{ ...form, graph_version: 2, current_node: 'task_structure' },
			{},
			() => {},
			fetcher
		);
		expect(result).toEqual(
			expect.objectContaining({ authoritative: true, advanced: false, awaitingInput: true })
		);
	});
	it('rejects stream errors and embedded run mismatches instead of resolving the form', async () => {
		const streamError = vi
			.fn()
			.mockResolvedValue(
				response(
					'data: {"action":"material_graph","event_type":"terminal","run_id":"run-1","status":"error","outcome":"error","error":"backend failed"}\n\n',
					200,
					'text/event-stream'
				)
			);
		await expect(resumeRun(form, {}, () => {}, streamError)).rejects.toThrow('backend failed');

		const mismatchedForm = vi
			.fn()
			.mockResolvedValue(
				response(
					'data: {"type":"form","run_id":"run-1","form":{"action":"assistant_form","run_id":"another-run","form_id":"next","checkpoint_id":"cp-2","status":"awaiting_input"}}\n\n',
					200,
					'text/event-stream'
				)
			);
		await expect(resumeRun(form, {}, () => {}, mismatchedForm)).rejects.toThrow('run_id');
	});
	it('recognizes a new authoritative input checkpoint as progress', async () => {
		const fetcher = vi
			.fn()
			.mockResolvedValue(
				response(
					'data: {"type":"form","run_id":"run-1","form":{"action":"assistant_form","run_id":"run-1","form_id":"next","checkpoint_id":"cp-2","status":"awaiting_input"}}\n\n',
					200,
					'text/event-stream'
				)
			);
		const events: any[] = [];
		const result = await resumeRun(form, {}, (event) => events.push(event), fetcher);
		expect(result).toEqual(
			expect.objectContaining({
				authoritative: true,
				advanced: true,
				awaitingInput: true,
				form_id: 'next',
				checkpoint_id: 'cp-2'
			})
		);
		expect(events[0].status).toEqual(
			expect.objectContaining({ run_id: 'run-1', form_id: 'next', checkpoint_id: 'cp-2' })
		);
	});
	it('rejects a clean EOF after graph progress when no terminal boundary was received', async () => {
		const fetcher = vi
			.fn()
			.mockResolvedValue(
				response(
					'data: {"action":"material_graph","event_type":"graph_delta","run_id":"run-1","status":"running","current_node":"task_subgraph","nodes":[],"edges":[]}\n\n',
					200,
					'text/event-stream'
				)
			);
		const events: any[] = [];

		await expect(resumeRun(form, {}, (event) => events.push(event), fetcher)).rejects.toThrow(
			'意外结束'
		);
		expect(events).toHaveLength(1);
		expect(events[0].status.current_node).toBe('task_subgraph');
	});
	it('cancels and releases a malformed resume stream instead of resolving the form', async () => {
		const cancel = vi.fn();
		const stream = new ReadableStream<Uint8Array>({
			start(controller) {
				controller.enqueue(new TextEncoder().encode('data: {malformed}\n\n'));
			},
			cancel
		});
		const fetcher = vi.fn().mockResolvedValue(
			new Response(stream, {
				status: 200,
				headers: { 'content-type': 'text/event-stream' }
			})
		);

		await expect(resumeRun(form, {}, () => {}, fetcher)).rejects.toThrow('无法解析');
		expect(cancel).toHaveBeenCalledOnce();
	});
	it('keeps real knowledge signals separate from the execution workflow during resume', async () => {
		const workflowNodes = Array.from({ length: 15 }, (_, index) => ({
			id: `workflow-${index}`,
			label: `Workflow ${index}`
		}));
		const workflowEdges = Array.from({ length: 24 }, (_, index) => ({
			source: `workflow-${index % workflowNodes.length}`,
			target: `workflow-${(index + 1) % workflowNodes.length}`
		}));
		const knowledgeSignal = {
			action: 'material_graph',
			type: 'knowledge_signal',
			event_type: 'knowledge_signal',
			run_id: 'run-1',
			phase: 'agent_execution',
			active_agents: ['material'],
			nodes: [
				{ id: 'kg-pi', label: 'PI', agent_roles: ['material'], retrieved: true },
				{ id: 'kg-tg', label: '高 Tg', agent_roles: ['evaluation'], retrieved: true }
			],
			edges: [
				{
					id: 'kg-edge',
					source: 'kg-pi',
					target: 'kg-tg',
					relation: 'targets',
					retrieved: true
				}
			],
			pulse: [{ edge_id: 'kg-edge', source: 'kg-pi', target: 'kg-tg' }],
			stats: { total_nodes: 2, total_edges: 1 }
		};
		const frames = [
			{
				action: 'material_graph',
				event_type: 'graph_snapshot',
				run_id: 'run-1',
				status: 'running',
				current_node: 'graph_retrieval',
				nodes: workflowNodes,
				edges: workflowEdges
			},
			knowledgeSignal,
			{
				action: 'material_graph',
				event_type: 'terminal',
				run_id: 'run-1',
				status: 'awaiting_review',
				current_node: 'human_review',
				done: true
			}
		];
		const fetcher = vi
			.fn()
			.mockResolvedValue(
				response(
					frames.map((frame) => `data: ${JSON.stringify(frame)}`).join('\n\n') + '\n\n',
					200,
					'text/event-stream'
				)
			);
		const events: any[] = [];

		await resumeRun(form, {}, (event) => events.push(event), fetcher);

		const statuses = events.flatMap((event) => (event.status ? [event.status] : []));
		const workflow = reduceMaterialGraph(statuses);
		const knowledge = latestKnowledgeGraph({
			messages: { assistant: { statusHistory: statuses } }
		});
		const directKnowledge = statuses.find((status) => status.event_type === 'knowledge_signal');
		expect(directKnowledge).toEqual(
			expect.objectContaining({
				action: 'material_graph_knowledge',
				run_id: 'run-1',
				nodes: knowledgeSignal.nodes,
				edges: knowledgeSignal.edges,
				pulse: knowledgeSignal.pulse
			})
		);
		expect(workflow?.nodes).toHaveLength(15);
		expect(workflow?.edges).toHaveLength(24);
		expect(knowledge?.nodes.map((node) => node.id)).toEqual(['kg-pi', 'kg-tg']);
		expect(knowledge?.edges).toHaveLength(1);
		expect(knowledge?.pulse).toHaveLength(1);
	});
	it('replaces the stale intake summary with one authoritative final assistant message', async () => {
		const finalSummary = '已完成 PI 高 Tg 任务：生成 3 个候选方案，进入专家审核。';
		const fetcher = vi.fn().mockResolvedValue(
			response(
				[
					`data: ${JSON.stringify({
						type: 'assistant_message',
						content_mode: 'final',
						run_id: 'run-1',
						content: finalSummary
					})}`,
					'data: {"action":"material_graph","event_type":"terminal","run_id":"run-1","status":"awaiting_review","current_node":"human_review","done":true}'
				].join('\n\n') + '\n\n',
				200,
				'text/event-stream'
			)
		);
		const events: any[] = [];
		await resumeRun(form, {}, (event) => events.push(event), fetcher);
		const history: any = {
			messages: {
				assistant: {
					id: 'assistant',
					content: '未指定材料体系，0 条证据。',
					statusHistory: []
				}
			}
		};
		const epoch = 'final-message-epoch';
		mergeMaterialGraphResumeEvent(history, 'assistant', {
			source: 'direct_resume',
			phase: 'begin',
			run_id: 'run-1',
			epoch
		});
		for (const event of events)
			mergeMaterialGraphResumeEvent(history, 'assistant', {
				...event,
				source: 'direct_resume',
				phase: 'event',
				run_id: 'run-1',
				epoch
			});

		expect(events.find((event) => event.token)).toEqual(
			expect.objectContaining({ token: finalSummary, replaceContent: true })
		);
		expect(history.messages.assistant.content).toBe(finalSummary);
		expect(history.messages.assistant.content).not.toContain('未指定');
	});
	it('suppresses a duplicate final assistant message after incremental deltas', async () => {
		const summary = 'PI 高 Tg 候选已生成。';
		const fetcher = vi.fn().mockResolvedValue(
			response(
				[
					`data: ${JSON.stringify({
						type: 'assistant_delta',
						run_id: 'run-1',
						delta: summary
					})}`,
					`data: ${JSON.stringify({
						type: 'assistant_message',
						content_mode: 'final',
						run_id: 'run-1',
						content: summary
					})}`,
					'data: {"action":"material_graph","event_type":"terminal","run_id":"run-1","status":"awaiting_review","current_node":"human_review","done":true}'
				].join('\n\n') + '\n\n',
				200,
				'text/event-stream'
			)
		);
		const events: any[] = [];

		await resumeRun(form, {}, (event) => events.push(event), fetcher);

		expect(events.map((event) => event.token).filter(Boolean)).toEqual([summary]);
		expect(events.some((event) => event.replaceContent)).toBe(false);
	});
});
