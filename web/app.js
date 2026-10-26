const nodeList = document.querySelector('#node-list');
const eventList = document.querySelector('#event-list');
const emptyEvents = document.querySelector('#empty-events');
const toast = document.querySelector('#toast');
const mapNodes = document.querySelector('#map-nodes');
const mapLines = document.querySelector('#map-lines');
const messageForm = document.querySelector('#message-form');
const messageSource = document.querySelector('#message-source');
const messageDestination = document.querySelector('#message-destination');
const messageText = document.querySelector('#message-text');
const sosSource = document.querySelector('#sos-source');
let currentState = null;
let toastTimer = null;
let mutationPending = false;
let refreshVersion = 0;
let connectionFailed = false;
const renderedMarkup = new WeakMap();

function renderHtml(element, markup) {
  // Preserve focus and in-progress clicks when polling returns unchanged data.
  if (renderedMarkup.get(element) !== markup) {
    element.innerHTML = markup;
    renderedMarkup.set(element, markup);
  }
}

function updateBusy() {
  document.querySelectorAll('button, select').forEach((control) => {
    control.disabled = mutationPending;
  });
  document.querySelector('main').setAttribute('aria-busy', String(mutationPending));
}

async function runMutation(action) {
  if (mutationPending) return;
  mutationPending = true;
  ++refreshVersion; // Invalidate state requests started before this operation.
  updateBusy();
  try { await action(); }
  catch (error) { notify(error.message, true); }
  finally { mutationPending = false; updateBusy(); }
}

const escapeHtml = (value) => String(value).replace(/[&<>"']/g, (char) => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
}[char]));

async function request(path, payload) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 8000);
  const options = payload === undefined ? {} : {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  };
  try {
    const response = await fetch(path, { ...options, signal: controller.signal, cache: 'no-store' });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'เกิดข้อผิดพลาด');
    return data;
  } catch (error) {
    if (error.name === 'AbortError') throw new Error('ระบบตอบกลับช้าเกินไป โปรดตรวจเหตุการณ์ล่าสุดก่อนส่งซ้ำ');
    throw error;
  } finally { clearTimeout(timeout); }
}

function notify(message, isError = false) {
  toast.textContent = message;
  toast.classList.toggle('error', isError);
  toast.classList.add('visible');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => toast.classList.remove('visible'), 3000);
}

function ensureOptions(select, nodes, selectedId) {
  const currentValue = select.value || selectedId;
  if (select.options.length !== nodes.length) {
    select.innerHTML = nodes.map((node) =>
      `<option value="${escapeHtml(node.id)}">Node ${escapeHtml(node.id)} — ${escapeHtml(node.role)}</option>`
    ).join('');
  }
  if (nodes.some((node) => node.id === currentValue)) select.value = currentValue;
  else select.value = selectedId;
}

function mapPositions(nodes) {
  const width = 1000;
  const height = 420;
  // Keep node labels apart in the four-node portfolio topology.
  const mobileLayout = {
    A: { x: 160, y: 315 },
    B: { x: 500, y: 240 },
    C: { x: 840, y: 315 },
    D: { x: 500, y: 100 },
  };
  const desktopLayout = {
    A: { x: 170, y: 100 },
    B: { x: 500, y: 185 },
    C: { x: 830, y: 100 },
    D: { x: 170, y: 300 },
  };
  const schematic = window.matchMedia('(max-width: 600px)').matches ? mobileLayout : desktopLayout;
  if (nodes.every((node) => schematic[node.id])) {
    return new Map(nodes.map((node) => [node.id, schematic[node.id]]));
  }
  const padX = 125;
  const padY = 80;
  const lats = nodes.map((node) => node.latitude);
  const lons = nodes.map((node) => node.longitude);
  const minLat = Math.min(...lats), maxLat = Math.max(...lats);
  const minLon = Math.min(...lons), maxLon = Math.max(...lons);
  const spanLat = maxLat - minLat || 1;
  const spanLon = maxLon - minLon || 1;
  return new Map(nodes.map((node) => [node.id, {
    x: padX + ((node.longitude - minLon) / spanLon) * (width - padX * 2),
    y: height - padY - ((node.latitude - minLat) / spanLat) * (height - padY * 2),
  }]));
}

