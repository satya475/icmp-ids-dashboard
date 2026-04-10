/* bandwidth.js */
const api = url => fetch(url).then(r => r.json());
let bwChart=null, topChart=null, selIp=null, selName=null, currentTab='day';
const COLORS=['#3b82f6','#22c55e','#f59e0b','#ef4444','#a855f7','#06b6d4'];

function fmtBytes(b){
  if(b>=1e9)return (b/1e9).toFixed(2)+' GB';
  if(b>=1e6)return (b/1e6).toFixed(1)+' MB';
  if(b>=1e3)return (b/1e3).toFixed(1)+' KB';
  return b+' B';
}
function fmtRate(bps){
  if(bps>=1e6)return (bps/1e6).toFixed(1)+' MB/s';
  if(bps>=1e3)return (bps/1e3).toFixed(1)+' KB/s';
  return Math.round(bps)+' B/s';
}

async function startBW(){
  const r=await fetch('/api/bandwidth/start',{method:'POST'}).then(r=>r.json());
  if(r.ok) setBWRunning(true);
  else alert(r.msg || 'Failed to start capture');
}
async function stopBW(){
  const r=await fetch('/api/bandwidth/stop',{method:'POST'}).then(r=>r.json());
  if(r.ok)setBWRunning(false);
}
function setBWRunning(on){
  document.getElementById('btn-bw-start').disabled=on;
  document.getElementById('btn-bw-stop').disabled=!on;
  document.getElementById('bw-dot').className='dot '+(on?'dot-on':'dot-off');
  document.getElementById('bw-status-text').textContent=on
    ?'Capturing packets — updates every 5s':'Capture stopped';
}

async function updateLive(){
  const data=await api('/api/bandwidth/live');
  const tb=document.getElementById('bw-tbody');
  if(!data.length){
    tb.innerHTML='<tr><td colspan="4" class="empty">No traffic yet — start capture above</td></tr>';
    return;
  }
  const totalIn=data.reduce((s,d)=>s+(d.total_in||0),0);
  const totalOut=data.reduce((s,d)=>s+(d.total_out||0),0);
  const maxTotal=Math.max(...data.map(d=>(d.total_in||0)+(d.total_out||0)));
  document.getElementById('bw-devices').textContent=data.length;
  document.getElementById('bw-total-in').textContent=fmtRate(totalIn/5);
  document.getElementById('bw-total-out').textContent=fmtRate(totalOut/5);
  document.getElementById('bw-top').textContent=data[0]?.name||data[0]?.ip||'—';
  tb.innerHTML='';
  data.forEach(d=>{
    const total=(d.total_in||0)+(d.total_out||0);
    const barW=maxTotal>0?Math.round((total/maxTotal)*100):0;
    const tr=document.createElement('tr');
    tr.className='clickable-row'+(d.ip===selIp?' sel':'');
    tr.innerHTML=`<td style="font-weight:500">${d.name||d.ip}
      <span class="uptime-bar"><span class="uptime-fill" style="width:${barW}%;background:#3b82f6"></span></span></td>
      <td style="font-family:monospace;color:var(--muted)">${d.ip}</td>
      <td style="color:#22c55e">${fmtRate((d.total_in||0)/5)}</td>
      <td style="color:#f59e0b">${fmtRate((d.total_out||0)/5)}</td>`;
    tr.onclick=()=>selectDevice(d.ip,d.name||d.ip);
    tb.appendChild(tr);
  });
}

