/* dashboard.js */
const api = url => fetch(url).then(r => r.json());
let devices=[], topo={nodes:[],edges:[]}, hops={}, classifications={};
let selIp=null, rttChart=null, lossChart=null;
let activeChips={rtt:new Set(),loss:new Set()};
let logOffset=0, isRunning=false;
const SC={up:'#22c55e',down:'#ef4444',unknown:'#64748b',degraded:'#f59e0b'};
const COLORS=['#3b82f6','#22c55e','#f59e0b','#ef4444','#a855f7','#06b6d4','#f97316','#84cc16'];

// ── Network auto-detection ───────────────
let _lastGateway = null;

async function detectNetwork(){
  try{
    const info=await api('/api/network/info');
    const box  = document.getElementById('network-info-box');
    const input= document.getElementById('router-ip');

    if(info.connected && info.gateway){
      // Detect router change — auto-update everything
      if(_lastGateway && _lastGateway !== info.gateway){
        console.log('Router changed:', _lastGateway, '->', info.gateway);
        // Auto-fill new gateway
        input.value = info.gateway;
        clearIpError();
        // Show router change notification
        box.innerHTML=`
          <div style="color:var(--warn);font-weight:500;margin-bottom:4px">
            Router Changed
          </div>
          <div>New Gateway: <b style="color:var(--text)">${info.gateway}</b></div>
          <div>New Subnet: <b style="color:var(--text)">${info.subnet}</b></div>
          <div style="font-size:10px;color:var(--muted);margin-top:4px">
            Restarting monitor for new network...
          </div>`;
        // Auto-restart monitor for new router
        if(isRunning){
          await stopMonitor();
          await new Promise(r=>setTimeout(r,2000));
          await startMonitor();
        }
      }

      _lastGateway = info.gateway;

      // Auto-fill if empty
      if(!input.value) input.value=info.gateway;
      input.placeholder=info.gateway;

      const changed = info.gateway_changed;
      box.innerHTML=`
        <div style="color:var(--up);font-weight:500;margin-bottom:4px">Connected</div>
        <div>Gateway: <b style="color:var(--text)">${info.gateway}</b></div>
        <div>My IP: <b style="color:var(--text)">${info.my_ip}</b></div>
        <div>Subnet: <b style="color:var(--text)">${info.subnet}</b></div>
        <div style="color:var(--muted);font-size:10px;margin-top:2px">${info.adapter||''}</div>`;
    } else {
      _lastGateway = null;
      box.innerHTML=`
        <div style="color:var(--down);font-weight:500">Not connected</div>
        <div style="font-size:11px;margin-top:4px">
          Connect to Wi-Fi or ethernet first.
        </div>`;
      input.placeholder='Not connected to any network';
    }
  }catch(e){
    document.getElementById('network-info-box').textContent='Could not detect network.';
  }
}

function showIpError(msg, suggestedIp=null){
  const el=document.getElementById('ip-error');
  el.style.display='block';
  el.innerHTML=msg+(suggestedIp
    ?` <a href="#" onclick="useIp('${suggestedIp}');return false"
        style="color:var(--blue);margin-left:6px">Use ${suggestedIp}</a>`:'');
  document.getElementById('ip-warning').style.display='none';
}

function showIpWarning(msg){
  const el=document.getElementById('ip-warning');
  el.style.display='block';
  el.textContent=msg;
  document.getElementById('ip-error').style.display='none';
}

function clearIpError(){
  document.getElementById('ip-error').style.display='none';
  document.getElementById('ip-warning').style.display='none';
}

function useIp(ip){
  document.getElementById('router-ip').value=ip;
  clearIpError();
}

