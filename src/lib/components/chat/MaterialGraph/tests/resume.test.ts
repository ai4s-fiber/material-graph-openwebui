import { describe, expect, it, vi } from 'vitest';
import {
	latestAssistantForm,
	latestMaterialGraph,
	mergeMaterialGraphResumeEvent,
	reduceMaterialGraph
} from '../contract';
import { latestKnowledgeGraph } from '../knowledgeGraph';
import { persistMaterialGraphResume } from '../persistence';
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
	it('persists the complete PI review checkpoint and reconstructs it after a reload', async () => {
		const finalSummary = 'PI 高 Tg 任务已完成一轮 Graph 执行，候选方案等待专家审核。';
		const workflowNodes = Array.from({ length: 15 }, (_, index) => ({
			id: index === 14 ? 'human_review' : `workflow-${index}`,
			label: index === 14 ? '专家审核' : `Workflow ${index}`,
			status: index === 14 ? 'awaiting_review' : 'complete'
		}));
		const workflowEdges = Array.from({ length: 24 }, (_, index) => ({
			source: workflowNodes[index % workflowNodes.length].id,
			target: workflowNodes[(index + 1) % workflowNodes.length].id
		}));
		const knowledgeSignal = {
			action: 'material_graph',
			type: 'knowledge_signal',
			event_type: 'knowledge_signal',
			run_id: 'run-1',
			phase: 'agent_execution',
			active_agents: ['material', 'evaluation', 'experiment_design'],
			nodes: [
				{ id: 'kg-pi', label: '聚酰亚胺', agent_roles: ['material'], retrieved: true },
				{
					id: 'kg-high-tg',
					label: '高玻璃化转变温度',
					agent_roles: ['evaluation'],
					retrieved: true
				}
			],
			edges: [
				{
					id: 'kg-targets',
					source: 'kg-pi',
					target: 'kg-high-tg',
					relation: 'targets',
					retrieved: true
				}
			],
			pulse: [{ edge_id: 'kg-targets', source: 'kg-pi', target: 'kg-high-tg' }],
			stats: { total_nodes: 2, total_edges: 1, visible_nodes: 2, visible_edges: 1 }
		};
		const reviewForm = {
			action: 'assistant_form',
			run_id: 'run-1',
			form_id: 'human-review:run-1',
			checkpoint_id: 'cp-review',
			status: 'awaiting_review',
			fields: [{ name: 'decision', type: 'select', options: ['approve', 'reject'] }]
		};
		const frames = [
			{
				type: 'assistant_message',
				content_mode: 'final',
				run_id: 'run-1',
				content: finalSummary
			},
			{
				action: 'material_graph',
				event_type: 'graph_snapshot',
				run_id: 'run-1',
				graph_version: 12,
				status: 'running',
				current_node: 'agent_aggregation',
				nodes: workflowNodes,
				edges: workflowEdges
			},
			knowledgeSignal,
			{ type: 'form', run_id: 'run-1', form: reviewForm },
			{
				action: 'material_graph',
				event_type: 'terminal',
				run_id: 'run-1',
				graph_version: 13,
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
		const intakeForm = {
			...form,
			status: 'awaiting_input',
			current_node: 'task_structure',
			graph_version: 1
		};
		const history: any = {
			messages: {
				assistant: {
					id: 'assistant',
					content: '未指定材料体系，0 条证据。',
					statusHistory: [
						{
							action: 'material_graph',
							event_type: 'graph_snapshot',
							run_id: 'run-1',
							graph_version: 1,
							status: 'awaiting_input',
							current_node: 'task_structure',
							nodes: workflowNodes,
							edges: workflowEdges
						},
						intakeForm
					]
				}
			}
		};
		const epoch = 'pi-review-resume';
		mergeMaterialGraphResumeEvent(history, 'assistant', {
			source: 'direct_resume',
			phase: 'begin',
			run_id: 'run-1',
			epoch,
			status: intakeForm
		});

		const mergeResults: any[] = [];
		const result = await resumeRun(
			intakeForm,
			{ material_family: 'PI', objective: '高 Tg' },
			(event) => {
				mergeResults.push(
					mergeMaterialGraphResumeEvent(history, 'assistant', {
						...event,
						source: 'direct_resume',
						phase: 'event',
						run_id: 'run-1',
						epoch
					})
				);
			},
			fetcher
		);
		expect(result).toEqual(
			expect.objectContaining({
				authoritative: true,
				advanced: true,
				status: 'awaiting_review',
				current_node: 'human_review'
			})
		);
		const terminalMerge = mergeResults.find((merge) => merge?.persist);
		expect(terminalMerge).toBeTruthy();
		expect(
			history.messages.assistant.statusHistory.find(
				(status: any) =>
					status.action === 'assistant_form' &&
					status.form_id === intakeForm.form_id &&
					status.checkpoint_id === intakeForm.checkpoint_id
			)
		).toEqual(expect.objectContaining({ resolved: true }));
		const saveMessage = vi.fn().mockResolvedValue(undefined);
		const settled = vi.fn().mockResolvedValue(undefined);
		// Simulate the original AssistantForm being destroyed immediately after
		// the replacement review form renders: no post-resume callback runs.
		const persisted = terminalMerge?.persist
			? await persistMaterialGraphResume({
					history,
					messageId: 'assistant',
					saveMessage,
					settle: settled
				})
			: null;
		expect(persisted).not.toBeNull();
		expect(settled).toHaveBeenCalledOnce();
		expect(saveMessage).toHaveBeenCalledOnce();
		expect(saveMessage).toHaveBeenCalledWith('assistant', persisted);

		// Simulate the exact payload handed to Open WebUI's persistence sink
		// being serialized by the backend and reconstructed after a full
		// browser refresh.
		const reloaded = {
			messages: {
				assistant: JSON.parse(JSON.stringify(saveMessage.mock.calls[0][1]))
			}
		};
		const restoredMessage = reloaded.messages.assistant;
		const restoredGraph = latestMaterialGraph(reloaded);
		const restoredForm = latestAssistantForm(restoredMessage.statusHistory);
		const restoredKnowledge = latestKnowledgeGraph(reloaded);

		expect(restoredMessage.content).toBe(finalSummary);
		expect(restoredMessage.content).not.toContain('未指定');
		expect(restoredGraph).toEqual(
			expect.objectContaining({
				run_id: 'run-1',
				status: 'awaiting_review',
				current_node: 'human_review'
			})
		);
		expect(restoredGraph?.nodes).toHaveLength(15);
		expect(restoredGraph?.edges).toHaveLength(24);
		expect(restoredForm).toEqual(
			expect.objectContaining({
				run_id: 'run-1',
				form_id: 'human-review:run-1',
				checkpoint_id: 'cp-review',
				status: 'awaiting_review'
			})
		);
		expect(restoredKnowledge).toEqual(
			expect.objectContaining({
				runId: 'run-1',
				activeAgents: ['material', 'evaluation', 'experiment_design'],
				pulse: knowledgeSignal.pulse
			})
		);
		expect(restoredKnowledge?.nodes.map((node) => node.id)).toEqual(['kg-pi', 'kg-high-tg']);
		expect(restoredKnowledge?.nodes.map((node) => node.agentViews)).toEqual([
			['material'],
			['evaluation']
		]);
		expect(restoredKnowledge?.edges.map((edge) => [edge.id, edge.source, edge.target])).toEqual([
			['kg-targets', 'kg-pi', 'kg-high-tg']
		]);
	});
	it('does not resolve or persist the intake form when a resume stream ends mid-run', async () => {
		const runningNodes = Array.from({ length: 15 }, (_, index) => ({
			id: `workflow-${index}`,
			label: `Workflow ${index}`
		}));
		const runningEdges = Array.from({ length: 24 }, (_, index) => ({
			source: runningNodes[index % runningNodes.length].id,
			target: runningNodes[(index + 1) % runningNodes.length].id
		}));
		const fetcher = vi.fn().mockResolvedValue(
			response(
				`data: ${JSON.stringify({
					action: 'material_graph',
					event_type: 'graph_snapshot',
					run_id: 'run-1',
					graph_version: 2,
					status: 'running',
					current_node: 'task_subgraph',
					nodes: runningNodes,
					edges: runningEdges
				})}\n\n`,
				200,
				'text/event-stream'
			)
		);
		const intakeForm = {
			...form,
			status: 'awaiting_input',
			current_node: 'task_structure',
			graph_version: 1
		};
		const history: any = {
			messages: {
				assistant: {
					id: 'assistant',
					content: '未指定材料体系，0 条证据。',
					statusHistory: [intakeForm]
				}
			}
		};
		const epoch = 'interrupted-resume';
		const saveMessage = vi.fn().mockResolvedValue(undefined);
		const persistence: Promise<unknown>[] = [];
		mergeMaterialGraphResumeEvent(history, 'assistant', {
			source: 'direct_resume',
			phase: 'begin',
			run_id: 'run-1',
			epoch
		});
		const mergeResults: any[] = [];

		await expect(
			resumeRun(
				intakeForm,
				{ material_family: 'PI', objective: '高 Tg' },
				(event) => {
					const merged = mergeMaterialGraphResumeEvent(history, 'assistant', {
						...event,
						source: 'direct_resume',
						phase: 'event',
						run_id: 'run-1',
						epoch
					});
					mergeResults.push(merged);
					if (merged?.persist)
						persistence.push(
							persistMaterialGraphResume({
								history,
								messageId: 'assistant',
								saveMessage
							})
						);
				},
				fetcher
			)
		).rejects.toThrow('意外结束');
		await Promise.all(persistence);

		const reloaded = {
			messages: {
				assistant: JSON.parse(JSON.stringify(history.messages.assistant))
			}
		};
		expect(mergeResults.some((merge) => merge?.persist)).toBe(false);
		expect(saveMessage).not.toHaveBeenCalled();
		expect(latestAssistantForm(reloaded.messages.assistant.statusHistory)).toEqual(
			expect.objectContaining({
				run_id: 'run-1',
				form_id: 'f',
				checkpoint_id: 'cp-1',
				status: 'awaiting_input'
			})
		);
		expect(reloaded.messages.assistant.content).toBe('未指定材料体系，0 条证据。');
	});
});
