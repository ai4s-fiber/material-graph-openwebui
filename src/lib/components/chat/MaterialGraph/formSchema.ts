import type { AssistantFormDefinition, AssistantFormField } from './types';
export const fieldKey = (field: AssistantFormField) =>
	String(field.name ?? field.key ?? field.id ?? '');
export const normalizeFields = (form: AssistantFormDefinition): AssistantFormField[] => {
	if (form.fields?.length) return form.fields;
	const properties = form.schema?.properties ?? {};
	const required: string[] = form.schema?.required ?? [];
	return Object.entries(properties).map(([name, raw]: [string, any]) => ({
		name,
		label: raw.title ?? name,
		description: raw.description,
		required: required.includes(name),
		type:
			raw.type === 'array' && raw.items?.enum
				? 'multiselect'
				: raw.enum
					? 'select'
					: ['number', 'integer'].includes(raw.type)
						? 'number'
						: raw.type === 'object'
							? 'object'
							: raw.type === 'boolean'
								? 'boolean'
								: raw.format === 'multiline' || raw.format === 'textarea'
									? 'textarea'
									: 'text',
		default: raw.default,
		minimum: raw.minimum,
		maximum: raw.maximum,
		minItems: raw.minItems,
		maxItems: raw.maxItems,
		multiple: raw.type === 'array',
		options: (raw.enum ?? raw.items?.enum)?.map((value: unknown, index: number) => ({
			value,
			label:
				raw['x-enum-labels']?.[String(value)] ??
				raw.items?.['x-enum-labels']?.[String(value)] ??
				raw.enumNames?.[index] ??
				String(value)
		}))
	}));
};
export const initialValues = (form: AssistantFormDefinition, fields = normalizeFields(form)) =>
	Object.fromEntries(
		fields.map((field) => {
			const key = fieldKey(field);
			const value =
				form.defaults?.[key] ??
				field.default ??
				(field.type === 'boolean' ? false : field.type === 'multiselect' ? [] : '');
			return [
				key,
				field.type === 'object' && value !== '' ? JSON.stringify(value, null, 2) : value
			];
		})
	);
export const validateValues = (fields: AssistantFormField[], values: Record<string, any>) => {
	const errors: Record<string, string> = {};
	for (const field of fields) {
		const key = fieldKey(field),
			value = values[key],
			label = field.label ?? key;
		const empty = value === '' || value == null || (Array.isArray(value) && value.length === 0);
		if (field.required && empty) errors[key] = `${label}为必填项`;
		else if (!empty && field.type === 'number' && !Number.isFinite(Number(value)))
			errors[key] = `${label}必须是数字`;
		else if (!empty && field.type === 'object') {
			try {
				const parsed = typeof value === 'string' ? JSON.parse(value) : value;
				if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) throw new Error();
			} catch {
				errors[key] = `${label}必须是有效的 JSON 对象`;
			}
		} else if (!empty && field.minimum != null && Number(value) < field.minimum)
			errors[key] = `${label}不能小于${field.minimum}`;
		else if (!empty && field.maximum != null && Number(value) > field.maximum)
			errors[key] = `${label}不能大于${field.maximum}`;
		else if (Array.isArray(value) && field.minItems != null && value.length < field.minItems)
			errors[key] = `${label}至少选择${field.minItems}项`;
		else if (Array.isArray(value) && field.maxItems != null && value.length > field.maxItems)
			errors[key] = `${label}最多选择${field.maxItems}项`;
	}
	return errors;
};
export const serializeValues = (fields: AssistantFormField[], values: Record<string, any>) =>
	Object.fromEntries(
		fields.map((field) => {
			const key = fieldKey(field),
				value = values[key];
			return [
				key,
				field.type === 'number' && value !== ''
					? Number(value)
					: field.type === 'object' && typeof value === 'string' && value !== ''
						? JSON.parse(value)
						: value
			];
		})
	);
