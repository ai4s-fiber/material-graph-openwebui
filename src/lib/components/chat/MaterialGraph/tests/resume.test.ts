import { describe, expect, it, vi } from 'vitest';
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
					'data: {"event":{"type":"status","data":{"action":"material_graph","run_id":"run-1","current_node":"next","nodes":[],"edges":[]}}}\n\n',
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
					'data: {"action":"assistant_form","run_id":"run-1","form_id":"f","checkpoint_id":"cp-1","status":"awaiting_input","validation_error":"Need a value"}\n\n',
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
					'data: {"action":"material_graph","event_type":"graph_delta","run_id":"run-1","status":"awaiting_input","graph_version":3,"patch":{"set":{"elapsed_ms":1200}}}\n\n',
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
});
