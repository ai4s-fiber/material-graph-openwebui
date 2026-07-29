<script context="module" lang="ts">
	export const STUDIO_SIDEBAR_SURFACES = ['new-chat', 'history-search', 'chat-history'] as const;
</script>

<script lang="ts">
	import { goto } from '$app/navigation';
	import { getContext, onMount, tick } from 'svelte';
	import { slide } from 'svelte/transition';

	import { getChatList } from '$lib/apis/chats';
	import { WEBUI_BASE_URL } from '$lib/constants';
	import {
		activeChatIds,
		chats,
		currentChatPage,
		isApp,
		mobile,
		scrollPaginationEnabled,
		selectedFolder,
		showSearch,
		showSidebar,
		sidebarWidth,
		socket,
		temporaryChatEnabled
	} from '$lib/stores';

	import Loader from '../common/Loader.svelte';
	import Spinner from '../common/Spinner.svelte';
	import Tooltip from '../common/Tooltip.svelte';
	import PencilSquare from '../icons/PencilSquare.svelte';
	import Search from '../icons/Search.svelte';
	import SidebarIcon from '../icons/Sidebar.svelte';
	import ChatItem from './Sidebar/ChatItem.svelte';
	import SearchModal from './SearchModal.svelte';

	const i18n = getContext('i18n');
	const MIN_WIDTH = 236;
	const MAX_WIDTH = 400;

	let allChatsLoaded = false;
	let chatListLoading = false;
	let selectedChatId: string | null = null;
	let shiftKey = false;

	const initChatList = async () => {
		currentChatPage.set(1);
		allChatsLoaded = false;
		scrollPaginationEnabled.set(false);

		const chatList = await getChatList(localStorage.token, 1).catch(() => []);
		chats.set(chatList);
		scrollPaginationEnabled.set(true);
	};

	const loadMoreChats = async () => {
		if (chatListLoading || allChatsLoaded) return;
		chatListLoading = true;
		currentChatPage.set($currentChatPage + 1);

		const nextChats = await getChatList(localStorage.token, $currentChatPage).catch(() => []);
		allChatsLoaded = nextChats.length === 0;

		const existingIds = new Set(($chats ?? []).map((chat) => chat.id));
		chats.set([...($chats ?? []), ...nextChats.filter((chat) => !existingIds.has(chat.id))]);
		chatListLoading = false;
	};

	const newChatHandler = async () => {
		selectedChatId = null;
		selectedFolder.set(null);
		temporaryChatEnabled.set(false);
		await goto('/');

		if ($mobile) {
			showSidebar.set(false);
		}
	};

	const onChatEvent = (event: {
		chat_id: string;
		data?: { type?: string; data?: { active?: boolean } };
	}) => {
		if (event.data?.type === 'chat:list') {
			void initChatList();
			return;
		}

		if (event.data?.type === 'chat:active') {
			activeChatIds.update((ids) => {
				const nextIds = new Set(ids);
				if (event.data?.data?.active) {
					nextIds.add(event.chat_id);
				} else {
					nextIds.delete(event.chat_id);
				}
				return nextIds;
			});
		}
	};

	const onKeyDown = (event: KeyboardEvent) => {
		if (event.key === 'Shift') shiftKey = true;
	};

	const onKeyUp = (event: KeyboardEvent) => {
		if (event.key === 'Shift') shiftKey = false;
	};

	onMount(() => {
		const savedWidth = Number(localStorage.getItem('sidebarWidth'));
		if (!Number.isNaN(savedWidth) && savedWidth >= MIN_WIDTH && savedWidth <= MAX_WIDTH) {
			sidebarWidth.set(savedWidth);
		}

		const savedSidebarState = localStorage.getItem('sidebar');
		showSidebar.set(!$mobile && savedSidebarState !== 'false');

		const unsubscribeWidth = sidebarWidth.subscribe((width) => {
			document.documentElement.style.setProperty('--sidebar-width', `${width}px`);
		});
		const unsubscribeSidebar = showSidebar.subscribe((visible) => {
			localStorage.setItem('sidebar', String(visible));
		});
		const unsubscribeMobile = mobile.subscribe((isMobile) => {
			if (isMobile && $showSidebar) showSidebar.set(false);
		});

		const socketInstance = $socket;
		socketInstance?.on('events', onChatEvent);
		window.addEventListener('keydown', onKeyDown);
		window.addEventListener('keyup', onKeyUp);

		void initChatList().then(() => tick());

		return () => {
			unsubscribeWidth();
			unsubscribeSidebar();
			unsubscribeMobile();
			socketInstance?.off('events', onChatEvent);
			window.removeEventListener('keydown', onKeyDown);
			window.removeEventListener('keyup', onKeyUp);
		};
	});
