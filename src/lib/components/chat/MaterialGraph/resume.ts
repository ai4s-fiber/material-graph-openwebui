import type { AssistantFormDefinition, ResumeEvent } from './types';
const unavailable = new Set([404,405,501]);
export const resumeKey = (form: AssistantFormDefinition) => [form.run_id, form.checkpoint_id ?? 'checkpoint', form.form_id].join(':');
const absolute = (base:string,path:string) => /^https?:\/\//.test(path) ? path : `${base.replace(/\/$/,'')}${path.startsWith('/') ? path : `/${path}`}`;
export const parseSse = async (response: Response, runId: string, emit: (event:ResumeEvent)=>void) => {
	if (!response.body) return;
	const reader=response.body.getReader(), decoder=new TextDecoder(); let buffer='';
	while (true) {
		const {done,value}=await reader.read(); buffer+=decoder.decode(value ?? new Uint8Array(),{stream:!done});
		const chunks=buffer.split(/\r?\n\r?\n/); buffer=chunks.pop() ?? '';
		for (const chunk of chunks) {
			const data=chunk.split(/\r?\n/).filter((line)=>line.startsWith('data:')).map((line)=>line.slice(5).trim()).join('\n');
			if (!data || data === '[DONE]') continue;
			const raw=JSON.parse(data), status=raw?.event?.type === 'status' ? raw.event.data : raw?.status;
			const eventRun=status?.run_id ?? status?.runId ?? raw?.run_id;
			if (eventRun && eventRun !== runId) throw new Error('恢复流返回了不匹配的 run_id');
			const token=raw?.delta ?? raw?.token ?? (['token','assistant_token','text_delta'].includes(raw?.event?.type) ? raw.event?.data?.text : undefined);
			emit({token, status, raw});
		}
		if (done) break;
	}
};
export const resumeRun = async (form:AssistantFormDefinition, values:Record<string,unknown>, emit:(event:ResumeEvent)=>void, fetcher:typeof fetch=fetch) => {
	const base=form.endpoint ?? '', legacy=form.submit?.url ?? form.submit?.path ?? `/runs/${form.run_id}/resume`;
	if (!base && !/^https?:\/\//.test(legacy)) throw new Error('未配置 Material Graph API 地址');
	const stream=form.submit?.stream_path ?? (legacy.endsWith('/resume') ? `${legacy}/stream` : `/runs/${form.run_id}/resume/stream`);
	const body=JSON.stringify({...(form.submission ?? {}),values,run_id:form.run_id,checkpoint_id:form.checkpoint_id});
	const headers={'Content-Type':'application/json','Idempotency-Key':resumeKey(form)};
	const response=await fetcher(absolute(base,stream),{method:form.submit?.method ?? 'POST',headers,body});
	if (response.ok) { await parseSse(response,form.run_id,emit); return {streamed:true}; }
	if (!unavailable.has(response.status)) throw new Error((await response.json().catch(()=>null))?.detail ?? `HTTP ${response.status}`);
	const fallback=await fetcher(absolute(base,legacy),{method:form.submit?.method ?? 'POST',headers,body});
	if (!fallback.ok) throw new Error((await fallback.json().catch(()=>null))?.detail ?? `HTTP ${fallback.status}`);
	const result=await fallback.json().catch(()=>null), resultRun=result?.run_id ?? result?.runId;
	if (resultRun && resultRun !== form.run_id) throw new Error('恢复响应返回了不匹配的 run_id');
	if (result?.status) emit({status:result.status,raw:result});
	return {streamed:false};
};
