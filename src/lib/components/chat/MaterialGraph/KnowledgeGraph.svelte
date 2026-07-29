<script lang="ts">
	import type { MaterialGraphKnowledgeGraph, MaterialGraphKnowledgeNode } from './types';
	import {
		AGENT_VIEW_META,
		AGENT_VIEW_ROLES,
		SHARED_RETRIEVAL_ZONE,
		type KnowledgeGraphZone
	} from './knowledgeGraph';

	export let graph: MaterialGraphKnowledgeGraph | null = null;

	type PositionedNode = MaterialGraphKnowledgeNode & { x: number; y: number };
	const WIDTH = 720;
	const HEIGHT = 560;
	const centers: Record<KnowledgeGraphZone, { x: number; y: number }> = {
		material: { x: 130, y: 145 },
		process: { x: 360, y: 125 },
		performance_testing: { x: 590, y: 150 },
		safety_quality: { x: 130, y: 405 },
		evaluation: { x: 360, y: 430 },
		experiment_design: { x: 590, y: 400 },
		shared_retrieval: { x: 360, y: 280 }
	};
	const graphZones = [...AGENT_VIEW_ROLES, SHARED_RETRIEVAL_ZONE] as KnowledgeGraphZone[];

	let selectedNodeId: string | null = null;
	$: positionedNodes = positionNodes(graph?.nodes ?? []);
	$: nodeById = new Map(positionedNodes.map((node) => [node.id, node]));
	$: positionedEdges = (graph?.edges ?? [])
		.map((edge) => ({
			...edge,
			sourceNode: nodeById.get(edge.source),
			targetNode: nodeById.get(edge.target)
		}))
		.filter((edge) => edge.sourceNode && edge.targetNode);
	$: selectedNode = positionedNodes.find((node) => node.id === selectedNodeId) ?? null;
	$: activeNodeCount = positionedNodes.filter((node) => node.hit || node.active).length;

	function positionNodes(nodes: MaterialGraphKnowledgeNode[]): PositionedNode[] {
		const result: PositionedNode[] = [];
		for (const role of graphZones) {
			const cluster = nodes.filter((node) => node.agentView === role);
			const center = centers[role];
			cluster.forEach((node, index) => {
				const ring = Math.floor(index / 7);
				const inRing = index % 7;
				const ringSize = Math.min(7, cluster.length - ring * 7);
				const angle = (Math.PI * 2 * inRing) / Math.max(ringSize, 1) - Math.PI / 2;
				const radiusX = ring === 0 ? (index === 0 ? 0 : 68) : 94;
				const radiusY = ring === 0 ? (index === 0 ? 0 : 54) : 76;
				result.push({
					...node,
					x: center.x + Math.cos(angle) * radiusX,
					y: center.y + Math.sin(angle) * radiusY
				});
			});
		}
		return result;
	}

	const phaseLabel = (phase: string) =>
		({
			task_subgraph: '任务子图',
			graph_retrieval: '图谱召回',
			literature_expansion: '文献增强',
			agent_partition: 'Agent 分区',
			agent_execution: 'Agent 执行'
		})[phase] ?? phase;

	const nodeOwnershipLabel = (node: MaterialGraphKnowledgeNode) => {
		if (!node.agentViews?.length) return '尚未分配 Agent';
		return node.agentViews.map((role) => AGENT_VIEW_META[role].label).join(' · ');
	};
</script>