function renderMap(state) {
  const positions = mapPositions(state.nodes);
  const latest = state.messages[0];
  const activePath = latest?.path || [];
  const activeLinks = new Set(activePath.slice(1).map((id, index) => `${activePath[index]}:${id}`));
  const broadcast = latest?.kind === 'sos' && latest.delivered;
  const reached = new Set([latest?.source, ...(latest?.recipients || [])]);
  renderHtml(mapLines, state.links.map((link) => {
    const from = positions.get(link.from), to = positions.get(link.to);
    const active = activeLinks.has(`${link.from}:${link.to}`) || activeLinks.has(`${link.to}:${link.from}`);
    const offline = !state.nodes.find((node) => node.id === link.from)?.online
      || !state.nodes.find((node) => node.id === link.to)?.online;
    const broadcastLink = broadcast && reached.has(link.from) && reached.has(link.to);
    return `<line class="link-line ${active || broadcastLink ? 'active' : ''} ${offline ? 'inactive' : ''}" x1="${from.x}" y1="${from.y}" x2="${to.x}" y2="${to.y}" />`;
  }).join(''));
  renderHtml(mapNodes, state.nodes.map((node) => {
    const point = positions.get(node.id);
    const x = point.x / 10;
    const y = point.y / 4.2;
    const coordinate = `${Number(node.latitude).toFixed(4)}, ${Number(node.longitude).toFixed(4)}`;
    return `<div class="map-node ${node.online ? '' : 'offline'}" data-id="${escapeHtml(node.id)}" style="left:${x}%;top:${y}%">
      <button class="map-node-button" type="button" data-select-source="${escapeHtml(node.id)}" aria-label="เลือก Node ${escapeHtml(node.id)} เป็นต้นทาง">
        <span class="node-radio" aria-hidden="true"></span>
      </button>
      <strong>Node ${escapeHtml(node.id)}</strong><small>${escapeHtml(node.role)}</small><code>${coordinate}</code>
    </div>`;
  }).join(''));
  document.querySelector('#route-caption').textContent = latest && !latest.delivered
    ? `${latest.kind === 'sos' ? 'SOS' : 'ข้อความ'} จาก Node ${latest.source} ส่งไม่ถึงปลายทาง`
    : latest?.kind === 'sos' && latest.delivered
    ? `SOS broadcast จาก Node ${latest.source} → ${latest.recipients.join(', ')}`
    : latest?.path
      ? latest.path.map((id) => `Node ${id}`).join(' → ')
      : 'A → B → C · Node D เป็นรีเลย์สำรอง';
}

function renderNodes(state) {
  const latestSos = state.messages.find((message) => message.kind === 'sos');
  const alertNodes = new Set(latestSos?.recipients || []);
  renderHtml(nodeList, state.nodes.map((node) => {
    const coordinate = `${Number(node.latitude).toFixed(4)}, ${Number(node.longitude).toFixed(4)}`;
    return `<article class="node-card ${node.online ? '' : 'offline'} ${node.online && alertNodes.has(node.id) ? 'alarm' : ''}">
      <span class="node-icon" aria-hidden="true"></span>
      <div class="node-info">
        <div class="node-title">Node ${escapeHtml(node.id)}<span class="status-text ${node.online ? '' : 'offline'}"><i></i>${node.online ? 'ออนไลน์' : 'ออฟไลน์'}</span></div>
        <div class="role-text">${escapeHtml(node.role)}</div>
        <div class="node-details"><span>⌁ Wi-Fi AP: ${escapeHtml(node.ap_ssid)}</span><span>⌖ ${coordinate} · ${escapeHtml(node.gps_source)}</span></div>
      </div>
      <button class="toggle-node" type="button" data-toggle-node="${escapeHtml(node.id)}" aria-label="${node.online ? 'จำลองปิด' : 'จำลองเปิด'} Node ${escapeHtml(node.id)}">${node.online ? 'ปิดโหนด' : 'เปิดโหนด'}</button>
    </article>`;
  }).join(''));
  ensureOptions(messageSource, state.nodes, 'A');
  ensureOptions(messageDestination, state.nodes, 'C');
  ensureOptions(sosSource, state.nodes, 'A');
  ensureOptions(document.querySelector('#gps-node'), state.nodes, 'A');
  const sourceNode = state.nodes.find((node) => node.id === 'A');
  if (sourceNode) document.querySelector('#header-gps').textContent = `${Number(sourceNode.latitude).toFixed(4)}, ${Number(sourceNode.longitude).toFixed(4)} · ${sourceNode.gps_source}`;
  syncDestination();
}

function syncDestination() {
  for (const option of messageDestination.options) {
    option.disabled = option.value === messageSource.value;
  }
  if (messageDestination.value === messageSource.value) {
    messageDestination.value = [...messageDestination.options].find((option) => !option.disabled)?.value || '';
  }
}

