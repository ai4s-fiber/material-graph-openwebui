import type {
	AssistantFormDefinition,
	MaterialGraphKnowledgeSignal,
	MaterialGraphSnapshot,
	ResumeEvent,
	ResumeResult
} from './types';

type JsonRecord = Record<string, any>;
type ResumeTracker = ResumeResult & {
	baselineCurrentNode: string | null;
	baselineGraphVersion?: number;
	baselineCheckpointId: string | null;
	originalFormKey: string;
	sawGraph: boolean;
	sawTerminalBoundary: boolean;
	sawAssistantDelta: boolean;
	activeFormKey?: string;
};

const unavailable = new Set([404, 405, 501]);
const failureOutcomes = new Set([
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
const graphEvents = new Set(['graph', 'graph_snapshot', 'graph_delta', 'terminal']);
const isRecord = (value: unknown): value is JsonRecord =>
	Boolean(value) && typeof value === 'object' && !Array.isArray(value);
const normalized = (value: unknown) =>
	typeof value === 'string' ? value.trim().toLowerCase().replaceAll('-', '_') : '';
const textValue = (...values: unknown[]) =>
	values.find((value): value is string => typeof value === 'string' && value.trim().length > 0);
const integerValue = (...values: unknown[]) =>
	values.find((value): value is number => Number.isInteger(value) && typeof value === 'number');
const formKey = (runId: string, checkpointId: unknown, formId: unknown) =>
	[runId, checkpointId ?? 'checkpoint', formId ?? 'form'].join(':');

/** One resume attempt per authoritative input checkpoint. */
export const resumeKey = (form: AssistantFormDefinition) =>
	formKey(form.run_id, form.checkpoint_id, form.form_id);

const absolute = (base: string, path: string) =>
	/^https?:\/\//.test(path)
		? path
		: `${base.replace(/\/$/, '')}${path.startsWith('/') ? path : `/${path}`}`;

const trackerFor = (form: AssistantFormDefinition, streamed: boolean): ResumeTracker => ({
	streamed,
	authoritative: false,
	advanced: false,
	awaitingInput: true,
	terminal: false,
	status: normalized(form.status) || 'awaiting_input',
	outcome: normalized(form.outcome) || undefined,
	current_node: form.current_node ?? (String((form as JsonRecord).node_id ?? '') || null),
	graph_version: form.graph_version,
	checkpoint_id: form.checkpoint_id ?? null,
	form_id: form.form_id,
	baselineCurrentNode: form.current_node ?? (String((form as JsonRecord).node_id ?? '') || null),
	baselineGraphVersion: form.graph_version,
	baselineCheckpointId: form.checkpoint_id ?? null,
	originalFormKey: formKey(form.run_id, form.checkpoint_id, form.form_id),
	sawGraph: false,
	sawTerminalBoundary: false,
	sawAssistantDelta: false
});

const unwrap = (raw: JsonRecord) => {
	const envelope = isRecord(raw.event) ? raw.event : undefined;
	if (
		['status', 'knowledge_signal'].includes(normalized(envelope?.type)) &&
		isRecord(envelope?.data)
	)
		return envelope.data;
	if (['status', 'knowledge_signal'].includes(normalized(raw.type)) && isRecord(raw.data))
		return raw.data;
	return raw;
};

const eventType = (raw: JsonRecord, payload: JsonRecord) =>
	normalized(raw.event_type ?? payload.event_type ?? payload.type ?? raw.type ?? raw.event?.type);

const eventRunId = (raw: JsonRecord, payload: JsonRecord) =>
	textValue(
		payload.run_id,
		payload.runId,
		raw.run_id,
		raw.runId,
		isRecord(raw.form) ? raw.form.run_id : undefined,
		isRecord(raw.form) ? raw.form.runId : undefined,
		isRecord(payload.form) ? payload.form.run_id : undefined,
		isRecord(payload.form) ? payload.form.runId : undefined,
		isRecord(raw.state) ? raw.state.run_id : undefined,
		isRecord(payload.state) ? payload.state.run_id : undefined
	);

const formFrom = (raw: JsonRecord, payload: JsonRecord, type: string) => {
	if (payload.action === 'assistant_form') return payload;
	if (isRecord(raw.form)) return raw.form;
	if (isRecord(payload.form)) return payload.form;
	return ['assistant_form', 'assistantform', 'form'].includes(type) ? payload : undefined;
};

const graphFrom = (raw: JsonRecord, payload: JsonRecord, type: string) => {
	if (type === 'knowledge_signal') return undefined;
	if (payload.action === 'material_graph') return payload;
	if (raw.action === 'material_graph') return raw;
	return graphEvents.has(type) || type === 'done' || type === 'error' ? payload : undefined;
};

const knowledgeFrom = (
	payload: JsonRecord,
	type: string,
	runId: string | undefined
): MaterialGraphKnowledgeSignal | undefined => {
	if (type !== 'knowledge_signal' || !runId) return undefined;
	return {
		...payload,
		action: 'material_graph_knowledge',
		type: 'knowledge_signal',
		event_type: 'knowledge_signal',
		run_id: runId
	};
};

const validationMessage = (form: JsonRecord, raw: JsonRecord) => {
	const context = isRecord(form.context) ? form.context : {};
	const message = textValue(
		form.validation_error,
		form.validationError,
		context.validation_error,
		context.validationError,
		context.error,
		form.error,
		raw.validation_error
	);
	return message?.trim();
};

const observe = (
	tracker: ResumeTracker,
	raw: JsonRecord,
	payload: JsonRecord,
	form: JsonRecord | undefined,
	graph: JsonRecord | undefined,
	type: string,
	authoritative: boolean
) => {
	const state = isRecord(raw.state)
		? raw.state
		: isRecord(payload.state)
			? payload.state
			: undefined;
	const patch = isRecord(graph?.patch) ? graph.patch : undefined;
	const set = isRecord(patch?.set) ? patch.set : undefined;
	const status = normalized(
		textValue(state?.status, set?.status, form?.status, graph?.status, payload.status, raw.status)
	);
	const outcome = normalized(
		textValue(state?.status, graph?.outcome, payload.outcome, raw.outcome, status)
	);
	const currentNode = textValue(
		state?.current_node,
		set?.current_node,
		graph?.current_node,
		payload.current_node,
		raw.current_node
	);
	const graphVersion = integerValue(graph?.graph_version, payload.graph_version, raw.graph_version);
	const checkpointId = textValue(
		form?.checkpoint_id,
		state?.checkpoint_id,
		set?.checkpoint_id,
		graph?.checkpoint_id,
		payload.checkpoint_id,
		raw.checkpoint_id
	);

	if (form && authoritative) {
		tracker.authoritative = true;
		tracker.status = status || 'awaiting_input';
		tracker.outcome = outcome || undefined;
		tracker.awaitingInput = (status || outcome || 'awaiting_input') === 'awaiting_input';
		tracker.form_id = textValue(form.form_id, form.formId, form.id) ?? null;
		tracker.checkpoint_id = checkpointId ?? tracker.checkpoint_id;
		tracker.activeFormKey = formKey(
			textValue(form.run_id, form.runId) ?? eventRunId(raw, payload) ?? '',
			tracker.checkpoint_id,
			tracker.form_id
		);
		tracker.message = validationMessage(form, raw) ?? tracker.message;
	}

	if (graph && authoritative) {
		tracker.authoritative = true;
		tracker.sawGraph = tracker.sawGraph || graphEvents.has(type) || type === 'done';
		tracker.sawTerminalBoundary =
			tracker.sawTerminalBoundary || type === 'terminal' || type === 'done';
		if (status) tracker.status = status;
		if (outcome) tracker.outcome = outcome;
		if (status || outcome) tracker.awaitingInput = (status || outcome) === 'awaiting_input';
		if (currentNode !== undefined) tracker.current_node = currentNode;
		if (graphVersion !== undefined) tracker.graph_version = graphVersion;
		if (checkpointId !== undefined) tracker.checkpoint_id = checkpointId;
		tracker.terminal =
			tracker.terminal ||
			type === 'terminal' ||
			type === 'done' ||
			type === 'error' ||
			Boolean(graph.done);
	}

	const error = textValue(raw.error, payload.error, graph?.error, state?.error);
	const failure =
		failureOutcomes.has(outcome) ||
		failureOutcomes.has(status) ||
		type === 'error' ||
		(type === 'terminal' &&
			(graph?.success === false || payload.success === false || raw.success === false));
	if (error || failure) {
		throw new Error(error?.trim() || `恢复流程失败：${outcome || status || 'error'}`);
	}
};

const statusEvent = (
	raw: JsonRecord,
	payload: JsonRecord,
	form: JsonRecord | undefined,
	graph: JsonRecord | undefined,
	runId: string
): ResumeEvent['status'] => {
	if (form) {
		return {
			...form,
			action: 'assistant_form',
			run_id: textValue(form.run_id, form.runId, runId) ?? runId,
			form_id: textValue(form.form_id, form.formId, form.id) ?? 'input'
		} as AssistantFormDefinition;
	}
	if (graph) {
		return {
			...graph,
			action: 'material_graph',
			run_id: eventRunId(raw, payload) ?? runId,
			nodes: Array.isArray(graph.nodes) ? graph.nodes : [],
			edges: Array.isArray(graph.edges) ? graph.edges : []
		} as MaterialGraphSnapshot;
	}
	return undefined;
};

const finish = (tracker: ResumeTracker, requireStreamBoundary = false): ResumeResult => {
	const changedNode =
		tracker.current_node !== undefined && tracker.current_node !== tracker.baselineCurrentNode;
	const changedVersion =
		tracker.graph_version !== undefined &&
		(tracker.baselineGraphVersion === undefined
			? tracker.sawGraph
			: tracker.graph_version > tracker.baselineGraphVersion);
	const changedForm =
		tracker.activeFormKey !== undefined && tracker.activeFormKey !== tracker.originalFormKey;
	if (requireStreamBoundary && !tracker.sawTerminalBoundary && !changedForm) {
		throw new Error('恢复流在到达下一检查点前意外结束，原表单已保留，请重试。');
	}
	const changedCheckpoint =
		tracker.checkpoint_id !== undefined && tracker.checkpoint_id !== tracker.baselineCheckpointId;
	const completedOrReview = ['complete', 'completed', 'awaiting_review'].includes(
		tracker.status || tracker.outcome || ''
	);
	const leftInput =
		tracker.authoritative && Boolean(tracker.status) && tracker.status !== 'awaiting_input';
	tracker.advanced = Boolean(
		tracker.authoritative &&
		// A graph-version bump alone can be a heartbeat/log update while the
		// very same input checkpoint is still pending. It must never hide the
		// form. A version is only supporting evidence after the authoritative
		// status has left awaiting_input; the state transition itself is what
		// resolves the original form.
		(changedNode ||
			changedCheckpoint ||
			changedForm ||
			completedOrReview ||
			leftInput ||
			(changedVersion && !tracker.awaitingInput))
	);

	// A repeated form for the same checkpoint is authoritative, but it is not
	// progress. Keep the original form visible so the user can correct it.
	if (
		!tracker.advanced &&
		tracker.awaitingInput &&
		tracker.activeFormKey === tracker.originalFormKey
	) {
		tracker.message ??= '提交已接收，但运行仍在等待这组信息，请检查填写内容后重试。';
	}
	if (!tracker.authoritative)
		tracker.message ??= '恢复请求没有返回权威运行状态，表单已保留，请重试。';

	const {
		baselineCurrentNode: _baselineCurrentNode,
		baselineGraphVersion: _baselineGraphVersion,
		baselineCheckpointId: _baselineCheckpointId,
		originalFormKey: _originalFormKey,
		sawGraph: _sawGraph,
		sawTerminalBoundary: _sawTerminalBoundary,
		sawAssistantDelta: _sawAssistantDelta,
		activeFormKey: _activeFormKey,
		...result
	} = tracker;
	return result;
};

const consumeFrame = (
	data: string,
	runId: string,
	tracker: ResumeTracker,
	emit: (event: ResumeEvent) => void,
	sseType?: string
) => {
	if (data === '[DONE]' || (!data && normalized(sseType) === 'done')) {
		tracker.sawTerminalBoundary = true;
		tracker.terminal = true;
		return;
	}
	if (!data) return;
	let raw: JsonRecord;
	try {
		const parsed = JSON.parse(data);
		if (!isRecord(parsed)) throw new Error('invalid event');
		raw = parsed;
	} catch {
		throw new Error('恢复流返回了无法解析的 SSE 事件');
	}
	if (sseType && !raw.event_type && !raw.type) raw.event_type = sseType;
	const payload = unwrap(raw);
	const type = eventType(raw, payload);
	const eventRun = eventRunId(raw, payload);
	if (eventRun && eventRun !== runId) throw new Error('恢复流返回了不匹配的 run_id');
	const form = formFrom(raw, payload, type);
	const graph = graphFrom(raw, payload, type);
	const knowledge = knowledgeFrom(payload, type, eventRun);
	const embeddedFormRun = form ? textValue(form.run_id, form.runId) : undefined;
	const embeddedGraphRun = graph ? textValue(graph.run_id, graph.runId) : undefined;
	if (embeddedFormRun && embeddedFormRun !== runId) throw new Error('恢复流表单的 run_id 不匹配');
	if (embeddedGraphRun && embeddedGraphRun !== runId)
		throw new Error('恢复流图状态的 run_id 不匹配');
	const authoritative = eventRun === runId;
	if (form && authoritative) {
		const incomingFormId = textValue(form.form_id, form.formId, form.id);
		const incomingCheckpointId = textValue(form.checkpoint_id, form.checkpointId);
		if (!incomingFormId || !incomingCheckpointId)
			throw new Error('恢复流表单缺少 form_id 或 checkpoint_id');
	}
	const incrementalToken = textValue(
		raw.delta,
		raw.token,
		payload.delta,
		payload.token,
		['token', 'assistant_token', 'text_delta', 'assistant_delta'].includes(type)
			? payload.text
			: undefined
	);
	const isAssistantDelta = ['token', 'assistant_token', 'text_delta', 'assistant_delta'].includes(
		type
	);
	if (isAssistantDelta && incrementalToken) tracker.sawAssistantDelta = true;
	const finalContent =
		type === 'assistant_message'
			? textValue(payload.content, raw.content, payload.text, raw.text)
			: undefined;
	const replaceContent = Boolean(finalContent && !tracker.sawAssistantDelta);
	const token = incrementalToken ?? (replaceContent ? finalContent : undefined);
	observe(tracker, raw, payload, form, graph, type, authoritative);
	const status = authoritative
		? (knowledge ?? statusEvent(raw, payload, form, graph, runId))
		: undefined;
	if (token || status) emit({ token, replaceContent, status, raw });
};

export const parseSse = async (
	response: Response,
	form: AssistantFormDefinition,
	emit: (event: ResumeEvent) => void
): Promise<ResumeResult> => {
	const tracker = trackerFor(form, true);
	if (!response.body) throw new Error('恢复流在到达下一检查点前意外结束，原表单已保留，请重试。');
	const reader = response.body.getReader();
	const decoder = new TextDecoder();
	let buffer = '';
	let completedRead = false;
	try {
		while (true) {
			const { done, value } = await reader.read();
			buffer += decoder.decode(value ?? new Uint8Array(), { stream: !done });
			const chunks = buffer.split(/\r?\n\r?\n/);
			buffer = chunks.pop() ?? '';
			for (const chunk of chunks) {
				const data = chunk
					.split(/\r?\n/)
					.filter((line) => line.startsWith('data:'))
					.map((line) => line.slice(5).trim())
					.join('\n');
				const sseType = chunk
					.split(/\r?\n/)
					.find((line) => line.startsWith('event:'))
					?.slice(6)
					.trim();
				consumeFrame(data, form.run_id, tracker, emit, sseType);
			}
			if (done) break;
		}
		if (buffer.trim()) {
			const data = buffer
				.split(/\r?\n/)
				.filter((line) => line.startsWith('data:'))
				.map((line) => line.slice(5).trim())
				.join('\n');
			const sseType = buffer
				.split(/\r?\n/)
				.find((line) => line.startsWith('event:'))
				?.slice(6)
				.trim();
			consumeFrame(data, form.run_id, tracker, emit, sseType);
		}
		completedRead = true;
	} finally {
		if (!completedRead) await reader.cancel().catch(() => undefined);
		reader.releaseLock();
	}
	return finish(tracker, true);
};

export const resumeRun = async (
	form: AssistantFormDefinition,
	values: Record<string, unknown>,
	emit: (event: ResumeEvent) => void,
	fetcher: typeof fetch = fetch
): Promise<ResumeResult> => {
	if (!form.run_id || !form.form_id || !form.checkpoint_id)
		throw new Error('当前表单缺少 run_id、checkpoint_id 或 form_id，无法安全恢复');
	const base = form.endpoint ?? '';
	const legacy = form.submit?.url ?? form.submit?.path ?? `/runs/${form.run_id}/resume`;
	if (!base && !/^https?:\/\//.test(legacy)) throw new Error('未配置 Material Graph API 地址');
	const stream =
		form.submit?.stream_path ??
		(legacy.endsWith('/resume') ? `${legacy}/stream` : `/runs/${form.run_id}/resume/stream`);
	const body = JSON.stringify({
		...(form.submission ?? {}),
		values,
		run_id: form.run_id,
		form_id: form.form_id,
		checkpoint_id: form.checkpoint_id ?? null
	});
	const headers = {
		'Content-Type': 'application/json',
		Accept: 'text/event-stream',
		'Idempotency-Key': resumeKey(form)
	};
	const response = await fetcher(absolute(base, stream), {
		method: form.submit?.method ?? 'POST',
		headers,
		body
	});
	if (response.ok) return parseSse(response, form, emit);
	if (!unavailable.has(response.status))
		throw new Error((await response.json().catch(() => null))?.detail ?? `HTTP ${response.status}`);

	const fallback = await fetcher(absolute(base, legacy), {
		method: form.submit?.method ?? 'POST',
		headers: { ...headers, Accept: 'application/json' },
		body
	});
	if (!fallback.ok)
		throw new Error((await fallback.json().catch(() => null))?.detail ?? `HTTP ${fallback.status}`);
	const result = await fallback.json().catch(() => null);
	const resultRun =
		result?.run_id ?? result?.runId ?? result?.state?.run_id ?? result?.state?.runId;
	if (resultRun && resultRun !== form.run_id) throw new Error('恢复响应返回了不匹配的 run_id');
	const tracker = trackerFor(form, false);
	if (isRecord(result?.state) && resultRun === form.run_id) {
		const state = {
			...result.state,
			action: 'material_graph',
			event_type: 'graph_snapshot',
			run_id: form.run_id,
			status: result.status ?? result.state.status
		};
		emit({ status: state as MaterialGraphSnapshot, raw: result });
		observe(tracker, state, state, undefined, state, 'graph_snapshot', true);
	}
	return finish(tracker);
};