<section class="knowledge-shell" aria-label="知识图谱实时信号">
	<header class="signal-header">
		<div>
			<div class="eyebrow"><span class="live-dot"></span> KNOWLEDGE SIGNAL</div>
			<h3>任务知识图谱</h3>
		</div>
		{#if graph}
			<div class="signal-stats" aria-label="知识图谱统计">
				<span>{phaseLabel(graph.phase)}</span>
				<strong>{activeNodeCount}</strong><small> / {graph.nodes.length} 节点命中</small>
			</div>
		{/if}
	</header>

	{#if graph && graph.nodes.length}
		<div class="graph-stage">
			<svg viewBox={`0 0 ${WIDTH} ${HEIGHT}`} role="img" aria-label="六类智能体知识节点关系图">
				<defs>
					<filter id="signal-glow" x="-80%" y="-80%" width="260%" height="260%">
						<feGaussianBlur stdDeviation="4" result="blur" />
						<feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge>
					</filter>
					<pattern id="signal-grid" width="24" height="24" patternUnits="userSpaceOnUse">
						<path
							d="M 24 0 L 0 0 0 24"
							fill="none"
							stroke="currentColor"
							stroke-opacity="0.055"
							stroke-width="1"
						/>
					</pattern>
				</defs>
				<rect width={WIDTH} height={HEIGHT} fill="url(#signal-grid)" class="grid-fill" />

				{#each AGENT_VIEW_ROLES as role}
					{@const meta = AGENT_VIEW_META[role]}
					{@const center = centers[role]}
					<g class="agent-zone" data-agent-zone={role}>
						<rect
							x={center.x - 104}
							y={center.y - 92}
							width="208"
							height="184"
							rx="28"
							fill={meta.soft}
							stroke={meta.color}
							stroke-opacity="0.2"
						/>
						<text x={center.x - 86} y={center.y - 66} fill={meta.color} class="zone-label"
							>{meta.label}</text
						>
					</g>
				{/each}
				<g class="shared-zone" data-agent-zone={SHARED_RETRIEVAL_ZONE}>
					<circle
						cx={centers[SHARED_RETRIEVAL_ZONE].x}
						cy={centers[SHARED_RETRIEVAL_ZONE].y}
						r="66"
						fill={AGENT_VIEW_META[SHARED_RETRIEVAL_ZONE].soft}
						stroke={AGENT_VIEW_META[SHARED_RETRIEVAL_ZONE].color}
						stroke-opacity="0.34"
						stroke-dasharray="4 6"
					/>
					<text
						x={centers[SHARED_RETRIEVAL_ZONE].x}
						y={centers[SHARED_RETRIEVAL_ZONE].y - 49}
						text-anchor="middle"
						fill={AGENT_VIEW_META[SHARED_RETRIEVAL_ZONE].color}
						class="zone-label">共同召回</text
					>
				</g>

				<g class="knowledge-edges">
					{#each positionedEdges as edge}
						<line
							x1={edge.sourceNode!.x}
							y1={edge.sourceNode!.y}
							x2={edge.targetNode!.x}
							y2={edge.targetNode!.y}
							class:active-edge={edge.active || edge.pulse}
							data-knowledge-edge={edge.id}
							data-active={Boolean(edge.active || edge.pulse)}
						/>
						{#if edge.active || edge.pulse}
							<circle
								r="4"
								fill={AGENT_VIEW_META[edge.sourceNode!.agentView].color}
								class="edge-pulse"
								filter="url(#signal-glow)"
							>
								<animate
									attributeName="cx"
									values={`${edge.sourceNode!.x};${edge.targetNode!.x}`}
									dur="1.45s"
									begin="0s"
									repeatCount="indefinite"
								/>
								<animate
									attributeName="cy"
									values={`${edge.sourceNode!.y};${edge.targetNode!.y}`}
									dur="1.45s"
									begin="0s"
									repeatCount="indefinite"
								/>
								<animate
									attributeName="opacity"
									values="0;1;1;0"
									dur="1.45s"
									repeatCount="indefinite"
								/>
							</circle>
						{/if}
					{/each}
				</g>

				<g class="knowledge-nodes">
					{#each positionedNodes as node}
						{@const meta = AGENT_VIEW_META[node.agentView]}
						<g
							role="button"
							tabindex="0"
							aria-label={`${meta.label}：${node.label}`}
							class:hit={node.hit || node.active}
							class:selected={selectedNodeId === node.id}
							data-knowledge-node={node.id}
							data-agent-view={node.agentView}
							transform={`translate(${node.x} ${node.y})`}
							on:click={() => (selectedNodeId = selectedNodeId === node.id ? null : node.id)}
							on:keydown={(event) => {
								if (event.key === 'Enter' || event.key === ' ') selectedNodeId = node.id;
							}}
						>
							{#if node.hit || node.active}<circle
									r="17"
									fill="none"
									stroke={meta.color}
									stroke-opacity="0.26"
									class="node-ripple"
								/>{/if}
							<circle
								r={node.hit || node.active ? 8 : 5.5}
								fill={meta.color}
								opacity={node.hit || node.active ? 1 : 0.48}
								class="node-core"
							/>
							<text y="18" text-anchor="middle" class="node-label"
								>{node.label.length > 10 ? `${node.label.slice(0, 9)}…` : node.label}</text
							>
						</g>
					{/each}
				</g>
			</svg>
		</div>

		<div class="signal-footer">
			<div class="legend" aria-label="Agent 分区图例">
				{#each AGENT_VIEW_ROLES as role}
					<span
						><i style={`--agent-color:${AGENT_VIEW_META[role].color}`}></i>{AGENT_VIEW_META[role]
							.label}</span
					>
				{/each}
			</div>
			{#if graph.truncated}
				<p class="truncated">
					视图已裁剪 · 实际 {graph.receivedNodeCount} 节点 / {graph.receivedEdgeCount} 边
				</p>
			{:else}
				<p>{graph.graphVersionLabel ?? '实时任务子图'} · {graph.edges.length} 条真实关系</p>
			{/if}
		</div>

		{#if selectedNode}
			<div class="node-inspector">
				<div>
					<span style={`--agent-color:${AGENT_VIEW_META[selectedNode.agentView].color}`}
					></span>{nodeOwnershipLabel(selectedNode)}
				</div>
				<strong>{selectedNode.label}</strong>
				{#if selectedNode.description}<p>{selectedNode.description}</p>{/if}
				<small
					>{selectedNode.hit || selectedNode.active
						? '当前任务已召回'
						: '任务子图上下文节点'}</small
				>
			</div>
		{/if}
	{:else}
		<div class="empty-state" data-knowledge-empty="true">
			<div class="empty-orbit"><span></span><span></span><span></span></div>
			<strong>等待真实图谱信号</strong>
			<p>开始材料检索后，这里会显示本次任务实际召回的节点、关系与 Agent 使用范围。</p>
			<small>没有事件时不生成示例节点</small>
		</div>
	{/if}
</section>

<style>
	.knowledge-shell {
		display: flex;
		min-height: 0;
		height: 100%;
		flex-direction: column;
		color: #20302d;
		background: linear-gradient(160deg, #fbfdfb 0%, #f3f8f5 52%, #eef5f2 100%);
		border-top: 1px solid rgba(45, 81, 70, 0.09);
	}
	.signal-header {
		display: flex;
		align-items: flex-end;
		justify-content: space-between;
		gap: 16px;
		padding: 14px 16px 10px;
	}
	.eyebrow {
		display: flex;
		align-items: center;
		gap: 7px;
		color: #6b7f78;
		font-size: 9px;
		font-weight: 700;
		letter-spacing: 0.16em;
	}
	.live-dot {
		width: 6px;
		height: 6px;
		border-radius: 999px;
		background: #35a780;
		box-shadow: 0 0 0 4px rgba(53, 167, 128, 0.12);
	}
	h3 {
		margin: 4px 0 0;
		font-family: 'Noto Serif SC', 'Songti SC', serif;
		font-size: 15px;
		font-weight: 650;
		letter-spacing: 0.02em;
		color: #172622;
	}
	.signal-stats {
		text-align: right;
		color: #788983;
		font-size: 10px;
	}
	.signal-stats span {
		display: block;
		margin-bottom: 2px;
		color: #477064;
	}
	.signal-stats strong {
		color: #172622;
		font-size: 14px;
		font-variant-numeric: tabular-nums;
	}
	.signal-stats small {
		font-size: 9px;
	}
	.graph-stage {
		min-height: 0;
		flex: 1;
		margin: 0 10px;
		overflow: hidden;
		border: 1px solid rgba(45, 81, 70, 0.09);
		border-radius: 18px;
		background: rgba(255, 255, 255, 0.62);
		box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.85);
	}
	svg {
		width: 100%;
		height: 100%;
		min-height: 290px;
		color: #365d51;
	}
	.zone-label {
		font-size: 10px;
		font-weight: 700;
		letter-spacing: 0.08em;
	}
	.knowledge-edges line {
		stroke: #7f9991;
		stroke-width: 1;
		stroke-opacity: 0.18;
		vector-effect: non-scaling-stroke;
	}
	.knowledge-edges line.active-edge {
		stroke: #3b9d7b;
		stroke-width: 1.6;
		stroke-opacity: 0.62;
		stroke-dasharray: 4 5;
		animation: edge-flow 1.2s linear infinite;
	}
	.node-label {
		fill: #40504b;
		font-size: 8.5px;
		pointer-events: none;
	}
	.knowledge-nodes g {
		cursor: pointer;
		outline: none;
	}
	.knowledge-nodes g:hover .node-core,
	.knowledge-nodes g.selected .node-core {
		filter: url(#signal-glow);
	}
	.node-ripple {
		transform-origin: center;
		animation: node-ripple 1.8s ease-out infinite;
	}
	.signal-footer {
		padding: 9px 14px 12px;
	}
	.legend {
		display: grid;
		grid-template-columns: repeat(3, minmax(0, 1fr));
		gap: 5px 8px;
	}
	.legend span {
		display: flex;
		align-items: center;
		gap: 5px;
		min-width: 0;
		color: #5c6e68;
		font-size: 9px;
		white-space: nowrap;
	}
	.legend i {
		width: 6px;
		height: 6px;
		flex: none;
		border-radius: 999px;
		background: var(--agent-color);
	}
	.signal-footer p {
		margin: 7px 0 0;
		color: #7c8c86;
		font-size: 9px;
	}
	.signal-footer .truncated {
		color: #8b7044;
	}
	.node-inspector {
		position: absolute;
		right: 22px;
		bottom: 70px;
		z-index: 3;
		width: min(220px, calc(100% - 44px));
		padding: 11px 12px;
		border: 1px solid rgba(45, 81, 70, 0.12);
		border-radius: 14px;
		background: rgba(252, 254, 253, 0.94);
		box-shadow: 0 14px 40px rgba(30, 62, 52, 0.14);
		backdrop-filter: blur(16px);
	}
	.node-inspector div {
		display: flex;
		align-items: center;
		gap: 6px;
		color: #6e807a;
		font-size: 9px;
	}
	.node-inspector div span {
		width: 6px;
		height: 6px;
		border-radius: 999px;
		background: var(--agent-color);
	}
	.node-inspector strong {
		display: block;
		margin-top: 5px;
		color: #172622;
		font-size: 12px;
	}
	.node-inspector p {
		margin: 4px 0 0;
		color: #5b6e68;
		font-size: 10px;
		line-height: 1.55;
	}
	.node-inspector small {
		display: block;
		margin-top: 6px;
		color: #3f896f;
		font-size: 9px;
	}
	.empty-state {
		display: flex;
		flex: 1;
		min-height: 260px;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		padding: 28px;
		text-align: center;
	}
	.empty-state strong {
		margin-top: 18px;
		font-family: 'Noto Serif SC', 'Songti SC', serif;
		font-size: 15px;
		color: #243630;
	}
	.empty-state p {
		max-width: 270px;
		margin: 8px 0 0;
		color: #74857f;
		font-size: 11px;
		line-height: 1.65;
	}
	.empty-state small {
		margin-top: 8px;
		color: #9aa7a2;
		font-size: 9px;
	}
	.empty-orbit {
		position: relative;
		width: 76px;
		height: 48px;
	}
	.empty-orbit::before,
	.empty-orbit::after {
		content: '';
		position: absolute;
		inset: 7px 0;
		border: 1px solid rgba(59, 126, 104, 0.18);
		border-radius: 50%;
		transform: rotate(12deg);
	}
	.empty-orbit::after {
		transform: rotate(-16deg);
	}
	.empty-orbit span {
		position: absolute;
		width: 7px;
		height: 7px;
		border-radius: 50%;
		background: #69a692;
		box-shadow: 0 0 14px rgba(73, 150, 124, 0.4);
	}
	.empty-orbit span:nth-child(1) {
		left: 6px;
		top: 22px;
	}
	.empty-orbit span:nth-child(2) {
		left: 35px;
		top: 3px;
	}
	.empty-orbit span:nth-child(3) {
		right: 5px;
		bottom: 8px;
	}
	@keyframes edge-flow {
		to {
			stroke-dashoffset: -18;
		}
	}
	@keyframes node-ripple {
		0% {
			transform: scale(0.55);
			opacity: 0.8;
		}
		85%,
		100% {
			transform: scale(1.35);
			opacity: 0;
		}
	}
	:global(.dark) .knowledge-shell {
		color: #dce8e3;
		background: linear-gradient(160deg, #111b18 0%, #15231f 55%, #10201b 100%);
		border-color: rgba(137, 194, 174, 0.08);
	}
	:global(.dark) h3,
	:global(.dark) .signal-stats strong {
		color: #eff7f4;
	}
	:global(.dark) .graph-stage {
		background: rgba(8, 18, 15, 0.38);
		border-color: rgba(137, 194, 174, 0.11);
	}
	:global(.dark) .agent-zone rect {
		fill: #17231f;
		fill-opacity: 0.92;
	}
	:global(.dark) .node-label {
		fill: #b9c9c3;
	}
	:global(.dark) .node-inspector {
		background: rgba(18, 30, 26, 0.94);
		border-color: rgba(137, 194, 174, 0.15);
	}
	:global(.dark) .node-inspector strong,
	:global(.dark) .empty-state strong {
		color: #eff7f4;
	}
	@media (prefers-reduced-motion: reduce) {
		.knowledge-edges line.active-edge,
		.node-ripple {
			animation: none;
		}
		.edge-pulse {
			display: none;
		}
	}
</style>
