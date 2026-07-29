<script context="module" lang="ts">
	let savedTab: 'overview' | 'materialGraph' = 'materialGraph';
</script>

<script lang="ts">
	import { Pane, PaneResizer } from 'paneforge';

	import { onMount, tick, getContext } from 'svelte';
	import { showControls } from '$lib/stores';
	import Drawer from '../common/Drawer.svelte';
	import Overview from './Overview.svelte';
	import StudioGraphPanel from './MaterialGraph/StudioGraphPanel.svelte';
	import { latestKnowledgeGraph, latestMaterialGraph } from './MaterialGraph/types';

	const i18n = getContext('i18n');

	export let history;
	export let models = [];

	export let chatId = null;

	export let chatFiles = [];
	export let params = {};

	export let eventTarget: EventTarget;
	export let submitPrompt: Function;
	export let stopResponse: Function;
	export let showMessage: Function;
	export let files;
	export let modelId;

	export let codeInterpreterEnabled = false;

	export let pane: Pane | null = null;

	let largeScreen = false;
	let minSize = 0;
	let paneReady = false;

	// Tab state for the compact graph panel.
	let activeTab = savedTab;
	let lastAutoOpenedRun = '';
	$: materialGraph = latestMaterialGraph(history);
	$: knowledgeGraph = latestKnowledgeGraph(history);
	// The workflow is a permanent part of this product, not a transient debug
	// inspector. Before a task begins it intentionally renders an honest empty
	// state instead of hiding the whole right-hand workspace.
	$: showMaterialGraphTab = true;
	$: activeRunId = materialGraph?.run_id ?? knowledgeGraph?.runId ?? '';
	$: if (activeRunId && activeRunId !== lastAutoOpenedRun) {
		lastAutoOpenedRun = activeRunId;
		activeTab = 'materialGraph';
		showControls.set(true);
	}
	// svelte-ignore reactive_declaration_module_script_dependency
	$: {
		savedTab = activeTab;
	}

	$: hasMessages = history?.messages && Object.keys(history.messages).length > 0;

	// Material Graph Studio deliberately removes Open WebUI's advanced controls and file tabs.
	$: showOverviewTab = hasMessages;

	// Tab fallback: if active tab becomes hidden, switch to next available
	$: if (!showOverviewTab && activeTab === 'overview' && showMaterialGraphTab)
		activeTab = 'materialGraph';
	$: if (!showMaterialGraphTab && activeTab === 'materialGraph' && showOverviewTab)
		activeTab = 'overview';

	// Auto-close if there are no visible tabs
	$: if (!showMaterialGraphTab && !showOverviewTab) {
		showControls.set(false);
	}

	export const openPane = () => {
		if (parseInt(localStorage?.chatControlsSize)) {
			const container = document.getElementById('chat-container');
			let size = Math.floor(
				(parseInt(localStorage?.chatControlsSize) / container.clientWidth) * 100
			);
			pane.resize(size);
		} else {
			pane.resize(minSize);
		}
	};

	const handleMediaQuery = (e) => {
		if (e.matches) {
			largeScreen = true;
			// Material Graph Studio is a three-pane research workbench on desktop:
			// chat on the centre, workflow/knowledge context on the right.
			showControls.set(true);
		} else {
			largeScreen = false;
			pane = null;
		}
	};

	onMount(() => {
		const mediaQuery = window.matchMedia('(min-width: 1024px)');
		mediaQuery.addEventListener('change', handleMediaQuery);
		handleMediaQuery(mediaQuery);

		let resizeObserver: ResizeObserver | null = null;
		let isDestroyed = false;

		// Wait for Svelte to render the Pane after largeScreen changed
		const init = async () => {
			await tick();

			if (isDestroyed) return;

			// If controls were persisted as open, set the pane to the saved size
			if ($showControls && pane) {
				openPane();
			}

			setTimeout(() => {
				paneReady = true;
			}, 0);

			const container = document.getElementById('chat-container') as HTMLElement;
			if (!container) return;

			minSize = Math.floor((350 / container.clientWidth) * 100);
			resizeObserver = new ResizeObserver((entries) => {
				for (let entry of entries) {
					const width = entry.contentRect.width;
					minSize = Math.floor((350 / width) * 100);
					if ($showControls) {
						if (pane && pane.isExpanded() && pane.getSize() < minSize) {
							pane.resize(minSize);
						} else {
							let size = Math.floor(
								(parseInt(localStorage?.chatControlsSize) / container.clientWidth) * 100
							);
							if (size < minSize && pane) pane.resize(minSize);
						}
					}
				}
			});
			resizeObserver.observe(container);
		};
		init();

		return () => {
			isDestroyed = true;
			paneReady = false;
			resizeObserver?.disconnect();
			if (!largeScreen) {
				showControls.set(false);
			}
			mediaQuery.removeEventListener('change', handleMediaQuery);
		};
	});

	const closeHandler = () => {
		if (!largeScreen) {
			showControls.set(false);
		}
	};

	$: if (paneReady && !chatId) closeHandler();
</script>

