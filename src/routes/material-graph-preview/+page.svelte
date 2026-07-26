<script lang="ts">
	import MaterialGraphView from '$lib/components/chat/MaterialGraph/View.svelte';
	import AssistantForm from '$lib/components/chat/Messages/ResponseMessage/AssistantForm.svelte';
	const snapshot = {
		action: 'material_graph' as const,
		run_id: 'preview-run',
		current_node: 'expert_gate',
		elapsed_ms: 84320,
		evidence_count: 18,
		done: false,
		nodes: [
			{
				id: 'intake',
				label: '任务理解',
				status: 'complete',
				description: '识别材料体系、目标和约束',
				duration_ms: 1280
			},
			{
				id: 'evidence',
				label: '证据检索',
				status: 'complete',
				description: '构建任务证据子图',
				duration_ms: 18640
			},
			{
				id: 'candidate',
				label: '候选生成',
				status: 'complete',
				description: '生成可追溯材料与工艺候选',
				duration_ms: 31420
			},
			{
				id: 'expert_gate',
				label: '专家审核',
				status: 'awaiting_review',
				description: '等待确认候选方案和实验边界'
			},
			{ id: 'report', label: '报告生成', status: 'pending', description: '汇总证据、风险与建议' }
		],
		edges: [
			{ source: 'intake', target: 'evidence' },
			{ source: 'evidence', target: 'candidate' },
			{ source: 'candidate', target: 'expert_gate' },
			{ source: 'expert_gate', target: 'report' }
		],
		logs: [
			{
				node_id: 'evidence',
				message: '已归一化 18 条证据并保留来源定位',
				status: 'complete',
				timestamp: '14:32:08'
			},
			{
				node_id: 'candidate',
				message: '候选与工艺窗口已完成交叉约束检查',
				status: 'complete',
				timestamp: '14:32:45'
			},
			{
				node_id: 'expert_gate',
				message: '等待审核决定，checkpoint 已持久化',
				status: 'awaiting_review',
				timestamp: '14:33:12'
			}
		]
	};
	const form = {
		action: 'assistant_form' as const,
		form_id: 'preview-review',
		run_id: 'preview-run',
		title: '请审核候选方案和实验安排',
		description: '提交后将从当前 LangGraph checkpoint 继续。',
		endpoint: 'http://127.0.0.1:8000',
		fields: [
			{
				name: 'decision',
				label: '审核决定',
				type: 'select',
				required: true,
				options: [
					{ value: 'approve', label: '通过' },
					{ value: 'revise', label: '退回修改' },
					{ value: 'reject', label: '拒绝' }
				]
			},
			{ name: 'reviewer', label: '审核人', type: 'text', default: '研发负责人' },
			{
				name: 'comment',
				label: '审核意见',
				type: 'textarea',
				placeholder: '例如：先做 4 点小试并补充拉伸测试'
			}
		],
		submit: { path: '/runs/preview-run/resume' }
	};
</script>

<svelte:head><title>Material Graph Studio Preview</title></svelte:head>
<div class="min-h-[100dvh] bg-gray-50 text-gray-900 dark:bg-gray-950 dark:text-gray-100">
	<header class="border-b border-gray-200 bg-white px-6 py-3 dark:border-gray-800 dark:bg-gray-900">
		<div class="mx-auto flex max-w-[1500px] items-center justify-between">
			<div class="font-semibold">Material Graph Studio</div>
			<div class="text-xs text-gray-500">Open WebUI v0.10.2 integration preview</div>
		</div>
	</header>
	<main
		class="mx-auto grid h-[calc(100dvh-53px)] max-w-[1500px] grid-cols-[minmax(0,1fr)_430px] gap-0 bg-white shadow-sm dark:bg-gray-900"
	>
		<section class="flex min-w-0 flex-col border-r border-gray-200 dark:border-gray-800">
			<div class="flex-1 overflow-y-auto px-8 py-8">
				<div class="mx-auto max-w-3xl space-y-7">
					<div class="flex justify-end">
						<div class="max-w-[75%] rounded-2xl bg-gray-100 px-4 py-3 text-sm dark:bg-gray-800">
							请为一种耐高温、低介电的薄膜材料制定证据充分的设计和实验路线。
						</div>
					</div>
					<div>
						<div class="mb-2 text-xs font-medium text-gray-500">Material Graph Studio</div>
						<div class="text-sm leading-7">
							已完成证据检索、候选生成与约束检查。右侧执行图显示当前停在专家审核节点，请确认后从同一
							checkpoint 继续。
						</div>
						<AssistantForm {form} />
					</div>
				</div>
			</div>
			<div class="border-t border-gray-100 px-8 py-4 dark:border-gray-800">
				<div
					class="mx-auto max-w-3xl rounded-2xl border border-gray-300 px-4 py-3 text-sm text-gray-400 dark:border-gray-700"
				>
					继续追问材料、工艺、证据或风险…
				</div>
			</div>
		</section>
		<aside class="min-w-0"><MaterialGraphView {snapshot} /></aside>
	</main>
</div>
