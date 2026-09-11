'use strict';
const $ = id => document.getElementById(id);
const labels = {passed:'통과', failed:'실패', completed:'완료', running:'실행 중'};
const chain = [[0,'Conv'],[1,'Pool'],[2,'Conv'],[3,'Pool'],[4,'Conv'],[5,'Pool'],[6,'Conv'],[7,'Pool'],[8,'Conv'],[9,'Pool'],[10,'Conv'],[11,'Pool'],[12,'Conv'],[13,'Conv'],[14,'Conv'],[15,'Conv'],[17,'Route'],[18,'Conv'],[19,'Up'],[20,'Route'],[21,'Conv'],[22,'Conv']];
let token = location.hash.slice(1) || sessionStorage.getItem('kr260-control') || '';
if (location.hash) history.replaceState(null, '', location.pathname);
if (token) sessionStorage.setItem('kr260-control', token);
$('token').value = token;
let latest = null, requestPending = false, frameUrl = '';
for (const [layer, kind] of chain) { const box=document.createElement('div'); box.id='op-'+layer; box.className='op'; box.textContent=String(layer).padStart(2,'0'); const sub=document.createElement('small'); sub.textContent=kind; box.append(sub); $('op-grid').append(box); }
function metricState(id, status, empty='미실행') { const el=$(id); el.textContent=labels[status]||empty; el.className='metric-value '+(status||''); }
function note(text, error=false) { $('notice').textContent=text; $('notice').className='notice'+(error?' error':''); }
async function cameraImage(show) { $('camera-frame').classList.toggle('visible', show); $('camera-placeholder').hidden=show; if(!show||!token)return; try{const res=await fetch('/api/camera.jpg',{headers:{'X-Control-Token':token}});if(!res.ok)return;const next=URL.createObjectURL(await res.blob());$('camera-frame').src=next;if(frameUrl)URL.revokeObjectURL(frameUrl);frameUrl=next;}catch(e){} }
function render(s) {
  latest=s; $('connection').textContent='● 보드 연결됨';
  $('fpga-state').textContent=s.fpga_ready?'로딩 완료':'로딩 필요'; $('fpga-state').className='metric-value '+(s.fpga_ready?'passed':'');
  $('fpga-detail').textContent=s.fpga_ready?`4-IP · ${(Number(s.clock_hz)/1e6).toFixed(1)} MHz`:`FPGA manager: ${s.manager_state||'정보 없음'}`;
  const full=s.full; metricState('full-state', full?.status); $('full-detail').textContent=full?`${full.ops.length} / 22 연산 · ${full.boot_id===s.boot_id?'현재 부팅 결과':'이전 부팅 결과'}`:'22개 하드웨어 연산';
  $('temperature').textContent=s.temperature_c===null?'—':Number(s.temperature_c).toFixed(1)+' °C';
  const report=s.report, checks=report?.checks||{};
  for (const index of [0,15,22]) { const c=checks[index]; const el=$('check-'+index); el.className='check-result '+(c?.status||''); el.replaceChildren(document.createTextNode(c?labels[c.status]:'미실행')); if(c){const sub=document.createElement('small'); sub.textContent=`불일치 ${c.mismatches.toLocaleString()} / ${c.bytes.toLocaleString()}`; el.append(sub);} }
  $('camera-device').textContent=s.cameras.length?'카메라 연결됨 · '+s.cameras.join(', '):'카메라 미연결'; $('board-info').textContent=`${s.host} · ${s.kernel}`; $('run-time').textContent=report?.finished_at?new Date(report.finished_at).toLocaleString('ko-KR'):'실행 대기'; $('console').textContent=s.log||'실행 대기 중';
  for(const [layer] of chain) $('op-'+layer).className='op'; const rows=report?.ops||[]; $('op-count').textContent=`${rows.filter(x=>x.duration_ms!==undefined).length} / ${report?.mode==='layer0'?1:22}`; $('op-table').replaceChildren();
  for(const row of rows){$('op-'+row.layer).className='op '+row.status; const tr=document.createElement('tr'); for(const value of [String(row.layer).padStart(2,'0'),row.kind,labels[row.status]||row.status,row.duration_ms?.toFixed(3)||'—',row.ap_ctrl||'—']){const td=document.createElement('td');td.textContent=value;tr.append(td);}$('op-table').append(tr);} if(!rows.length){const tr=document.createElement('tr'),td=document.createElement('td');td.colSpan=5;td.textContent='아직 실행 결과가 없습니다.';tr.append(td);$('op-table').append(tr);}
  const camera=s.camera||{}, live=s.job.busy&&s.job.action==='camera';
  $('live-state').textContent=(camera.status||'stopped').toUpperCase(); $('live-state').className='pill '+(camera.status==='running'?'live':'neutral'); $('camera-state').textContent=camera.status==='running'?`FPGA 추론 실행 중 · ${camera.processed_frames||0} 프레임`:camera.status==='failed'?(camera.error||'실행 실패'):'실시간 스트리밍 대기 중';
  $('capture-fps').textContent=camera.capture_fps!==undefined?Number(camera.capture_fps).toFixed(1):'—'; $('inference-fps').textContent=camera.inference_fps!==undefined?Number(camera.inference_fps).toFixed(2):'—'; $('latency-detail').textContent=camera.inference_ms!==undefined?`${Number(camera.inference_ms).toFixed(1)} ms · FPGA IP 합계 ${Number(camera.accelerator_ms).toFixed(1)} ms`:'실시간 입력 대기 중';
  $('processed').textContent=camera.processed_frames||0; $('dropped').textContent=camera.dropped_frames||0; const detections=camera.detections||[]; $('detection-count').textContent=detections.length; $('detection-list').replaceChildren();
  if(detections.length){for(const d of detections){const row=document.createElement('div');row.textContent=`${d.class} · ${(d.score*100).toFixed(1)}%`; $('detection-list').append(row);}} else $('detection-list').textContent='검출 결과 없음';
  cameraImage(camera.status==='running'&&camera.processed_frames>0); $('camera-start').disabled=s.job.busy||requestPending||!s.fpga_ready||!s.cameras.length; $('camera-stop').disabled=!live||requestPending;
  document.querySelectorAll('[data-action]').forEach(b=>b.disabled=s.job.busy||requestPending||(b.dataset.action!=='load'&&!s.fpga_ready));
  if(live) note('실제 카메라 프레임을 FPGA 전체 체인으로 추론하고 있습니다. 최신 프레임만 처리합니다.'); else if(s.job.busy) note(`${s.job.action==='load'?'FPGA 로딩':'하드웨어 검증'} 진행 중입니다. 결과와 로그가 자동으로 갱신됩니다.`); else if(s.job.returncode!==null&&s.job.returncode!==0) note(camera.status==='failed'?(camera.error||'카메라 실행 실패'):(report?.error||'실행에 실패했습니다. 로그를 확인하세요.'),true); else if(full?.status==='passed') note('전체 체인 검증 통과 · Layer 0과 두 출력 헤드가 정답 데이터와 바이트 단위로 일치합니다.'); else note(s.fpga_ready?'FPGA 로딩 완료. 정답 검증 또는 카메라 추론을 시작할 수 있습니다.':'FPGA 로딩을 먼저 실행하세요.');
}
async function refresh(){try{const res=await fetch('/api/status');if(!res.ok)throw Error('HTTP '+res.status);render(await res.json());}catch(e){$('connection').textContent='● 연결 끊김';note('보드에 연결할 수 없습니다. 전원과 네트워크를 확인하세요.',true);}}
async function act(path){if(!token){note('실행 제어 키가 필요합니다. 제공된 제어 링크로 접속하거나 키를 입력하세요.',true);document.querySelector('details').open=true;$('token').focus();return;}requestPending=true;try{const res=await fetch(path,{method:'POST',headers:{'X-Control-Token':token}});const data=await res.json();if(!res.ok)throw Error(data.error);await refresh();}catch(e){note(e.message,true);}finally{requestPending=false;}}
document.querySelectorAll('[data-action]').forEach(button=>button.addEventListener('click',()=>act('/api/'+button.dataset.action)));
$('camera-start').addEventListener('click',()=>act('/api/camera/start')); $('camera-stop').addEventListener('click',()=>act('/api/camera/stop'));
$('save-token').addEventListener('click',()=>{token=$('token').value.trim();sessionStorage.setItem('kr260-control',token);note('제어 키를 저장했습니다.');});
$('download').addEventListener('click',()=>{if(!latest)return;const blob=new Blob([JSON.stringify(latest,null,2)],{type:'application/json'});const url=URL.createObjectURL(blob);const a=document.createElement('a');a.href=url;a.download='kr260-verification-'+new Date().toISOString().replaceAll(':','-')+'.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);});
refresh(); setInterval(refresh,2000);
