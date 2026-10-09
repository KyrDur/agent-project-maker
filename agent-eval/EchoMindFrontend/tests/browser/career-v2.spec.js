import {test,expect} from '@playwright/test'
import {readFileSync,writeFileSync,mkdirSync,copyFileSync} from 'node:fs'
import path from 'node:path'
const root=process.env.ECHOMIND_TEST_EVIDENCE_DIR || path.resolve('../../phase5.1')
const source=path.resolve('../../phase4/rag/user-preview/store')
const eid='9c262aad-8c12-449c-8728-7bb9a04ba706',oldid='8423a263-a792-4059-abcb-f27e0a008221'
test('Phase5.1 actual frozen eight-case evidence → gaps → targeted narrative → edits → export → refresh',async({page,request})=>{
 const workspace=JSON.parse(readFileSync(root+'/local-workspace.json'))
 const store=workspace.data_dir+'/store';const evidence=JSON.parse(readFileSync(`${source}/career/evidence/${eid}.json`)).artifact
 for(const s of Object.values(evidence.source_map)){
  if(s.group==='SYSTEM_DERIVED')continue
  mkdirSync(store+'/'+s.group,{recursive:true});writeFileSync(`${store}/${s.group}/${s.id}.json`,JSON.stringify({artifact:s.snapshot,sha256:s.sha256}))
 }
 for(const [group,id] of [['evidence',eid],['materials',oldid]]){
  mkdirSync(`${store}/career/${group}`,{recursive:true});copyFileSync(`${source}/career/${group}/${id}.json`,`${store}/career/${group}/${id}.json`)
 }
 const before=readFileSync(`${store}/career/evidence/${eid}.json`,'utf8');const old=readFileSync(`${store}/career/materials/${oldid}.json`,'utf8')
 const errors=[];page.on('pageerror',e=>errors.push(e.message))
 await page.goto('/');await page.evaluate(ids=>{localStorage.setItem('echomind.workspace.v1',JSON.stringify({step:'career'}));localStorage.setItem('echomind.career.v1',JSON.stringify({evidence:ids.eid,material:ids.oldid}))},{eid,oldid});await page.reload()
 await expect(page.getByRole('heading',{name:'把做过的实验，说清楚。',exact:true})).toBeVisible()
 await page.getByRole('button',{name:'检查证据与待补判断',exact:true}).click()
 await expect(page.getByRole('heading',{name:'只补充真正缺少的判断'})).toBeVisible()
 await expect(page.getByLabel(/你认为排序问题的可能原因/)).toBeVisible()
 await expect(page.getByLabel(/你是否考虑过 Query Rewrite/)).toBeVisible()
 await expect(page.getByLabel(/复测后，你怎样理解结果/)).toHaveCount(0)
 await page.getByRole('button',{name:'基于此 Evidence 生成全套材料',exact:true}).click()
 await expect(page.getByRole('heading',{name:'面试材料准备度',exact:true})).toBeVisible()
 await expect(page.getByText(/锁定 Evidence v2 · Draft/)).toBeVisible()
 await page.getByRole('button',{name:'Interview',exact:true}).click()
 await expect(page.getByTestId('career-interview-story60')).toContainText('从 25% 变为 100%')
 await expect(page.getByTestId('career-interview-story90')).toContainText('没有运行回答评测')
 await page.getByLabel('导出范围',{exact:true}).selectOption('interview')
 const download=page.waitForEvent('download');await page.getByRole('button',{name:'导出 Markdown',exact:true}).click()
 const d=await download;const destination=root+'/browser-interview.md';await d.saveAs(destination)
 expect(readFileSync(destination,'utf8')).toContain('60 秒讲稿');expect(readFileSync(destination,'utf8')).not.toContain('## 通用产品经理简历')
 await page.getByRole('button',{name:'Resume',exact:true}).click();const section=page.getByTestId('career-resume_ai-ai_eval')
 await section.getByRole('button',{name:'编辑文字',exact:true}).click();await section.getByLabel('编辑文案',{exact:true}).fill('回答质量提升了 99%。')
 await section.getByRole('button',{name:'保存文案新版本',exact:true}).click();await expect(page.getByText(/锁定 Evidence v2 · Mixed/)).toBeVisible()
 await section.getByRole('button',{name:'从锁定 Evidence 重新生成此段',exact:true}).click();await expect(page.getByText(/锁定 Evidence v2 · Draft/)).toBeVisible()
 await page.reload();await expect(page.getByRole('heading',{name:'面试材料准备度',exact:true})).toBeVisible()
 expect(readFileSync(`${store}/career/evidence/${eid}.json`,'utf8')).toBe(before);expect(readFileSync(`${store}/career/materials/${oldid}.json`,'utf8')).toBe(old)
 await page.getByRole('button',{name:'Case Study',exact:true}).click();await expect(page.getByRole('heading',{name:'个人判断与方案取舍',exact:true})).toBeVisible()
 await page.screenshot({path:root+'/career-v2-case-study-1440.png',fullPage:true})
 await page.setViewportSize({width:390,height:844});await page.screenshot({path:root+'/career-v2-390.png',fullPage:true})
 expect(errors).toEqual([])
})
