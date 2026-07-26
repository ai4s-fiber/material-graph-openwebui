describe('Material Graph Studio contract integration', () => {
	it('keeps full topology, validates schema, resumes the same run, and renders rejection', () => {
		cy.intercept('POST','**/chat/completions',{fixture:'material-graph-stream.txt',headers:{'content-type':'text/event-stream'}}).as('chat');
		cy.intercept('POST','**/runs/e2e-run/resume/stream',(request)=>{
			expect(request.headers).to.have.property('idempotency-key','e2e-run:cp-e2e:equipment');
			expect(request.body.run_id).to.eq('e2e-run');
			request.reply({fixture:'material-graph-resume-stream.txt',headers:{'content-type':'text/event-stream'}});
		}).as('resume');
		cy.visit('/');
		cy.get('textarea').first().type('设计一个通用材料方案{enter}');
		cy.contains('Material Graph').should('be.visible');
		cy.contains('需求解析').should('be.visible');
		cy.contains('任意工作流节点').should('be.visible');
		cy.contains('专家审核').should('be.visible');
		cy.contains('补充设备边界').should('be.visible');
		cy.contains('提交并继续').click();
		cy.contains('最高温度为必填项').should('be.visible');
		cy.get('input[type=number]').type('550');
		cy.get('select[multiple]').select(['dma','tga']);
		cy.contains('提交并继续').click();
		cy.contains('最高温度不能大于500').should('be.visible');
		cy.get('input[type=number]').clear().type('450');
		cy.contains('提交并继续').click();
		cy.wait('@resume');
		cy.get('[data-node-id=gate]').should('have.attr','data-node-status','rejected');
		cy.contains('执行被拒绝').should('be.visible');
		cy.screenshot('material-graph-rejected-contract');
	});
});