// ── Control ──────────────────────────────
async function startMonitor(){
  const ip=document.getElementById('router-ip').value.trim();
  clearIpError();

  if(!ip){
    showIpError('Please enter your router IP address.');
    return;
  }

  // Validate against current network before starting
  const validation=await fetch('/api/network/validate',{
    method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({ip})
  }).then(r=>r.json());

  if(!validation.ok){
    showIpError(validation.message, validation.suggested_ip);
    return;
  }
  if(validation.warning){
    showIpWarning(validation.message);
  }

  const r=await fetch('/api/control/start',{
    method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({router_ip:ip})
  }).then(r=>r.json());

  if(r.ok){
    isRunning=true;
    setRunning(true);
    appendLog({ts:new Date().toLocaleTimeString(),src:'system',msg:r.msg});
    if(r.warning) showIpWarning(r.warning);
  } else {
    showIpError(r.msg, r.suggested_ip);
  }
}
async function stopMonitor(){
  const r=await fetch('/api/control/stop',{method:'POST'}).then(r=>r.json());
  if(r.ok){isRunning=false;setRunning(false);}
}
function setRunning(on){
  document.getElementById('btn-start').disabled=on;
  document.getElementById('btn-stop').disabled=!on;
  setBadge('discovery',false);setBadge('probe',false);setBadge('traceroute',false);
}
function setBadge(name,running){
  const el=document.getElementById('badge-'+name);
  if(!el)return;
  el.textContent=name.charAt(0).toUpperCase()+name.slice(1)+': '+(running?'running':'stopped');
  el.className='proc-badge '+(running?'pb-running':'pb-stopped');
}
async function pollLogs(){
  try{
    const d=await api('/api/control/logs?since='+logOffset);
    d.logs.forEach(appendLog);
    logOffset=d.total;
    const st=await api('/api/control/status');
    isRunning=st.running;
    setBadge('discovery',  st.processes.discovery);
    setBadge('probe',      st.processes.probe);
    setBadge('traceroute', st.processes.traceroute);
    document.getElementById('btn-start').disabled=st.running;
    document.getElementById('btn-stop').disabled=!st.running;
  }catch(e){}
}
function appendLog(line){
  const win=document.getElementById('log-window');
  if(!win)return;
  const div=document.createElement('div');
  div.className='log-line';
  div.innerHTML=`<span class="log-ts">${line.ts}</span>`+
    `<span class="log-src-${line.src||'system'}">${(line.src||'system').padEnd(12)}</span>`+
    `<span class="log-msg">${line.msg}</span>`;
  win.appendChild(div);
  win.scrollTop=win.scrollHeight;
  while(win.children.length>200)win.removeChild(win.firstChild);
}

// ── Stats ────────────────────────────────
async function updateStats(){
  const s=await api('/api/stats');
  document.getElementById('s-total').textContent=s.total;
  document.getElementById('s-up').textContent=s.up;
  document.getElementById('s-down').textContent=s.down;
  document.getElementById('s-unknown').textContent=s.unknown;
  document.getElementById('s-rtt').textContent=s.avg_rtt?s.avg_rtt+' ms':'—';
  document.getElementById('last-update').textContent='Updated '+new Date().toLocaleTimeString();
  // Update network badge
  try{
    const net=await api('/api/network/info');
    const badge=document.getElementById('net-badge');
    if(badge&&net.gateway){
      badge.textContent=net.gateway+' ('+net.subnet+')';
      badge.title='Current router: '+net.gateway;
    }
  }catch(e){}
}

