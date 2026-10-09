import test from 'node:test'
import assert from 'node:assert/strict'
import { prepareWorkspace, ApiError } from '../src/api.js'

const storage = initial => {
  const data = new Map(Object.entries(initial))
  return {data, getItem:k=>data.get(k) ?? null, setItem:(k,v)=>data.set(k,v), removeItem:k=>data.delete(k)}
}
const response = data => async (url,options) => {
  assert.equal(url,'/api/experiments/workspace')
  assert.equal(options.credentials,'same-origin')
  assert.equal(options.cache,'no-store')
  return {ok:true,json:async()=>data}
}
test('new browser identity clears only stale experiment pointers, never creates identity in storage',async()=>{
  const s=storage({'echomind.workspace.v1':'old','echomind.retrieval.v1':'old','echomind.career.v1':'old','other-app':'keep'})
  await prepareWorkspace(s,response({isolated:true,workspace_ref:'a'.repeat(64)}))
  assert.equal(s.getItem('echomind.workspace.v1'),null)
  assert.equal(s.getItem('echomind.retrieval.v1'),null)
  assert.equal(s.getItem('echomind.career.v1'),null)
  assert.equal(s.getItem('other-app'),'keep')
  assert.equal(s.getItem('echomind.browser-workspace'),'a'.repeat(64))
})
test('same browser restores its existing pointers',async()=>{
  const s=storage({'echomind.browser-workspace':'a'.repeat(64),'echomind.workspace.v1':'own'})
  await prepareWorkspace(s,response({isolated:true,workspace_ref:'a'.repeat(64)}))
  assert.equal(s.getItem('echomind.workspace.v1'),'own')
})
test('legacy local server leaves existing local pointers intact',async()=>{
  const s=storage({'echomind.workspace.v1':'old'})
  await prepareWorkspace(s,response({isolated:false}))
  assert.equal(s.getItem('echomind.workspace.v1'),'old')
})
test('bootstrap rejection is explicit and does not wipe pointers',async()=>{
  const s=storage({'echomind.workspace.v1':'old'})
  await assert.rejects(prepareWorkspace(s,async()=>({ok:false,status:503,json:async()=>({detail:'WORKSPACE_CAPACITY_REACHED'})})),ApiError)
  assert.equal(s.getItem('echomind.workspace.v1'),'old')
})
test('storage unavailable still permits cookie-based identity',async()=>{
  const s={getItem:()=>{throw Error('disabled')}}
  assert.equal((await prepareWorkspace(s,response({isolated:true,workspace_ref:'a'.repeat(64)}))).isolated,true)
})
