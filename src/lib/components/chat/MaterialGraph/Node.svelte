<script lang="ts">
	import { Handle, Position, type NodeProps } from '@xyflow/svelte';
	type Props = NodeProps; export let data: Props['data'];
	$: status = String(data?.status ?? 'pending').toLowerCase().replaceAll('-', '_');
	$: isActive = Boolean(data?.active);
	$: isError = ['error','failed','failure','blocked','budget_stopped','budget_exceeded','rejected','cancelled','canceled'].includes(status);
	$: isComplete = ['complete','completed','success','succeeded'].includes(status);
	$: duration = data?.duration ?? (data?.duration_ms != null ? `${Math.round(Number(data.duration_ms))} ms` : '');
</script>
<div class:active={isActive} class:error={isError} class:complete={isComplete} data-node-id={data?.id} data-node-status={status} class="graph-node w-[220px] rounded-xl border bg-white px-3 py-2.5 shadow-sm dark:bg-gray-900">
	<Handle type="target" position={Position.Top} class="!size-1.5 !border-0 !bg-gray-400" />
	<div class="flex items-start justify-between gap-2"><div class="min-w-0"><div class="truncate text-sm font-medium text-gray-900 dark:text-gray-100">{data?.label ?? data?.id}</div><div class="mt-1 line-clamp-2 text-[11px] leading-4 text-gray-500 dark:text-gray-400">{data?.description ?? data?.summary ?? status}</div></div><span class="status-dot mt-1 size-2 shrink-0 rounded-full" aria-label={status}></span></div>
	{#if duration}<div class="mt-1.5 text-[10px] tabular-nums text-gray-400">{duration}</div>{/if}
	<Handle type="source" position={Position.Bottom} class="!size-1.5 !border-0 !bg-gray-400" />
</div>
<style>
	.graph-node{border-color:rgb(229 231 235)} :global(.dark) .graph-node{border-color:rgb(55 65 81)}
	.status-dot{background:rgb(156 163 175)} .graph-node.complete .status-dot{background:rgb(16 185 129)}
	.graph-node.error{border-color:rgb(248 113 113);background:rgb(254 242 242)} .graph-node.error .status-dot{background:rgb(239 68 68)}
	.graph-node.active{border-color:rgb(59 130 246);box-shadow:0 0 0 3px rgb(59 130 246 / .12)} .graph-node.active .status-dot{background:rgb(59 130 246);animation:pulse 1.6s ease-in-out infinite}
	@keyframes pulse{50%{opacity:.35;transform:scale(.75)}} @media(prefers-reduced-motion:reduce){.graph-node.active .status-dot{animation:none}}
</style>
