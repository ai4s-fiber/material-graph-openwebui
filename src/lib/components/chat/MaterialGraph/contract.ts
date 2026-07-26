import type { AssistantFormDefinition, MaterialGraphSnapshot } from './types';

const failures = new Set([
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
export const isFailureOutcome = (value?: string | null) =>
	failures.has(
		String(value ?? '')
			.toLowerCase()
			.replaceAll('-', '_')
	);
export const outcomeLabel = (snapshot?: MaterialGraphSnapshot | null) => {
	const outcome = String(snapshot?.outcome ?? '')
		.toLowerCase()
		.replaceAll('-', '_');
	if (!snapshot?.done) return '实时执行流程';
	if (
		snapshot.success === true ||
		['success', 'succeeded', 'complete', 'completed'].includes(outcome)
	)
		return '执行完成';
	return (
		(
			{
				failed: '执行失败',
				failure: '执行失败',
				error: '执行失败',
				blocked: '执行阻塞',
				budget_stopped: '预算停止',
				budget_exceeded: '预算停止',
				rejected: '执行被拒绝',
				cancelled: '执行取消',
				canceled: '执行取消'
			} as Record<string, string>
		)[outcome] ?? '执行已停止'
	);
};
export const reduceMaterialGraph = (events: any[]): MaterialGraphSnapshot | null => {
	let result: MaterialGraphSnapshot | null = null;
	for (const event of events) {
		if (event?.action !== 'material_graph' || !event.run_id) continue;
		if (!result || result.run_id !== event.run_id)
			result = { run_id: event.run_id, nodes: [], edges: [], logs: [] };
		const workflow = event.workflow;
		const previous = result as MaterialGraphSnapshot;
		const next: MaterialGraphSnapshot = {
			...previous,
			...event,
			workflow: workflow ?? previous.workflow,
			nodes: event.nodes?.length
				? event.nodes
				: workflow?.nodes?.length
					? workflow.nodes
					: previous.nodes,
			edges: event.edges?.length
				? event.edges
				: workflow?.edges?.length
					? workflow.edges
					: previous.edges,
			logs: event.logs ?? previous.logs
		};
		if (next.done && isFailureOutcome(next.outcome)) next.success = false;
		result = next;
	}
	return result;
};
export const latestMaterialGraph = (history: any): MaterialGraphSnapshot | null => {
	const events: any[] = [];
	for (const message of Object.values(history?.messages ?? {}) as any[])
		events.push(...(message?.statusHistory ?? []));
	return reduceMaterialGraph(events);
};
export const latestAssistantForm = (statusHistory: any[] = []): AssistantFormDefinition | null => {
	for (let index = statusHistory.length - 1; index >= 0; index--)
		if (statusHistory[index]?.action === 'assistant_form')
			return statusHistory[index]?.resolved ? null : statusHistory[index];
	return null;
};