function renderConnection(state) {
  const isBle = state.connection_mode === 'ble';
  document.querySelector('#connection-title').textContent = isBle ? 'BLE fallback' : 'Wi-Fi AP';
  document.querySelectorAll('[data-connection-mode]').forEach((button) => {
    const selected = button.dataset.connectionMode === state.connection_mode;
    button.classList.toggle('active', selected);
    button.setAttribute('aria-pressed', String(selected));
  });
  document.querySelector('#connection-summary').innerHTML = isBle
    ? '<i class="dot"></i> BLE fallback จำลอง · Mobile'
    : '<i class="dot"></i> Captive Portal จำลอง · NODE-A';
  document.querySelector('#connection-note').textContent = isBle
    ? 'จำลองผู้ใช้มือถือเชื่อม Node ผ่าน Bluetooth LE · routing ใช้ LoRa Mesh จำลอง'
    : 'Captive Portal จำลองเปิดอัตโนมัติเมื่อเชื่อม Wi-Fi';
}

function renderEvents(state) {
  const events = state.events;
  document.querySelector('#event-count').textContent = String(events.length);
  emptyEvents.hidden = events.length > 0;
  renderHtml(eventList, events.slice(0, 8).map((event) => {
    const iconClass = event.title === 'SOS' ? 'sos' : event.title.includes('ข้อความ') ? 'message' : '';
    const symbol = event.title === 'SOS' ? 'SOS' : event.title.includes('ข้อความ') ? '•••' : '⌁';
    return `<li class="event-item"><span class="event-mark ${iconClass}" aria-hidden="true">${symbol}</span>
      <div class="event-content"><strong>${escapeHtml(event.title)}${event.node_id ? ` · Node ${escapeHtml(event.node_id)}` : ''}</strong><p>${escapeHtml(event.detail)}</p></div>
      <time class="event-time">${escapeHtml(event.time)}</time></li>`;
  }).join(''));
  const latestSos = state.messages.find((message) => message.kind === 'sos');
  const alertPanel = document.querySelector('#alert-panel');
  if (latestSos?.delivered && latestSos.recipients.length) {
    alertPanel.classList.add('active');
    document.querySelector('#alert-status').textContent = `Node ${latestSos.recipients.join(', ')} รับ SOS · Buzzer ดัง · LED กะพริบ`;
    document.querySelector('#alert-label').textContent = 'แจ้งเตือน';
  } else {
    alertPanel.classList.remove('active');
    document.querySelector('#alert-status').textContent = latestSos
      ? 'SOS ล่าสุดส่งไม่ถึงโหนดใด ไม่มีการแจ้งเตือนปลายทาง'
      : 'Buzzer และ LED จะทำงานเมื่อได้รับ SOS';
    document.querySelector('#alert-label').textContent = latestSos ? 'ส่งไม่สำเร็จ' : 'พร้อม';
  }
}

function render(state) {
  currentState = state;
  renderMap(state);
  renderNodes(state);
  renderConnection(state);
  renderEvents(state);
  document.querySelector('#radio-range').textContent = `${state.radio_range_m} m`;
  const updated = new Date(state.updated_at);
  document.querySelector('#updated-at').textContent = updated.toLocaleTimeString('th-TH', { hour12: false });
  document.querySelector('#mesh-status').textContent = 'จำลองพร้อมใช้งาน';
  document.querySelector('#mesh-dot').classList.remove('offline-dot');
  updateBusy();
}

async function refresh(force = false) {
  if (mutationPending && !force) return;
  const version = ++refreshVersion;
  try {
    const state = await request('/api/state');
    if (version !== refreshVersion) return;
    render(state);
    connectionFailed = false;
  } catch (error) {
    if (version !== refreshVersion) return;
    document.querySelector('#mesh-status').textContent = 'ขาดการเชื่อมต่อ';
    document.querySelector('#mesh-dot').classList.add('offline-dot');
    if (!connectionFailed) notify(`เชื่อมต่อระบบจำลองไม่ได้: ${error.message}`, true);
    connectionFailed = true;
  }
}

async function submitMessage(event) {
  event.preventDefault();
  const button = messageForm.querySelector('button[type="submit"]');
  button.disabled = true;
  try {
    const result = await request('/api/message', {
      source: messageSource.value,
      destination: messageDestination.value,
      text: messageText.value,
    });
    await refresh(true);
    notify(result.delivered ? `ส่งถึง Node ${result.destination} แล้ว · ${result.path.join(' → ')}` : `ยังส่งไม่ถึง Node ${result.destination}`);
  } catch (error) { notify(error.message, true); }
  finally { button.disabled = false; }
}

function playBuzzer() {
  try {
    const audioContext = new (window.AudioContext || window.webkitAudioContext)();
    const oscillator = audioContext.createOscillator();
    const gain = audioContext.createGain();
    oscillator.type = 'square';
    oscillator.frequency.value = 880;
    gain.gain.setValueAtTime(.04, audioContext.currentTime);
    gain.gain.exponentialRampToValueAtTime(.001, audioContext.currentTime + .38);
    oscillator.connect(gain);
    gain.connect(audioContext.destination);
    oscillator.start();
    oscillator.stop(audioContext.currentTime + .38);
    oscillator.onended = () => { audioContext.close().catch(() => {}); };
  } catch { /* Browser audio may be unavailable; visual LED feedback still works. */ }
}

