<script lang="ts">
	import type { AssistantFormDefinition, ResumeEvent } from '../../MaterialGraph/types';
	import { fieldKey, initialValues, normalizeFields, serializeValues, validateValues } from '../../MaterialGraph/formSchema';
	import { resumeRun } from '../../MaterialGraph/resume';
	export let form: AssistantFormDefinition;
	export let onResumeEvent: (event: ResumeEvent) => void = () => {};
	let values: Record<string, any> = {};
	let errors: Record<string, string> = {};
	let submitting = false;
	let submitted = false;
	let error = '';
	let initialized = '';
	$: fields = normalizeFields(form);
	$: {
		const identity = `${form?.run_id}:${form?.checkpoint_id ?? ''}:${form?.form_id}`;
		if (identity && identity !== initialized) {
			initialized = identity; values = initialValues(form, fields); errors = {}; submitted = false; error = '';
		}
	}
	const optionValue = (option: any) => option && typeof option === 'object' ? option.value : option;
	const optionLabel = (option: any) => option && typeof option === 'object' ? option.label ?? option.value : option;
	const submit = async () => {
		if (submitting || submitted) return;
		errors = validateValues(fields, values); error = '';
		if (Object.keys(errors).length) return;
		submitting = true;
		try {
			await resumeRun(form, serializeValues(fields, values), onResumeEvent);
			onResumeEvent({ status: { ...form, resolved: true } as any });
			submitted = true;
		} catch (reason) {
			error = reason instanceof Error ? reason.message : String(reason);
		} finally {
			submitting = false;
		}
	};
</script>
<section class="my-3 rounded-xl border border-gray-200 bg-gray-50 p-4 dark:border-gray-700 dark:bg-gray-900/60" aria-labelledby={`form-${form.form_id}`}>
	<h3 id={`form-${form.form_id}`} class="text-sm font-semibold text-gray-900 dark:text-gray-100">{form.title ?? '需要补充信息'}</h3>
	{#if form.description}<p class="mt-1 text-xs leading-5 text-gray-500">{form.description}</p>{/if}
	{#if submitted}
		<div class="mt-3 rounded-lg bg-blue-50 px-3 py-2 text-sm text-blue-700 dark:bg-blue-950/40 dark:text-blue-300">已提交，正在从原 checkpoint 继续。</div>
	{:else}
		<form class="mt-3 space-y-3" on:submit|preventDefault={submit}>
			{#each fields as field}
				{@const key = fieldKey(field)}
				<label class="block text-xs font-medium text-gray-700 dark:text-gray-300">
					<span>{field.label ?? key}{field.required ? ' *' : ''}</span>
					{#if field.description}<span class="mt-0.5 block font-normal leading-4 text-gray-500">{field.description}</span>{/if}
					{#if field.type === 'select'}
						<select bind:value={values[key]} aria-invalid={Boolean(errors[key])} class="mt-1 w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm dark:border-gray-700 dark:bg-gray-850"><option value="">请选择</option>{#each field.options ?? [] as option}<option value={optionValue(option)}>{optionLabel(option)}</option>{/each}</select>
					{:else if field.type === 'multiselect'}
						<select multiple bind:value={values[key]} aria-invalid={Boolean(errors[key])} class="mt-1 min-h-24 w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm dark:border-gray-700 dark:bg-gray-850">{#each field.options ?? [] as option}<option value={optionValue(option)}>{optionLabel(option)}</option>{/each}</select>
					{:else if field.type === 'textarea'}
						<textarea bind:value={values[key]} placeholder={field.placeholder ?? ''} aria-invalid={Boolean(errors[key])} rows="3" class="mt-1 w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm dark:border-gray-700 dark:bg-gray-850"></textarea>
					{:else if field.type === 'boolean' || field.type === 'checkbox'}
						<input bind:checked={values[key]} type="checkbox" class="ml-2 align-middle" />
					{:else}
						<input bind:value={values[key]} type={field.type === 'number' ? 'number' : 'text'} min={field.minimum} max={field.maximum} placeholder={field.placeholder ?? ''} aria-invalid={Boolean(errors[key])} class="mt-1 w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm dark:border-gray-700 dark:bg-gray-850" />
					{/if}
					{#if errors[key]}<span class="mt-1 block font-normal text-red-600 dark:text-red-400">{errors[key]}</span>{/if}
				</label>
			{/each}
			{#if error}<p class="text-xs text-red-600 dark:text-red-400">{error}</p>{/if}
			<button type="submit" disabled={submitting || submitted} class="rounded-lg bg-gray-900 px-3 py-2 text-sm font-medium text-white hover:bg-gray-700 disabled:opacity-50 dark:bg-gray-100 dark:text-gray-900">{submitting ? '提交中…' : '提交并继续'}</button>
		</form>
	{/if}
</section>
