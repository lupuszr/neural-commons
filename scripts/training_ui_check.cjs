// Exercise recorded training progress without a browser, participant or model.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {test} = require('node:test');
class Element {
  constructor(tag, text, className) { this.tag=tag;this.textContent=text??'';this.className=className;this.children=[];this.attributes={};this.style={}; }
  append(...items) { this.children.push(...items); }
  setAttribute(key,value) { this.attributes[key]=String(value); }
}
const source=fs.readFileSync(path.join(__dirname,'../web/app.js'),'utf8');
const context=vm.createContext({
  node:(...args)=>new Element(...args),
  document:{createElementNS:(_ns,tag)=>new Element(tag)},
  researchStatus:value=>value==='awaiting_review'?'Awaiting review':value,
});
vm.runInContext(source.slice(source.indexOf('function researchTrainingEpochs('),source.indexOf('function renderResearchExperiment(')),context);
const event=training_progress=>({event:{data:{training_progress}}});
const progress=(epoch,extra={})=>({epoch,epochs:20,class_loss:1/epoch,...extra});
const descendants=root=>[root,...root.children.flatMap(descendants)];
const text=root=>descendants(root).map(x=>x.textContent).join(' ');

test('recorded epochs are ordered, corrected by later events and validated',()=>{
  const epochs=context.researchTrainingEpochs({events:[
    event(progress(2)),event(progress(1)),event(progress(2,{class_loss:.2})),
    event(progress(0)),event(progress(21)),event(progress(1.5)),
    event(progress(3,{class_loss:NaN})),event(progress(3,{box_loss:-1})),
    event(progress(3,{dfl_loss:Infinity})),event(progress(3,{anchor_penalty:NaN})),{},
  ]});
  assert.deepEqual(Array.from(epochs,e=>[e.epoch,e.class_loss]),[[1,1],[2,.2]]);
});

test('partial fine-tuning plots only the measured loss with its actual definition',()=>{
  const panel=context.researchTraining({status:'awaiting_review',definition:{label:'Dog-head tuning'},
    events:[event(progress(1,{loss_definition:'Weighted dog BCE, frozen backbone'}))]});
  assert.match(text(panel),/Epoch 1\/20 · Awaiting review/);
  assert.match(text(panel),/Weighted BCE: 1.0000/);
  assert.match(text(panel),/Weighted dog BCE, frozen backbone/);
  assert.doesNotMatch(text(panel),/Box:|DFL:|training worker running/);
  const nodes=descendants(panel),svg=nodes.find(n=>n.tag==='svg');
  assert.match(svg.attributes['aria-label'],/epoch 1 to 1.*Weighted BCE/);
  assert.equal(nodes.filter(n=>n.tag==='path').length,1);
  assert.equal(nodes.filter(n=>n.tag==='circle').length,1);
  assert.doesNotMatch(JSON.stringify(svg),/NaN|Infinity/);
});

test('an append-only correction removes a spurious epoch from the plot',()=>{
  const epochs=context.researchTrainingEpochs({events:[
    event(progress(1)),event(progress(2)),event({epoch:2,valid:false}),
  ]});
  assert.deepEqual(Array.from(epochs,e=>e.epoch),[1]);
});

test('active full training displays all recorded losses and epoch progress',()=>{
  const panel=context.researchTraining({status:'running',definition:{label:'Full tuning'},events:[
    event(progress(1,{box_loss:2,dfl_loss:3})),event(progress(2,{box_loss:1,dfl_loss:2,
      loss_definition:'YOLO26 supervised detection loss on both native heads'})),
  ]});
  assert.match(text(panel),/Epoch 2\/20 · training worker running/);
  assert.match(text(panel),/Class: 0.5000/);
  assert.doesNotMatch(text(panel),/Weighted BCE/);
  const nodes=descendants(panel),bar=nodes.find(n=>n.tag==='progress');
  assert.equal(bar.value,2);assert.equal(bar.max,20);
  assert.equal(nodes.filter(n=>n.tag==='path').length,3);
  assert.match(text(panel),/Final evaluation is separate/);
});

test('an idle round without completed epochs does not claim training is running',()=>{
  const panel=context.researchTraining({status:'failed',definition:{label:'Failed tuning'},events:[]});
  assert.match(text(panel),/No completed epochs recorded/);
  assert.doesNotMatch(text(panel),/training worker running/);
});

test('anchored fine-tuning plots its measured regularizer separately',()=>{
  const panel=context.researchTraining({status:'running',definition:{label:'Anchored tuning'},events:[
    event(progress(1,{box_loss:1.1,anchor_penalty:.2})),
    event(progress(2,{box_loss:.9,anchor_penalty:.14})),
  ]});
  assert.match(text(panel),/Anchor \(epoch end\): 0.1400/);
  const nodes=descendants(panel);
  assert.equal(nodes.filter(n=>n.tag==='path').length,3);
  assert.match(nodes.find(n=>n.tag==='svg').attributes['aria-label'],/Anchor \(epoch end\) 0.1400/);
});

test('validation mAP uses its own percent scale and never claims a loss decrease meets the target',()=>{
  const panel=context.researchTraining({status:'running',definition:{label:'Detection training'},events:[
    event(progress(1,{validation_map50_95:.46,target_map50_95:.8})),
    event(progress(2,{validation_map50_95:.42,target_map50_95:.8})),
  ]});
  assert.match(text(panel),/Latest: 42.0% · Best in this round: 46.0% · Target: 80.0% · not reached/);
  const svgs=descendants(panel).filter(n=>n.tag==='svg');
  assert.equal(svgs.length,2);
  assert.match(svgs[1].attributes['aria-label'],/Separate from training loss and final evaluation/);
  assert.equal(descendants(svgs[1]).filter(n=>n.tag==='line').length,1);
  assert.doesNotMatch(JSON.stringify(panel),/NaN|Infinity/);
});

test('validation target can be reached and invalid percent values cannot overwrite recorded epochs',()=>{
  const events=[event(progress(1,{validation_map50_95:.81,target_map50_95:.8})),
    event(progress(1,{validation_map50_95:81})),event(progress(2,{target_map50_95:Infinity})),
    event(progress(3,{validation_map50_95:-.1}))];
  const panel=context.researchTraining({status:'awaiting_review',definition:{label:'Detection training'},events});
  assert.match(text(panel),/Latest: 81.0%.*Target: 80.0% · reached/);
  assert.equal(context.researchTrainingEpochs({events}).length,1);
});
