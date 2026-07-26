<script lang="ts">
	import { writable } from 'svelte/store';
	import { Background, BackgroundVariant, Controls, SvelteFlow, SvelteFlowProvider } from '@xyflow/svelte';
	import '@xyflow/svelte/dist/style.css';
	import type { MaterialGraphSnapshot } from './types';
	import { outcomeLabel } from './contract';
	import { layoutWorkflow } from './layout';
	import MaterialGraphNode from './Node.svelte';
	export let snapshot: MaterialGraphSnapshot;
	let selectedNodeId: string | null = null;
	const nodes=writable<any[]>([]), edges=writable<any[]>([]);
	$: displayNodes=(snapshot?.nodes ?? []).map((node)=>({...node,active:node.id === snapshot?.current_node}));
	$: layout=layoutWorkflow(displayNodes,snapshot?.edges ?? []);
	$: nodes.set(layout.nodes); $: edges.set(layout.edges);
	$: selectedNode=(snapshot?.nodes ?? []).find((node)=>node.id===selectedNodeId) ?? (snapshot?.nodes ?? []).find((node)=>node.id===snapshot?.current_node) ?? null;
	const nodeTypes:any={materialGraph:MaterialGraphNode};
</script>
<SvelteFlowProvider><div class="flex h-full min-h-0 flex-col bg-white dark:bg-gray-850" data-terminal-outcome={snapshot?.outcome ?? ''}>
<header class="shrink-0 border-b border-gray-100 px-4 py-3 dark:border-gray-800"><div class="flex items-center justify-between gap-3"><div><h2 class="text-sm font-semibold text-gray-900 dark:text-gray-100">Material Graph</h2><p class:!text-red-600={snapshot?.done && snapshot?.success === false} class="mt-0.5 text-xs text-gray-500">{outcomeLabel(snapshot)}</p></div><div class="text-right text-xs tabular-nums text-gray-500"><div>{Math.round((snapshot?.elapsed_ms ?? 0)/100)/10}s</div><div>{snapshot?.evidence_count ?? 0} 条证据</div></div></div></header>
<div class="min-h-[300px] flex-1"><SvelteFlow {nodes} {edges} {nodeTypes} fitView minZoom={0.25} maxZoom={1.5} nodesDraggable={false} nodesConnectable={false} on:nodeclick={(event)=>(selectedNodeId=event.detail.node.id)}><Background variant={BackgroundVariant.Dots} gap={18} size={1}/><Controls showLock={false}/></SvelteFlow></div>
<div class="max-h-[34%] shrink-0 overflow-y-auto border-t border-gray-100 px-4 py-3 dark:border-gray-800">{#if selectedNode}<div class="mb-3"><div class="text-xs font-medium text-gray-900 dark:text-gray-100">{selectedNode.label}</div><p class="mt-1 text-xs leading-5 text-gray-500">{selectedNode.description ?? selectedNode.summary ?? selectedNode.status}</p></div>{/if}<div class="space-y-2" aria-label="执行日志">{#each (snapshot?.logs ?? []).slice().reverse() as log}<div class="flex gap-2 text-xs"><span class="mt-1.5 size-1.5 shrink-0 rounded-full bg-gray-400"></span><div class="min-w-0"><div class="break-words text-gray-700 dark:text-gray-300">{log.message}</div><div class="mt-0.5 text-[10px] text-gray-400">{log.node_id}{log.timestamp ? ` · ${log.timestamp}` : ''}</div></div></div>{:else}<p class="text-xs text-gray-400">节点日志会随工作流执行实时出现。</p>{/each}</div></div>
</div></SvelteFlowProvider>