// ── Devices ──────────────────────────────
async function updateDevices(){
  devices=await api('/api/devices');
  hops   =await api('/api/hops');
  classifications=await api('/api/classify');
  const tb=document.getElementById('dev-tbody');
  tb.innerHTML='';
  for(const d of devices){
    const st=d.is_alive===1?'up':d.is_alive===0?'down':'unknown';
    const rtt   = d.rtt_med_ms ? d.rtt_med_ms.toFixed(1)
                : d.rtt_avg_ms ? d.rtt_avg_ms.toFixed(1) : '—';
    const jitter= d.jitter_ms  ? d.jitter_ms.toFixed(1)+'ms' : '—';
    const loss  = d.packet_loss!=null?(d.packet_loss*100).toFixed(0)+'%':'—';
    const qualityColors={'excellent':'#22c55e','good':'#22c55e','fair':'#f59e0b',
      'poor':'#ef4444','bad':'#ef4444','no-reply':'#64748b'};
    const qColor = qualityColors[d.quality]||'#64748b';
    const quality= d.quality
      ? `<span style="color:${qColor};font-size:10px;font-weight:600">${d.quality}</span>`
      : '<span class="muted">—</span>';
    const seen=d.last_seen?new Date(d.last_seen).toLocaleTimeString():'—';
    const fseen=d.first_seen?new Date(d.first_seen).toLocaleDateString():'—';
    const mac = d.mac && d.mac !== 'unknown' && d.mac
      ? `<span style="font-family:monospace;font-size:10px;color:var(--muted)">${d.mac}</span>`
      : '<span class="muted">—</span>';
    const cls    = classifications[d.ip];
    const devType= cls
      ? `<span style="display:inline-flex;align-items:center;gap:4px;
           padding:1px 8px;border-radius:20px;font-size:10px;font-weight:600;
           background:${cls.meta.color}22;color:${cls.meta.color};
           border:1px solid ${cls.meta.color}44"
           title="${Math.round(cls.confidence)}% confidence">
           ${cls.meta.label}
         </span>`
      : '<span class="muted" style="font-size:10px">learning...</span>';
    const uptime=d.uptime!=null
      ?`${d.uptime}%<span class="uptime-bar"><span class="uptime-fill" style="width:${d.uptime}%;background:${d.uptime>90?'#22c55e':d.uptime>50?'#f59e0b':'#ef4444'}"></span></span>`
      :'<span class="muted">—</span>';

    // Build hop path string
    const deviceHops  = hops[d.ip] || [];
    const validHops   = deviceHops.filter(h=>h.hop_ip);
    const hopCount    = validHops.length;
    const hopPath     = validHops.map(h=>h.hop_ip).join(' → ');
    let hopsCell;
    if(deviceHops.length === 0){
      hopsCell = '<span class="muted" style="font-size:10px">tracing...</span>';
    } else if(hopCount === 0){
      hopsCell = '<span class="muted" style="font-size:10px">no reply</span>';
    } else if(hopCount === 1 && validHops[0].hop_ip === d.ip){
      hopsCell = '<span style="font-size:10px;color:var(--up)">Direct</span>';
    } else {
      hopsCell = `<span style="font-size:10px;color:var(--muted)">${hopCount} hop${hopCount>1?'s':''}</span>
        <div style="font-size:10px;color:var(--muted);font-family:monospace;margin-top:2px;
          max-width:180px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap"
          title="${hopPath}">${hopPath}</div>`;
    }

    const tr=document.createElement('tr');
    tr.className='clickable-row';
    if(d.ip===selIp)tr.classList.add('sel');
    tr.innerHTML=`
      <td><span class="badge b-${st}">${st.toUpperCase()}</span></td>
      <td style="font-weight:500;cursor:pointer" title="Click to rename"
          onclick="renameDevice('${d.ip}','${d.name}',event)">
        ${d.name}
        <span style="font-size:10px;color:var(--muted);margin-left:4px">✎</span>
      </td>
      <td style="font-family:monospace;color:var(--muted);font-size:11px">${d.ip}</td>
      <td>${mac}</td>
      <td>${devType}</td>
      <td style="font-weight:500">${rtt}</td>
      <td style="color:var(--muted);font-size:11px">${jitter}</td>
      <td>${loss}</td>
      <td>${quality}</td>
      <td>${hopsCell}</td>
      <td style="color:var(--muted);font-size:11px">${seen}</td>`;
    tr.onclick=()=>selectDevice(d.ip,d.name);
    tb.appendChild(tr);
  }
  updateChips();
}

// ── Topology ─────────────────────────────
async function updateTopology(){
  topo=await api('/api/topology');
  drawTopology();
}

