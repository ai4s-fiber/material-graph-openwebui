<script lang="ts">
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';

	onMount(() => {
		void goto('/', { replaceState: true });
	});
</script>

<svelte:head>
	<title>Material Graph Studio</title>
</svelte:head>

<main
	class="grid min-h-screen place-items-center bg-white text-sm text-slate-500 dark:bg-slate-950 dark:text-slate-400"
	role="status"
	aria-live="polite"
>
	正在返回 Material Graph Studio…
</main>
