(() => {
  let course='settings', step=0, passed=false;
  const lessons={
    settings:{surface:'<h3>显示偏好 · 练习</h3><p>夜间使用电脑时，可以减少屏幕的蓝光。</p><label class="coach-switch" data-coach-target="toggle"><span>夜间模式</span><input id="coach-night" type="checkbox" role="switch" aria-label="夜间模式"></label><label class="coach-field" data-coach-target="strength">强度 <input id="coach-strength" type="range" min="0" max="100" value="20" aria-label="夜间模式强度"><output id="coach-strength-value">20%</output></label><div class="coach-monitor" aria-label="屏幕效果预览">Aa <span>阅读更舒适</span></div>',steps:[
      ['打开夜间模式','找到右侧开关，亲手将夜间模式打开。','开关在文字右侧；黑色表示开启。','toggle',()=>document.querySelector('#coach-night').checked,'开关还没有打开，再试一次。'],
      ['调整到适合的强度','将强度调到 40% 至 60% 之间，观察预览变化。','拖动滑块，或者用键盘方向键微调。','strength',()=>document.querySelector('#coach-night').checked&&+document.querySelector('#coach-strength').value>=40&&+document.querySelector('#coach-strength').value<=60,'保持夜间模式开启，并把强度调到 40% 至 60%。'],
      ['练习恢复原状','现在关闭夜间模式。会调整，也要知道如何恢复。','点击同一个开关即可关闭；无需修改其它设置。','toggle',()=>!document.querySelector('#coach-night').checked,'开关仍然开启。关掉它就完成了。']]},
    excel:{surface:'<h3>本周学习时长</h3><p>这是一张可编辑的练习表。公式仅支持本课的求和。</p><table class="coach-sheet"><caption>单位：分钟</caption><thead><tr><th scope="col"></th><th scope="col">A</th><th scope="col">B</th></tr></thead><tbody><tr><th scope="row">1</th><td>周一</td><td>20</td></tr><tr><th scope="row">2</th><td>周二</td><td>30</td></tr><tr><th scope="row">3</th><td>周三</td><td><input id="coach-b3" aria-label="B3 学习分钟" value="40" inputmode="numeric" data-coach-target="value"></td></tr><tr><th scope="row">4</th><td>合计</td><td><input id="coach-b4" aria-label="B4 求和公式" placeholder="在这里输入公式" data-coach-target="formula"><output id="coach-result" aria-live="polite">尚未输入公式</output></td></tr></tbody></table>',steps:[
      ['从等号开始','在 B4 输入公式，将 B1 到 B3 的分钟数相加。','输入 =SUM(B1:B3)。冒号表示连续的一段单元格。','formula',()=>formulaOK(),'请输入 =SUM(B1:B3)，直接填 90 不能表达求和规则。'],
      ['让公式替你更新','把 B3 的 40 改成 50，观察合计是否变成 100。','只修改 B3，保留 B4 的公式。','value',()=>formulaOK()&&document.querySelector('#coach-b3').value.trim()==='50','请将 B3 改为 50，并保留 B4 的求和公式。'],
      ['不靠提示，再做一次','现在把 B3 改成 35。合计应该是多少？请亲手验证。','20 + 30 + 35 = 85，公式会重新计算。','value',()=>formulaOK()&&document.querySelector('#coach-b3').value.trim()==='35','请把 B3 改为 35，确认合计为 85。']]},
    agent:{surface:'<h3>任务草稿 · 不会发送</h3><label class="coach-field" data-coach-target="task">我希望完成什么<textarea id="coach-task" placeholder="例如：整理这份会议记录，列出三个待办事项"></textarea></label><label class="coach-switch" data-coach-target="approval"><span>修改或发送前，先让我确认</span><input id="coach-approval" type="checkbox" role="switch" aria-label="执行前确认"></label><label class="coach-field" data-coach-target="verification">我会怎样检查结果<textarea id="coach-verification" placeholder="例如：核对待办事项是否有负责人和截止时间"></textarea></label><p class="coach-local-note">本练习只检查草稿是否填写完整，不评价任务质量，也不会调用模型或执行任务。</p>',steps:[
      ['先说清想得到什么','写下一个任务，包括要处理的对象和想得到的结果。','例如：整理这份会议记录，列出三个待办事项。','task',()=>document.querySelector('#coach-task').value.trim().length>=12,'请再具体一点，至少写 12 个字符，说明对象和结果。'],
      ['保留自己的决定权','打开“修改或发送前，先让我确认”。','这是操作边界：先看计划，再决定是否执行。','approval',()=>document.querySelector('#coach-approval').checked,'请打开执行前确认开关。'],
      ['想好怎样验收','写下你会核对什么，而不是只看 AI 说“完成了”。','例如：核对每条待办是否有负责人和截止时间。','verification',()=>document.querySelector('#coach-verification').value.trim().length>=10&&document.querySelector('#coach-approval').checked&&document.querySelector('#coach-task').value.trim().length>=12,'请保留完整任务和执行前确认，并写下至少 10 个字符的检查项。']]}
  };
  function formulaOK(){return /^=SUM\(B1:B3\)$/i.test(document.querySelector('#coach-b4').value.replace(/\s/g,''));}
  function updatePreview(){
    if(course==='settings'){
      const on=document.querySelector('#coach-night').checked, strength=+document.querySelector('#coach-strength').value;
      document.querySelector('#coach-strength-value').textContent=strength+'%';
      document.querySelector('.coach-monitor').style.background=on?`hsl(38 65% ${98-strength*.18}%)`:'#f5f7fa';
    }else if(course==='excel'){
      const raw=document.querySelector('#coach-b3').value.trim();
      document.querySelector('#coach-result').textContent=formulaOK()&&raw!==''&&Number.isFinite(Number(raw))?'合计 '+(50+Number(raw))+' 分钟':'等待有效公式与数值';
    }
  }
  function render(reset=false){
    const root=document.querySelector('#le-coach');if(!root)return;
    if(reset){document.querySelector('#coach-surface').innerHTML=lessons[course].surface;updatePreview();}
    document.querySelectorAll('[data-coach-course]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.coachCourse===course)));
    const item=lessons[course].steps[step];
    document.querySelector('#coach-count').textContent=`第 ${step+1} 步，共 3 步`;
    document.querySelector('#coach-progress').value=step+(passed?1:0);
    document.querySelector('#coach-title').textContent=item[0];document.querySelector('#coach-body').textContent=item[1];document.querySelector('#coach-hint').textContent=item[2];
    document.querySelectorAll('[data-coach-target]').forEach(e=>e.classList.toggle('coach-target',e.dataset.coachTarget===item[3]));
    document.querySelector('#coach-check').hidden=passed;document.querySelector('#coach-next').hidden=!passed||step===2;
    root.classList.toggle('coach-complete',passed&&step===2);
  }
  document.addEventListener('click',event=>{
    const pick=event.target.closest('[data-coach-course]');
    if(pick){course=pick.dataset.coachCourse;step=0;passed=false;document.querySelector('#coach-feedback').textContent='';render(true);}
    if(event.target.closest('#coach-restart')){step=0;passed=false;document.querySelector('#coach-feedback').textContent='';render(true);}
    if(event.target.closest('#coach-check')){passed=lessons[course].steps[step][4]();document.querySelector('#coach-feedback').textContent=passed?(step===2?'练习完成。你已亲手完成这三个步骤。':'这一步完成了。准备好后，再继续。'):lessons[course].steps[step][5];render();}
    if(event.target.closest('#coach-next')&&passed&&step<2){step++;passed=false;document.querySelector('#coach-feedback').textContent='';document.querySelector('#le-coach details').open=false;render();document.querySelector('#coach-title').focus();}
  });
  document.addEventListener('input',event=>{if(event.target.closest('#coach-surface')){passed=false;document.querySelector('#coach-feedback').textContent='';updatePreview();render();}});
  const wait=setInterval(()=>{if(document.querySelector('#coach-surface')){clearInterval(wait);render(true);}},250);
})();
