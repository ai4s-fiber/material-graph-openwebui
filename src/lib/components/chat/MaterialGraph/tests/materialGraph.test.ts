import { describe, expect, it } from 'vitest';
import { latestAssistantForm, reduceMaterialGraph, outcomeLabel } from '../contract';
import { layoutWorkflow } from '../layout';

describe('Material Graph contracts', () => {
	it('preserves a complete workflow across partial events', () => {
		const graph=reduceMaterialGraph([
			{action:'material_graph',run_id:'r1',workflow:{nodes:[{id:'intake',label:'Intake'},{id:'gate',label:'Gate'}],edges:[{source:'intake',target:'gate'}]},nodes:[],edges:[]},
			{action:'material_graph',run_id:'r1',current_node:'gate',nodes:[{id:'intake',label:'Intake'},{id:'gate',label:'Gate',status:'awaiting_review'}],edges:[]}
		]);
		expect(graph?.nodes.map((node)=>node.id)).toEqual(['intake','gate']);
		expect(graph?.edges).toHaveLength(1);
		expect(layoutWorkflow(graph!.nodes,graph!.edges).nodes).toHaveLength(2);
	});
	it.each(['failed','blocked','budget_stopped','rejected'])('does not present %s as success',(outcome)=>{
		expect(outcomeLabel({run_id:'r',nodes:[],edges:[],done:true,success:false,outcome})).not.toBe('执行完成');
	});
	it('selects only unresolved latest forms',()=>{
		expect(latestAssistantForm([{action:'assistant_form',form_id:'old',run_id:'r',resolved:true},{action:'assistant_form',form_id:'new',run_id:'r'}])?.form_id).toBe('new');
	});
});
