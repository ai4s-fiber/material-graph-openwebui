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
	it('validates and serializes object fields as JSON', () => {
		const fields: any[] = [{ name: 'metadata', type: 'object' }];
		expect(validateValues(fields, { metadata: '{broken' })).toEqual({
			metadata: 'metadata必须是有效的 JSON 对象'
		});
		expect(serializeValues(fields, { metadata: '{"batch": 3}' })).toEqual({
			metadata: { batch: 3 }
		});
		expect(
			initialValues({ ...form, defaults: { metadata: { source: 'operator' } } }, fields).metadata
		).toBe('{\n  "source": "operator"\n}');
	});
	it('keeps natural-language objectives as textarea text instead of object JSON', () => {
		const fields = normalizeFields({
			...form,
			schema: {
				type: 'object',
				required: ['objective_text'],
				properties: {
					objective_text: {
						type: 'string',
						title: '研发目标',
						format: 'textarea'
					}
				}
			}
		});
		expect(fields[0].type).toBe('textarea');
		expect(serializeValues(fields, { objective_text: '高 Tg，且低介电' })).toEqual({
			objective_text: '高 Tg，且低介电'
		});
	});
});