function initBWChart(){
  bwChart=new Chart(document.getElementById('bw-chart').getContext('2d'),{
    type:'line',data:{labels:[],datasets:[]},
    options:{responsive:true,maintainAspectRatio:false,animation:false,
      plugins:{legend:{display:true,labels:{color:'#64748b',font:{size:10},boxWidth:12}}},
      scales:{
        x:{ticks:{color:'#64748b',maxTicksLimit:6,font:{size:10}},grid:{color:'#1a1d27'}},
        y:{ticks:{color:'#64748b',font:{size:10}},grid:{color:'#1a1d27'},
           title:{display:true,text:'bytes/s',color:'#64748b',font:{size:10}}}
      }}
  });
}
async function selectDevice(ip,name){
  selIp=ip;selName=name;
  document.getElementById('chart-device-label').textContent=name;
  document.querySelectorAll('.clickable-row').forEach(r=>{
    r.classList.toggle('sel',r.cells[1]&&r.cells[1].textContent===ip);
  });
  const hist=await api('/api/bandwidth/history/'+ip);
  bwChart.data.labels=hist.map(h=>new Date(h.timestamp).toLocaleTimeString());
  bwChart.data.datasets=[
    {label:'Download',data:hist.map(h=>Math.round(h.rate_in||0)),
     borderColor:'#22c55e',backgroundColor:'#22c55e20',borderWidth:1.5,pointRadius:0,tension:0.3,fill:true},
    {label:'Upload',data:hist.map(h=>Math.round(h.rate_out||0)),
     borderColor:'#f59e0b',backgroundColor:'#f59e0b20',borderWidth:1.5,pointRadius:0,tension:0.3,fill:true}
  ];
  bwChart.update('none');
}

function fillTotalsTable(id,rows){
  const tb=document.getElementById(id);
  if(!rows.length){tb.innerHTML='<tr><td colspan="4" class="empty">No data yet</td></tr>';return;}
  tb.innerHTML=rows.slice(0,15).map(r=>`<tr>
    <td style="font-weight:500">${r.name||r.ip}</td>
    <td style="color:#22c55e">${fmtBytes(r.total_in||0)}</td>
    <td style="color:#f59e0b">${fmtBytes(r.total_out||0)}</td>
    <td>${fmtBytes((r.total_in||0)+(r.total_out||0))}</td>
  </tr>`).join('');
}

function initTopChart(){
  topChart=new Chart(document.getElementById('top-chart').getContext('2d'),{
    type:'bar',data:{labels:[],datasets:[]},
    options:{responsive:true,maintainAspectRatio:false,animation:false,
      indexAxis:'y',
      plugins:{legend:{display:true,labels:{color:'#64748b',font:{size:10},boxWidth:12}}},
      scales:{
        x:{ticks:{color:'#64748b',font:{size:10}},grid:{color:'#1a1d27'}},
        y:{ticks:{color:'#e2e8f0',font:{size:11}},grid:{color:'#1a1d27'}}
      }}
  });
}
function switchTab(tab){
  currentTab=tab;
  document.getElementById('tab-day').classList.toggle('on',tab==='day');
  document.getElementById('tab-week').classList.toggle('on',tab==='week');
  api('/api/bandwidth/totals').then(t=>updateTopChart(t));
}
function updateTopChart(totals){
  const rows=(currentTab==='day'?totals.daily:totals.weekly)||[];
  const top=rows.slice(0,10);
  topChart.data.labels=top.map(r=>r.name||r.ip);
  topChart.data.datasets=[
    {label:'Download',data:top.map(r=>r.total_in||0),backgroundColor:'#22c55e88',borderColor:'#22c55e',borderWidth:1},
    {label:'Upload',  data:top.map(r=>r.total_out||0),backgroundColor:'#f59e0b88',borderColor:'#f59e0b',borderWidth:1}
  ];
  topChart.update('none');
}

async function updateTotals(){
  const t=await api('/api/bandwidth/totals');
  fillTotalsTable('daily-tbody',t.daily||[]);
  fillTotalsTable('weekly-tbody',t.weekly||[]);
  updateTopChart(t);
}
async function refresh(){
  await updateLive();
  await updateTotals();
  if(selIp)selectDevice(selIp,selName);
  document.getElementById('last-update').textContent='Updated '+new Date().toLocaleTimeString();
}
initBWChart();initTopChart();
refresh();
setInterval(refresh,5000);
