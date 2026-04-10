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
  const W=svg.clientWidth||700,H=svg.clientHeight||340;
  const {nodes,edges}=topo;
  if(!nodes.length){
    svg.innerHTML=`
      <defs>
        <linearGradient id="emptyGrad" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stop-color="#37b0ff" stop-opacity=".3"/>
          <stop offset="100%" stop-color="#37b0ff" stop-opacity=".05"/>
        </linearGradient>
      </defs>
      <g transform="translate(${W/2},${H/2-20})">
        <circle r="40" fill="url(#emptyGrad)" stroke="#37b0ff" stroke-width=".5" opacity=".4"/>
        <circle r="28" fill="none" stroke="#37b0ff" stroke-width=".3" stroke-dasharray="4 4" opacity=".3"/>
        <text y="4" text-anchor="middle" fill="#37b0ff" font-size="20" opacity=".5">⬡</text>
        <text y="65" text-anchor="middle" fill="#64748b" font-size="13" font-weight="500">No devices discovered yet</text>
        <text y="82" text-anchor="middle" fill="#4d6284" font-size="11">Start monitoring to see your network</text>
      </g>`;
    return;
  }

  const router=nodes.find(n=>n.is_router)||nodes[0];
  const others=nodes.filter(n=>n.id!==router.id);
  const cx=W/2,cy=H/2,R=Math.min(W,H)*0.36;
  const pos={[router.id]:{x:cx,y:cy}};
  others.forEach((n,i)=>{
    const a=(2*Math.PI*i/Math.max(others.length,1))-Math.PI/2;
    pos[n.id]={x:cx+R*Math.cos(a),y:cy+R*Math.sin(a)};
  });

  // Build SVG defs for gradients and filters
  let defs='<defs>';
  // Glow filter
  defs+=`<filter id="glow" x="-50%" y="-50%" width="200%" height="200%">
    <feGaussianBlur stdDeviation="6" result="blur"/>
    <feComposite in="SourceGraphic" in2="blur" operator="over"/>
  </filter>`;
  defs+=`<filter id="glowStrong" x="-50%" y="-50%" width="200%" height="200%">
    <feGaussianBlur stdDeviation="10" result="blur"/>
    <feComposite in="SourceGraphic" in2="blur" operator="over"/>
  </filter>`;
  // Node gradients per status
  const statusGradients={up:['#22c55e','#16a34a'],down:['#ef4444','#dc2626'],degraded:['#f59e0b','#d97706'],unknown:['#64748b','#475569']};
  Object.entries(statusGradients).forEach(([key,[c1,c2]])=>{
    defs+=`<radialGradient id="ng-${key}" cx="35%" cy="30%" r="70%">
      <stop offset="0%" stop-color="${c1}" stop-opacity=".25"/>
      <stop offset="100%" stop-color="${c2}" stop-opacity=".08"/>
    </radialGradient>`;
    defs+=`<radialGradient id="halo-${key}" cx="50%" cy="50%" r="50%">
      <stop offset="0%" stop-color="${c1}" stop-opacity=".15"/>
      <stop offset="100%" stop-color="${c1}" stop-opacity="0"/>
    </radialGradient>`;
  });
  // Arrow marker
  defs+=`<marker id="flowArrow" markerWidth="6" markerHeight="6" refX="3" refY="3" orient="auto">
    <circle cx="3" cy="3" r="2" fill="#37b0ff" opacity=".6"/>
  </marker>`;
  defs+='</defs>';

  let html=defs;

  // -- Draw edges with curved paths, animated flow, and traveling packets --
  edges.forEach((e,idx)=>{
    const a=pos[e.from],b=pos[e.to];
    if(!a||!b)return;
    const nd=nodes.find(n=>n.id===e.to);
    const st=nd?.status||'unknown';
    const c=SC[st]||SC.unknown;
    const devHops=hops[e.to]||[];

    // Compute control point for curved path
    const mx=(a.x+b.x)/2, my=(a.y+b.y)/2;
    const dx=b.x-a.x, dy=b.y-a.y;
    const len=Math.sqrt(dx*dx+dy*dy)||1;
    const curvature=0.15;
    const cpx=mx+(-dy/len)*len*curvature;
    const cpy=my+(dx/len)*len*curvature;
    const pathD=`M${a.x},${a.y} Q${cpx},${cpy} ${b.x},${b.y}`;
    const pathId=`edge-path-${idx}`;

    // Hidden path for motion reference
    html+=`<path id="${pathId}" d="${pathD}" fill="none" stroke="none"/>`;

    // Background glow path
    html+=`<path d="${pathD}" fill="none" stroke="${c}" stroke-width="4" opacity=".06"/>`;
    // Main edge with draw-in animation
    html+=`<path d="${pathD}" fill="none" stroke="${c}" stroke-width="1.5" opacity=".35"
      stroke-linecap="round" stroke-dasharray="1000" stroke-dashoffset="1000"
      style="animation:edgeDrawIn 1.2s ease ${idx*0.1}s forwards"/>`;
    // Animated flow dash
    html+=`<path d="${pathD}" fill="none" stroke="${c}" stroke-width="1" opacity=".5"
      stroke-dasharray="4 12" stroke-linecap="round"
      style="animation:flowDash ${2+idx*0.3}s linear infinite"/>`;

    // Traveling data packet dot along the edge
    const packetDur=3+idx*0.5;
    html+=`<circle r="2.5" fill="${c}" opacity=".8">
      <animateMotion dur="${packetDur}s" repeatCount="indefinite" rotate="auto">
        <mpath href="#${pathId}"/>
      </animateMotion>
      <animate attributeName="opacity" values=".9;.4;.9" dur="${packetDur}s" repeatCount="indefinite"/>
    </circle>`;
    // Second packet with offset timing for busier look
    if(st==='up'){
      html+=`<circle r="2" fill="${c}" opacity=".5">
        <animateMotion dur="${packetDur*1.3}s" repeatCount="indefinite" rotate="auto"
          begin="${packetDur*0.5}s">
          <mpath href="#${pathId}"/>
        </animateMotion>
        <animate attributeName="opacity" values=".5;.2;.5" dur="${packetDur*1.3}s"
          repeatCount="indefinite" begin="${packetDur*0.5}s"/>
      </circle>`;
    }

    // Draw small hop dots along the path with pulsing animation
    if(devHops.length>1){
      const validHops=devHops.filter(h=>h.hop_ip);
      validHops.forEach((h,i)=>{
        const t=(i+1)/(validHops.length+1);
        const tt=1-t;
        const hx=tt*tt*a.x+2*tt*t*cpx+t*t*b.x;
        const hy=tt*tt*a.y+2*tt*t*cpy+t*t*b.y;
        html+=`<circle cx="${hx}" cy="${hy}" r="3"
          fill="rgba(10,20,36,.9)" stroke="#f59e0b" stroke-width="1">
          <animate attributeName="r" values="3;4;3" dur="2s" begin="${i*0.4}s" repeatCount="indefinite"/>
          <animate attributeName="opacity" values=".5;.9;.5" dur="2s" begin="${i*0.4}s" repeatCount="indefinite"/>
        </circle>`;
        html+=`<circle cx="${hx}" cy="${hy}" r="1.5" fill="#f59e0b" opacity=".6"/>`;
      });
    }
  });

  // -- Draw nodes --
  nodes.forEach((n,nIdx)=>{
    const p=pos[n.id];if(!p)return;
    const st=n.status||'unknown';
    const c=SC[st]||SC.unknown;
    const r=n.is_router?30:20;
    // Short, clean labels — no IP clutter
    const lbl=n.label.length>10?n.label.slice(0,9)+'…':n.label;
    const enc=JSON.stringify({
      name:n.label,ip:n.ip,vendor:n.vendor,mac:n.mac,
      rtt:n.rtt,loss:n.loss,uptime:n.uptime,status:n.status,
      hops:(hops[n.id]||[]).length
    }).replace(/"/g,'&quot;');

    html+=`<g class="topo-node" style="cursor:pointer;transform-origin:${p.x}px ${p.y}px"
        onclick="selectDevice('${n.id}','${n.label}')"
        onmouseenter="showTip(event,'${enc}')"
        onmouseleave="hideTip()">`;

    // Outer breathing glow halo
    html+=`<circle cx="${p.x}" cy="${p.y}" r="${r+16}"
      fill="url(#halo-${st})">
      <animate attributeName="opacity" values=".3;.6;.3" dur="${3+nIdx*0.2}s" repeatCount="indefinite"/>
    </circle>`;

    // Animated pulse ring (for online devices)
    if(st==='up'){
      html+=`<circle cx="${p.x}" cy="${p.y}" r="${r+3}"
        fill="none" stroke="${c}" stroke-width="1" opacity="0">
        <animate attributeName="r" from="${r+3}" to="${r+20}" dur="2.5s" repeatCount="indefinite"/>
        <animate attributeName="opacity" from=".4" to="0" dur="2.5s" repeatCount="indefinite"/>
      </circle>`;
      // Second pulse ring staggered for layered heartbeat
      html+=`<circle cx="${p.x}" cy="${p.y}" r="${r+3}"
        fill="none" stroke="${c}" stroke-width=".6" opacity="0">
        <animate attributeName="r" from="${r+3}" to="${r+20}" dur="2.5s" begin="1.25s" repeatCount="indefinite"/>
        <animate attributeName="opacity" from=".25" to="0" dur="2.5s" begin="1.25s" repeatCount="indefinite"/>
      </circle>`;
    }
    // Down devices get a slow warning pulse
    if(st==='down'){
      html+=`<circle cx="${p.x}" cy="${p.y}" r="${r+2}"
        fill="none" stroke="${c}" stroke-width="1.5" opacity="0">
        <animate attributeName="r" from="${r+2}" to="${r+14}" dur="1.8s" repeatCount="indefinite"/>
        <animate attributeName="opacity" from=".6" to="0" dur="1.8s" repeatCount="indefinite"/>
      </circle>`;
    }

    if(n.is_router){
      // Rotating scanner ring around router
      html+=`<circle cx="${p.x}" cy="${p.y}" r="${r+8}"
        fill="none" stroke="${c}" stroke-width=".6"
        stroke-dasharray="8 14 4 14" opacity=".4"
        style="transform-origin:${p.x}px ${p.y}px;animation:scannerSpin 12s linear infinite"/>`;

      // Hexagonal router shape
      const hex=[];
      for(let i=0;i<6;i++){
        const angle=Math.PI/6+i*Math.PI/3;
        hex.push(`${p.x+r*Math.cos(angle)},${p.y+r*Math.sin(angle)}`);
      }
      html+=`<polygon points="${hex.join(' ')}"
        fill="url(#ng-${st})" stroke="${c}" stroke-width="2"
        filter="url(#glow)"/>`;
      // Inner hexagon
      const hexInner=[];
      for(let i=0;i<6;i++){
        const angle=Math.PI/6+i*Math.PI/3;
        hexInner.push(`${p.x+(r-6)*Math.cos(angle)},${p.y+(r-6)*Math.sin(angle)}`);
      }
      html+=`<polygon points="${hexInner.join(' ')}"
        fill="none" stroke="${c}" stroke-width=".5" opacity=".3"/>`;
      // Router icon
      html+=`<text x="${p.x}" y="${p.y+4}" text-anchor="middle"
        font-size="14" fill="${c}" opacity=".8">⬡</text>`;
    } else {
      // Regular device: circle with gradient
      html+=`<circle cx="${p.x}" cy="${p.y}" r="${r}"
        fill="url(#ng-${st})" stroke="${c}" stroke-width="1.5"
        filter="url(#glow)"/>`;
      // Inner ring
      html+=`<circle cx="${p.x}" cy="${p.y}" r="${r-4}"
        fill="none" stroke="${c}" stroke-width=".4" opacity=".2"/>`;
      // Status indicator dot with breathing
      html+=`<circle cx="${p.x+r*0.55}" cy="${p.y-r*0.55}" r="3.5"
        fill="${c}" stroke="rgba(6,14,28,.8)" stroke-width="1.5">
        <animate attributeName="r" values="3.5;4.2;3.5" dur="2s" repeatCount="indefinite"/>
      </circle>`;
    }

    // Label pill — positioned below the node with enough gap
    const lblW=lbl.length*6.2+14;
    html+=`<rect x="${p.x-lblW/2}" y="${p.y+r+5}" width="${lblW}" height="16"
      rx="8" fill="rgba(6,14,28,.88)" stroke="${c}33" stroke-width=".5"/>`;
    html+=`<text x="${p.x}" y="${p.y+r+16}" text-anchor="middle"
      font-size="9" fill="${c}" font-weight="600"
      font-family="'Manrope',sans-serif">${lbl}</text>`;

    html+='</g>';
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
    el.innerHTML='<div class="activity-empty">No recent activity</div>';
    return;
  }
  el.innerHTML = events.map(e=>{
    const ts  = new Date(e.timestamp).toLocaleTimeString();
    const dot = `<span class="activity-dot" style="background:${e.color}"></span>`;
    return `<div class="activity-item">
      ${dot}
      <div style="min-width:0">
        <div class="activity-title" style="color:${e.color}">${e.title}</div>
        <div class="activity-sub">
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