function drawTopology(){
  const svg=document.getElementById('topo-svg');
  const W=svg.clientWidth||700,H=svg.clientHeight||360;
  const {nodes,edges}=topo;
  if(!nodes.length){
    svg.innerHTML='<text x="50%" y="50%" text-anchor="middle" fill="#64748b" font-size="13">No devices yet</text>';
    return;
  }

  const router=nodes.find(n=>n.is_router)||nodes[0];
  const others=nodes.filter(n=>n.id!==router.id);
  const cx=W/2,cy=H/2,R=Math.min(W,H)*0.38;
  const pos={[router.id]:{x:cx,y:cy}};
  others.forEach((n,i)=>{
    const a=(2*Math.PI*i/Math.max(others.length,1))-Math.PI/2;
    pos[n.id]={x:cx+R*Math.cos(a),y:cy+R*Math.sin(a)};
  });

  let html='';

  // Draw edges — if hops exist, show intermediate points
  edges.forEach(e=>{
    const a=pos[e.from],b=pos[e.to];
    if(!a||!b)return;
    const nd    =nodes.find(n=>n.id===e.to);
    const c     =SC[nd?.status]||SC.unknown;
    const devHops=hops[e.to]||[];

    if(devHops.length<=1){
      // Simple direct line
      html+=`<line x1="${a.x}" y1="${a.y}" x2="${b.x}" y2="${b.y}"
        stroke="${c}44" stroke-width="1.5"/>`;
    } else {
      // Draw hop points along the path
      const validHops=devHops.filter(h=>h.hop_ip);
      validHops.forEach((h,i)=>{
        // Interpolate position along the line
        const t=(i+1)/(validHops.length+1);
        const hx=a.x+(b.x-a.x)*t;
        const hy=a.y+(b.y-a.y)*t;
        // Draw small hop dot
        html+=`<circle cx="${hx}" cy="${hy}" r="4"
          fill="#1a1d27" stroke="#f59e0b" stroke-width="1.5"
          title="${h.hop_ip}"/>`;
        // Hop IP label
        html+=`<text x="${hx+8}" y="${hy-6}" font-size="9" fill="#f59e0b"
          font-family="monospace">${h.hop_ip}</text>`;
      });
      // Draw the line itself
      html+=`<line x1="${a.x}" y1="${a.y}" x2="${b.x}" y2="${b.y}"
        stroke="${c}33" stroke-width="1" stroke-dasharray="3 3"/>`;
    }
  });

  // Draw nodes
  nodes.forEach(n=>{
    const p=pos[n.id];if(!p)return;
    const c=SC[n.status]||SC.unknown,r=n.is_router?28:20;
    const lbl=n.label.length>11?n.label.slice(0,10)+'…':n.label;
    const rtt=n.rtt?n.rtt+'ms':'—';
    const up=n.uptime!=null?n.uptime+'%':'';
    const enc=JSON.stringify({
      name:n.label,ip:n.ip,vendor:n.vendor,mac:n.mac,
      rtt:n.rtt,loss:n.loss,uptime:n.uptime,status:n.status,
      hops:(hops[n.id]||[]).length
    }).replace(/"/g,'&quot;');
    html+=`<g style="cursor:pointer"
        onclick="selectDevice('${n.id}','${n.label}')"
        onmouseenter="showTip(event,'${enc}')"
        onmouseleave="hideTip()">
      <circle cx="${p.x}" cy="${p.y}" r="${r}"
        fill="${c}18" stroke="${c}" stroke-width="1.5"/>
      ${n.is_router?`<circle cx="${p.x}" cy="${p.y}" r="${r+5}"
        fill="none" stroke="${c}" stroke-width="0.5"
        stroke-dasharray="3 3" opacity="0.5"/>`:''}
      <text x="${p.x}" y="${p.y+4}" text-anchor="middle"
        font-size="10" fill="${c}" font-weight="600">${lbl}</text>
      <text x="${p.x}" y="${p.y+r+13}" text-anchor="middle"
        font-size="9" fill="#64748b">${rtt}</text>
      ${up?`<text x="${p.x}" y="${p.y+r+23}" text-anchor="middle"
        font-size="9" fill="#64748b">${up}</text>`:''}
    </g>`;
  });

  svg.innerHTML=html;
}

// ── Tooltip ──────────────────────────────
function showTip(e,enc){
  const d=JSON.parse(enc.replace(/&quot;/g,'"'));
  document.getElementById('tt-name').textContent=d.name;
  document.getElementById('tt-body').innerHTML=
    `<div>IP: <b>${d.ip}</b></div>`+
    `<div>Vendor: <b>${d.vendor||'—'}</b></div>`+
    `<div>MAC: <b>${d.mac||'—'}</b></div>`+
    `<div>RTT: <b>${d.rtt?d.rtt+' ms':'—'}</b></div>`+
    `<div>Loss: <b>${d.loss!=null?d.loss+'%':'—'}</b></div>`+
    `<div>Uptime: <b>${d.uptime!=null?d.uptime+'%':'—'}</b></div>`+
    `<div>Hops: <b>${d.hops||'—'}</b></div>`+
    `<div>Status: <b style="color:${SC[d.status]||SC.unknown}">${(d.status||'unknown').toUpperCase()}</b></div>`;
  const tip=document.getElementById('tooltip');
  tip.style.left=(e.clientX+14)+'px';
  tip.style.top=(e.clientY-10)+'px';
  tip.classList.add('show');
}
function hideTip(){document.getElementById('tooltip').classList.remove('show');}

// ── Alerts ───────────────────────────────
async function updateAlerts(){
  const alerts=await api('/api/alerts');
  const el=document.getElementById('alert-list');
  if(!alerts.length){el.innerHTML='<div class="empty">No alerts yet</div>';return;}
  el.innerHTML=alerts.slice(0,30).map(a=>{
    const st=a.new_status.toLowerCase();
    const dc=st==='up'?'d-up':st==='down'?'d-down':st==='degraded'?'d-deg':'d-unk';
    return `<div class="a-item"><div class="a-dot ${dc}"></div><div>
      <div class="a-name">${a.name} → <span style="color:${SC[st]||SC.unknown}">${a.new_status}</span></div>
      <div class="a-sub">${a.host||''} · was ${a.old_status||'—'} · ${new Date(a.timestamp).toLocaleTimeString()}</div>
    </div></div>`;
  }).join('');
}

// ── Charts ───────────────────────────────
function mkChart(id,yLabel){
  return new Chart(document.getElementById(id).getContext('2d'),{
    type:'line',data:{labels:[],datasets:[]},
    options:{responsive:true,maintainAspectRatio:false,animation:false,
      plugins:{legend:{display:false}},
      scales:{
        x:{ticks:{color:'#64748b',maxTicksLimit:6,font:{size:10}},grid:{color:'#1a1d27'}},
        y:{ticks:{color:'#64748b',font:{size:10}},grid:{color:'#1a1d27'},
           title:{display:true,text:yLabel,color:'#64748b',font:{size:10}}}
      }}
  });
}
async function loadChart(ip,name,chart,field,scale){
  const hist=await api('/api/history/'+ip);
  const labels=hist.map(h=>new Date(h.timestamp).toLocaleTimeString());
  const vals=hist.map(h=>h[field]!=null?+(h[field]*scale).toFixed(2):null);
  const idx=chart.data.datasets.findIndex(d=>d.label===name);
  const color=COLORS[Math.max(0,idx<0?chart.data.datasets.length:idx)%COLORS.length];
  if(idx>=0)chart.data.datasets[idx].data=vals;
  else chart.data.datasets.push({label:name,data:vals,borderColor:color,
    backgroundColor:color+'20',borderWidth:1.5,pointRadius:0,tension:0.3,fill:true});
  chart.data.labels=labels;chart.update('none');
}
function removeDataset(name,chart){
  const i=chart.data.datasets.findIndex(d=>d.label===name);
  if(i>=0){chart.data.datasets.splice(i,1);chart.update('none');}
}
function updateChips(){
  ['rtt','loss'].forEach(type=>{
    const el=document.getElementById(type+'-chips');
    if(!el)return;
    el.innerHTML='';
    devices.forEach(d=>{
      const chip=document.createElement('span');
      chip.className='chip'+(activeChips[type].has(d.ip)?' on':'');
      chip.textContent=d.name;
      chip.onclick=()=>toggleChip(d.ip,d.name,type,chip);
      el.appendChild(chip);
    });
  });
}
function toggleChip(ip,name,type,chip){
  const chart=type==='rtt'?rttChart:lossChart;
  const field=type==='rtt'?'rtt_avg_ms':'packet_loss';
  if(activeChips[type].has(ip)){
    activeChips[type].delete(ip);chip.classList.remove('on');removeDataset(name,chart);
  }else{
    activeChips[type].add(ip);chip.classList.add('on');
    loadChart(ip,name,chart,field,type==='rtt'?1:100);
  }
}
function selectDevice(ip,name){
  selIp=ip;
  ['rtt','loss'].forEach(type=>{
    if(!activeChips[type].has(ip)){
      activeChips[type].add(ip);
      loadChart(ip,name,type==='rtt'?rttChart:lossChart,
        type==='rtt'?'rtt_avg_ms':'packet_loss',type==='rtt'?1:100);
    }
  });
  updateChips();
  document.querySelectorAll('.clickable-row').forEach(r=>{
    r.classList.toggle('sel',r.cells[2]&&r.cells[2].textContent===ip);
  });
}

// ── Device rename ───────────────────────────
async function renameDevice(ip, currentName, event){
  event.stopPropagation();
  const newName = prompt('Enter new name for ' + ip + ':', currentName);
  if(!newName || newName === currentName) return;
  const r = await fetch('/api/device/rename', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({ip, name: newName})
  }).then(r=>r.json());
  if(r.ok){
    refresh();
  } else {
    alert('Failed: ' + r.msg);
  }
}