async function sendSos() {
  const button = document.querySelector('#sos-button');
  button.disabled = true;
  try {
    const result = await request('/api/sos', { source: sosSource.value });
    await refresh(true);
    if (result.delivered) {
      playBuzzer();
      const locationLabel = result.gps_source?.includes('ไม่มี fix')
        ? 'พร้อมพิกัดล่าสุด (ยังไม่มี GPS fix)'
        : 'พร้อมพิกัด GPS';
      notify(`SOS ถึง ${result.recipients.map((id) => `Node ${id}`).join(', ')} ${locationLabel}`);
    } else notify('ไม่มี Node ปลายทางออนไลน์ที่รับ SOS ได้', true);
  } catch (error) { notify(error.message, true); }
  finally { button.disabled = false; }
}

async function submitGps(event) {
  event.preventDefault();
  const button = document.querySelector('.gps-parse-button');
  button.disabled = true;
  try {
    const state = await request('/api/gps/nmea', {
      node_id: document.querySelector('#gps-node').value,
      sentence: document.querySelector('#gps-sentence').value,
    });
    render(state);
    const latestEvent = state.events[0];
    document.querySelector('#gps-result').textContent = latestEvent?.title === 'GPS parser'
      ? latestEvent.detail
      : 'พิกัดได้รับการอัปเดตแล้ว';
    notify(document.querySelector('#gps-result').textContent);
  } catch (error) {
    document.querySelector('#gps-result').textContent = error.message;
    notify(error.message, true);
  } finally { button.disabled = false; }
}

messageForm.addEventListener('submit', (event) => {
  event.preventDefault();
  runMutation(() => submitMessage(event));
});
messageSource.addEventListener('change', syncDestination);
document.querySelector('#sos-button').addEventListener('click', () => runMutation(sendSos));
document.querySelector('#gps-form').addEventListener('submit', (event) => {
  event.preventDefault();
  runMutation(() => submitGps(event));
});
document.querySelector('#reset-button').addEventListener('click', () => runMutation(async () => {
  try {
    const state = await request('/api/reset', {});
    messageForm.reset();
    messageDestination.value = 'C';
    sosSource.value = 'A';
    document.querySelector('#gps-form').reset();
    document.querySelector('#gps-result').textContent = 'ป้อน NMEA RMC หรือ GGA ที่มี GPS fix';
    document.querySelector('#character-count').textContent = `${messageText.value.length}/200`;
    render(state);
    notify('เริ่มสถานการณ์จำลองใหม่แล้ว');
  }
  catch (error) { notify(error.message, true); }
}));
messageText.addEventListener('input', () => {
  document.querySelector('#character-count').textContent = `${messageText.value.length}/200`;
});
document.querySelector('#character-count').textContent = `${messageText.value.length}/200`;
document.addEventListener('click', async (event) => {
  const sourceButton = event.target.closest('[data-select-source]');
  if (sourceButton) {
    const id = sourceButton.dataset.selectSource;
    messageSource.value = id;
    sosSource.value = id;
    syncDestination();
    notify(`เลือก Node ${id} เป็นต้นทางแล้ว`);
    return;
  }
  const toggleButton = event.target.closest('[data-toggle-node]');
  if (toggleButton && currentState) {
    const id = toggleButton.dataset.toggleNode;
    const node = currentState.nodes.find((item) => item.id === id);
    await runMutation(async () => { try {
      render(await request('/api/node-status', { node_id: id, online: !node.online }));
      notify(`เปลี่ยนสถานะ Node ${id} แล้ว · ลองส่งข้อความเพื่อดูการเลือกเส้นทาง`);
    } catch (error) { notify(error.message, true); } });
    return;
  }
  const connectionButton = event.target.closest('[data-connection-mode]');
  if (connectionButton) {
    await runMutation(async () => { try {
      render(await request('/api/connection-mode', { mode: connectionButton.dataset.connectionMode }));
      notify(connectionButton.dataset.connectionMode === 'ble'
        ? 'เปิด BLE fallback จำลองสำหรับผู้ใช้มือถือแล้ว'
        : 'เปิด Wi-Fi AP / Captive Portal จำลองแล้ว');
    } catch (error) { notify(error.message, true); } });
  }
});

refresh();
window.setInterval(refresh, 2000);
window.addEventListener('resize', () => {
  if (currentState) renderMap(currentState);
  updateBusy();
});
