import { describe, expect, it } from 'vitest';
import { initialValues, normalizeFields, serializeValues, validateValues } from '../formSchema';
const form: any = {
	action: 'assistant_form',
	form_id: 'f',
	run_id: 'r',
	schema: {
		type: 'object',
		required: ['temperature', 'modes'],
		properties: {
			temperature: {
				type: 'number',
				title: '温度',
				minimum: 10,
				maximum: 20,
				description: '工艺上限'
			},
			decision: { type: 'string', enum: ['approve', 'reject'] },
			modes: { type: 'array', items: { type: 'string', enum: ['a', 'b', 'c'] }, minItems: 2 },
			enabled: { type: 'boolean', default: true }
		}
	}
};
describe('JSON Schema forms', () => {
	it('normalizes enum, multiselect, boolean, descriptions and ranges', () => {
		const fields = normalizeFields(form);
		expect(fields.map((x) => x.type)).toEqual(['number', 'select', 'multiselect', 'boolean']);
		expect(fields[0].description).toBe('工艺上限');
		expect(initialValues(form, fields).enabled).toBe(true);
	});
	it('returns deterministic field errors and typed numbers', () => {
		const fields = normalizeFields(form),
			values = { temperature: 30, decision: 'approve', modes: ['a'], enabled: false };
		expect(validateValues(fields, values)).toEqual({
			temperature: '温度不能大于20',
			modes: 'modes至少选择2项'
		});
		expect(serializeValues(fields, { ...values, temperature: '12' }).temperature).toBe(12);
	});
});