// ── Activity feed ───────────────────────────
async function updateActivity(){
  const events = await api('/api/activity');
  const el     = document.getElementById('activity-feed');
  if(!el) return;
  if(!events.length){
    el.innerHTML='<div style="color:var(--muted);font-size:12px;padding:8px 16px">No recent activity</div>';
    return;
  }
  el.innerHTML = events.map(e=>{
    const ts  = new Date(e.timestamp).toLocaleTimeString();
    const dot = `<span style="width:7px;height:7px;border-radius:50%;
      background:${e.color};display:inline-block;flex-shrink:0;margin-top:4px"></span>`;
    return `<div style="display:flex;align-items:flex-start;gap:10px;
      padding:6px 16px;border-bottom:1px solid var(--border)">
      ${dot}
      <div style="min-width:0">
        <div style="font-size:12px;font-weight:500;color:${e.color}">${e.title}</div>
        <div style="font-size:10px;color:var(--muted);margin-top:1px">
          ${e.detail} · ${ts}
        </div>
      </div>
    </div>`;
  }).join('');
}

// ── Refresh ──────────────────────────────
async function refresh(){
  await Promise.all([updateStats(),updateDevices(),updateTopology(),updateAlerts(),pollLogs(),updateActivity()]);
  for(const ip of activeChips.rtt){
    const d=devices.find(x=>x.ip===ip);
    if(d)loadChart(ip,d.name,rttChart,'rtt_avg_ms',1);
  }
  for(const ip of activeChips.loss){
    const d=devices.find(x=>x.ip===ip);
    if(d)loadChart(ip,d.name,lossChart,'packet_loss',100);
  }
}
rttChart=mkChart('rtt-chart','ms');
lossChart=mkChart('loss-chart','%');
detectNetwork();
refresh();
setInterval(refresh,5000);
setInterval(detectNetwork,30000);
window.addEventListener('resize',drawTopology);
