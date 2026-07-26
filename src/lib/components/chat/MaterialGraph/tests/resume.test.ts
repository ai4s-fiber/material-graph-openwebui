import { describe,expect,it,vi } from 'vitest';
import { resumeKey,resumeRun } from '../resume';
const form:any={action:'assistant_form',form_id:'f',run_id:'run-1',checkpoint_id:'cp-1',endpoint:'https://api.test',submit:{path:'/runs/run-1/resume'}};
const response=(body:string,status=200,type='application/json')=>new Response(body,{status,headers:{'content-type':type}});
describe('resume adapter',()=>{
 it('prefers resume stream and preserves the authoritative run',async()=>{
  const fetcher=vi.fn().mockResolvedValue(response('data: {"event":{"type":"status","data":{"action":"material_graph","run_id":"run-1","current_node":"next","nodes":[],"edges":[]}}}\n\n',200,'text/event-stream'));
  const events:any[]=[]; expect(await resumeRun(form,{x:1},(e)=>events.push(e),fetcher)).toEqual({streamed:true});
  expect(fetcher.mock.calls[0][0]).toBe('https://api.test/runs/run-1/resume/stream'); expect(events[0].status.current_node).toBe('next');
  expect((fetcher.mock.calls[0][1].headers as any)['Idempotency-Key']).toBe(resumeKey(form));
 });
 it('falls back only when the stream route is unavailable',async()=>{
  const fetcher=vi.fn().mockResolvedValueOnce(response('{}',404)).mockResolvedValueOnce(response('{"run_id":"run-1"}'));
  expect(await resumeRun(form,{},()=>{},fetcher)).toEqual({streamed:false}); expect(fetcher).toHaveBeenCalledTimes(2);
 });
 it('rejects a fake run returned by legacy resume',async()=>{
  const fetcher=vi.fn().mockResolvedValueOnce(response('{}',405)).mockResolvedValueOnce(response('{"run_id":"fake"}'));
  await expect(resumeRun(form,{},()=>{},fetcher)).rejects.toThrow('run_id');
 });
});
