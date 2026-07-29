<script lang="ts">
	import MaterialGraphView from './View.svelte';
	import KnowledgeGraphView from './KnowledgeGraph.svelte';
	import { hasStartedMaterialGraphWorkflow } from './panelState';
	import type { MaterialGraphKnowledgeGraph, MaterialGraphSnapshot } from './types';

	export let workflow: MaterialGraphSnapshot | null = null;
	export let knowledge: MaterialGraphKnowledgeGraph | null = null;
</script>

<div class="studio-graph-panel" data-studio-graph-panel="true">
	<section class="workflow-section" aria-label="执行流程图">
		{#if hasStartedMaterialGraphWorkflow(workflow)}
			<MaterialGraphView snapshot={workflow} compact={true} />
		{:else}
			<div class="workflow-empty">
				<div class="workflow-empty-line"><span></span><span></span><span></span></div>
				<strong>执行流程待启动</strong>
				<p>发起材料研发任务后，全流程会在这里保持可见。</p>
			</div>
		{/if}
	</section>
	<section class="knowledge-section" aria-label="知识图谱信号">
		<KnowledgeGraphView graph={knowledge} />
	</section>
</div>

<style>
	.studio-graph-panel {
		display: flex;
		min-height: 0;
		height: 100%;
		flex-direction: column;
		overflow: hidden;
		background: #fff;
	}
	.workflow-section {
		min-height: 210px;
		height: 43%;
		overflow: hidden;
		border-bottom: 1px solid rgba(45, 81, 70, 0.1);
	}
	.workflow-empty {
		display: flex;
		height: 100%;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		padding: 20px;
		text-align: center;
		color: #74817d;
		background: linear-gradient(180deg, #fff 0%, #f7faf8 100%);
	}
	.workflow-empty strong {
		margin-top: 12px;
		color: #344640;
		font-size: 12px;
	}
	.workflow-empty p {
		margin: 5px 0 0;
		font-size: 10px;
	}
	.workflow-empty-line {
		display: flex;
		align-items: center;
		gap: 8px;
	}
	.workflow-empty-line span {
		display: block;
		width: 32px;
		height: 7px;
		border: 1px solid #b9c9c3;
		border-radius: 999px;
	}
	.workflow-empty-line span:nth-child(2) {
		width: 52px;
		background: #e8f0ec;
	}
	.knowledge-section {
		min-height: 0;
		flex: 1;
	}
	:global(.dark) .studio-graph-panel {
		background: #101715;
	}
	:global(.dark) .workflow-empty {
		color: #8da09a;
		background: linear-gradient(180deg, #111b18 0%, #0d1512 100%);
	}
	:global(.dark) .workflow-empty strong {
		color: #dce8e3;
	}
	:global(.dark) .workflow-section {
		border-color: rgba(137, 194, 174, 0.1);
	}
</style>