</script>

<SearchModal
	bind:show={$showSearch}
	onClose={() => {
		if ($mobile) showSidebar.set(false);
	}}
/>

{#if $showSidebar && $mobile}
	<button
		class="fixed inset-0 z-40 h-[100dvh] w-full bg-slate-950/55 backdrop-blur-[2px]"
		aria-label={$i18n.t('Close Sidebar')}
		on:click={() => showSidebar.set(false)}
	></button>
{/if}

{#if !$mobile && !$showSidebar}
	<aside
		id="studio-sidebar-rail"
		class="z-30 flex h-screen w-[52px] shrink-0 flex-col items-center gap-1 border-r border-slate-200/70 bg-[#f7f8f6] px-1.5 py-2 text-slate-700 dark:border-slate-800 dark:bg-[#101412] dark:text-slate-200"
		aria-label="Material Graph Studio"
	>
		<Tooltip content={$i18n.t('Open Sidebar')} placement="right">
			<button
				class="mb-2 flex size-9 items-center justify-center rounded-xl transition hover:bg-white dark:hover:bg-slate-800"
				aria-label={$i18n.t('Open Sidebar')}
				on:click={() => showSidebar.set(true)}
			>
				<img src="{WEBUI_BASE_URL}/static/favicon.png" class="size-6 rounded-lg" alt="" />
			</button>
		</Tooltip>

		<Tooltip content={$i18n.t('New Chat')} placement="right">
			<button
				class="flex size-9 items-center justify-center rounded-xl transition hover:bg-white dark:hover:bg-slate-800"
				aria-label={$i18n.t('New Chat')}
				on:click={newChatHandler}
			>
				<PencilSquare className="size-4.5" strokeWidth="2" />
			</button>
		</Tooltip>

		<Tooltip content={$i18n.t('Search')} placement="right">
			<button
				class="flex size-9 items-center justify-center rounded-xl transition hover:bg-white dark:hover:bg-slate-800"
				aria-label={$i18n.t('Search')}
				on:click={() => showSearch.set(true)}
			>
				<Search className="size-4.5" strokeWidth="2" />
			</button>
		</Tooltip>
	</aside>
{/if}

{#if $showSidebar}
	<aside
		id="studio-sidebar"
		class="fixed left-0 top-0 z-50 flex h-screen max-h-[100dvh] min-h-screen w-[var(--sidebar-width)] shrink-0 select-none flex-col overflow-hidden border-r border-slate-200/70 bg-[#f7f8f6]/95 text-sm text-slate-900 shadow-[12px_0_32px_-28px_rgba(15,23,42,0.5)] backdrop-blur-xl dark:border-slate-800 dark:bg-[#101412]/96 dark:text-slate-100 md:relative {$isApp
			? 'ml-[4.5rem] md:ml-0'
			: ''}"
		transition:slide={{ duration: 180, axis: 'x' }}
		data-state="open"
		aria-label="Material Graph Studio"
	>
		<header class="flex items-center gap-2 px-3 pb-3 pt-3">
			<a href="/" class="flex min-w-0 flex-1 items-center gap-2.5" on:click={newChatHandler}>
				<img src="{WEBUI_BASE_URL}/static/favicon.png" class="size-7 rounded-lg" alt="" />
				<div class="min-w-0">
					<div class="truncate text-[13px] font-semibold tracking-[-0.01em]">
						Material Graph Studio
					</div>
					<div class="truncate text-[10px] uppercase tracking-[0.16em] text-slate-400">
						Research workspace
					</div>
				</div>
			</a>

			<button
				class="flex size-8 items-center justify-center rounded-xl text-slate-500 transition hover:bg-white hover:text-slate-900 dark:hover:bg-slate-800 dark:hover:text-white"
				aria-label={$i18n.t('Close Sidebar')}
				on:click={() => showSidebar.set(false)}
			>
				<SidebarIcon className="size-4.5" />
			</button>
		</header>

		<div class="space-y-1 px-2.5 pb-3">
			<button
				id="sidebar-new-chat-button"
				class="group flex w-full items-center gap-3 rounded-xl bg-slate-900 px-3 py-2.5 text-left text-white shadow-sm transition hover:bg-slate-800 dark:bg-[#d8ff6a] dark:text-slate-950 dark:hover:bg-[#c9f45d]"
				aria-label={$i18n.t('New Chat')}
				on:click={newChatHandler}
			>
				<PencilSquare className="size-4.5" strokeWidth="2" />
				<span class="flex-1 text-[13px] font-medium">{$i18n.t('New Chat')}</span>
			</button>

			<button
				id="sidebar-search-button"
				class="flex w-full items-center gap-3 rounded-xl border border-slate-200/80 bg-white/70 px-3 py-2.5 text-left text-slate-600 transition hover:border-slate-300 hover:bg-white hover:text-slate-950 dark:border-slate-800 dark:bg-slate-900/60 dark:text-slate-300 dark:hover:bg-slate-800 dark:hover:text-white"
				aria-label={$i18n.t('Search')}
				on:click={() => showSearch.set(true)}
			>
				<Search className="size-4.5" strokeWidth="2" />
				<span class="flex-1 text-[13px]">{$i18n.t('Search chat history')}</span>
			</button>
		</div>

		<section class="flex min-h-0 flex-1 flex-col" aria-labelledby="studio-chat-history-label">
			<div class="flex items-center justify-between px-4 pb-2 pt-1">
				<h2
					id="studio-chat-history-label"
					class="text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-400"
				>
					{$i18n.t('Chat history')}
				</h2>
			</div>

			<div class="min-h-0 flex-1 overflow-y-auto px-2.5 pb-4 scrollbar-hidden">
				{#if $chats}
					{#if $chats.length === 0}
						<div
							class="mx-1 mt-2 rounded-xl border border-dashed border-slate-200 px-3 py-5 text-center text-xs leading-5 text-slate-400 dark:border-slate-800"
						>
							{$i18n.t('No chat history yet. Start a new conversation.')}
						</div>
					{:else}
						{#each $chats as chat, index (`studio-chat-${chat?.id ?? index}`)}
							{#if index === 0 || chat.time_range !== $chats[index - 1]?.time_range}
								<div class="px-2 pb-1 pt-3 text-[10px] font-medium text-slate-400 first:pt-1">
									{$i18n.t(chat.time_range)}
								</div>
							{/if}

							<ChatItem
								id={chat.id}
								title={chat.title}
								createdAt={chat.created_at}
								updatedAt={chat.updated_at}
								lastReadAt={chat.last_read_at}
								{shiftKey}
								selected={selectedChatId === chat.id}
								on:select={() => {
									selectedChatId = chat.id;
								}}
								on:unselect={() => {
									selectedChatId = null;
								}}
								on:change={initChatList}
							/>
						{/each}

						{#if $scrollPaginationEnabled && !allChatsLoaded}
							<Loader
								on:visible={() => {
									void loadMoreChats();
								}}
							>
								<div class="flex items-center justify-center gap-2 py-3 text-xs text-slate-400">
									<Spinner className="size-3.5" />
									<span>{$i18n.t('Loading...')}</span>
								</div>
							</Loader>
						{/if}
					{/if}
				{:else}
					<div class="flex items-center justify-center gap-2 py-4 text-xs text-slate-400">
						<Spinner className="size-3.5" />
						<span>{$i18n.t('Loading...')}</span>
					</div>
				{/if}
			</div>
		</section>
	</aside>
{/if}