{#if !largeScreen}
	{#if $showControls}
		<Drawer
			show={$showControls}
			onClose={() => showControls.set(false)}
			className="min-h-[100dvh] !bg-white dark:!bg-gray-850"
		>
			<div class="h-[100dvh] flex flex-col">
				<!-- Material Graph Studio: workflow + truthful knowledge signal -->
				<div class="flex flex-col h-full min-h-0">
					<!-- Tab bar -->
					<div class="flex items-center justify-between px-2 pt-2 pb-2 shrink-0">
						<div class="flex gap-1 min-w-0 overflow-x-auto scrollbar-hidden">
							{#if showMaterialGraphTab}
								<button
									class="studio-tab {activeTab === 'materialGraph' ? 'active' : ''}"
									on:click={() => (activeTab = 'materialGraph')}>运行图谱</button
								>
							{/if}
							{#if showOverviewTab}
								<button
									class="studio-tab {activeTab === 'overview' ? 'active' : ''}"
									on:click={() => (activeTab = 'overview')}
								>
									概述
								</button>
							{/if}
						</div>
						<button
							class="p-1 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-800 transition text-gray-500 dark:text-gray-400"
							on:click={() => showControls.set(false)}
							aria-label={$i18n.t('Close')}
						>
							<svg
								xmlns="http://www.w3.org/2000/svg"
								viewBox="0 0 24 24"
								fill="none"
								stroke="currentColor"
								stroke-width="1.5"
								class="size-4"
							>
								<path stroke-linecap="round" stroke-linejoin="round" d="M6 18 18 6M6 6l12 12" />
							</svg>
						</button>
					</div>

					<div class="flex-1 min-h-0">
						{#if activeTab === 'materialGraph'}
							<StudioGraphPanel workflow={materialGraph} knowledge={knowledgeGraph} />
						{:else if activeTab === 'overview'}
							<Overview
								{history}
								onNodeClick={(e) => {
									const node = e.node;
									showMessage(node.data.message, true);
								}}
								onClose={() => showControls.set(false)}
							/>
						{/if}
					</div>
				</div>
			</div>
		</Drawer>
	{/if}
{:else}
	{#if $showControls}
		<PaneResizer
			class="relative flex items-center justify-center group border-l border-gray-50 dark:border-gray-850/30 hover:border-gray-200 dark:hover:border-gray-800 transition z-20"
			id="controls-resizer"
		>
			<div
				class="absolute -left-1.5 -right-1.5 -top-0 -bottom-0 z-20 cursor-col-resize bg-transparent"
			/>
		</PaneResizer>
	{/if}

	<Pane
		bind:pane
		defaultSize={0}
		onResize={(size) => {
			if ($showControls && pane.isExpanded()) {
				if (size < minSize) pane.resize(minSize);
				if (size < minSize) {
					localStorage.chatControlsSize = 0;
				} else {
					const container = document.getElementById('chat-container');
					localStorage.chatControlsSize = Math.floor((size / 100) * container.clientWidth);
				}
			}
		}}
		onCollapse={() => {
			if (paneReady) showControls.set(false);
		}}
		collapsible={true}
		class="z-10 bg-white dark:bg-gray-850"
	>
		{#if $showControls}
			<div class="flex max-h-full min-h-full">
				<div
					class="w-full bg-white dark:shadow-lg dark:bg-gray-850 z-40 pointer-events-auto overflow-hidden scrollbar-hidden"
					id="controls-container"
				>
					<!-- Material Graph Studio: workflow + truthful knowledge signal -->
					<div class="flex flex-col h-full min-h-0">
						<!-- Tab bar -->
						<div class="flex items-center justify-between px-2 pt-2 pb-2 shrink-0">
							<div class="flex gap-1 min-w-0 overflow-x-auto scrollbar-hidden">
								{#if showMaterialGraphTab}
									<button
										class="studio-tab {activeTab === 'materialGraph' ? 'active' : ''}"
										on:click={() => (activeTab = 'materialGraph')}>运行图谱</button
									>
								{/if}
								{#if showOverviewTab}
									<button
										class="studio-tab {activeTab === 'overview' ? 'active' : ''}"
										on:click={() => (activeTab = 'overview')}
									>
										概述
									</button>
								{/if}
							</div>
							<button
								class="p-1 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-800 transition text-gray-500 dark:text-gray-400"
								on:click={() => showControls.set(false)}
								aria-label={$i18n.t('Close')}
							>
								<svg
									xmlns="http://www.w3.org/2000/svg"
									viewBox="0 0 24 24"
									fill="none"
									stroke="currentColor"
									stroke-width="1.5"
									class="size-4"
								>
									<path stroke-linecap="round" stroke-linejoin="round" d="M6 18 18 6M6 6l12 12" />
								</svg>
							</button>
						</div>

						<div class="flex-1 min-h-0">
							{#if activeTab === 'materialGraph'}
								<StudioGraphPanel workflow={materialGraph} knowledge={knowledgeGraph} />
							{:else if activeTab === 'overview'}
								<Overview
									{history}
									onNodeClick={(e) => {
										const node = e.node;
										if (node?.data?.message?.favorite) {
											history.messages[node.data.message.id].favorite = true;
										} else {
											history.messages[node.data.message.id].favorite = null;
										}
										showMessage(node.data.message, true);
									}}
									onClose={() => showControls.set(false)}
								/>
							{/if}
						</div>
					</div>
				</div>
			</div>
		{/if}
	</Pane>
{/if}

<style>
	.studio-tab {
		border: 1px solid transparent;
		border-radius: 10px;
		padding: 5px 10px;
		color: rgb(107 114 128);
		font-size: 12px;
		transition: 160ms ease;
		white-space: nowrap;
	}
	.studio-tab:hover {
		background: rgb(248 250 249);
		color: rgb(31 41 55);
	}
	.studio-tab.active {
		border-color: rgb(207 226 218);
		background: rgb(239 248 243);
		color: rgb(31 86 67);
		font-weight: 600;
	}
	:global(.dark) .studio-tab:hover {
		background: rgb(31 41 55);
		color: rgb(229 231 235);
	}
	:global(.dark) .studio-tab.active {
		border-color: rgb(52 91 76);
		background: rgb(23 55 43);
		color: rgb(190 235 213);
	}
</style>
