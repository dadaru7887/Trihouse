/* EXPLAINCODE: 이 화면은 Gateway snapshot/event만 읽고 DB·RMF·ROS를 직접 호출하지 않는다. */
const byId = (id) => document.getElementById(id);
const text = (value) => document.createTextNode(String(value ?? ''));
const clear = (node) => node.replaceChildren();

// 표에 문자열을 넣을 때 text node를 사용해 외부 상태 값이 HTML로 실행되지 않게 한다.
function cell(row, value) { const td = document.createElement('td'); td.append(text(value)); row.append(td); }

function render(snapshot) {
  const map = byId('map'); clear(map);
  snapshot.robots.forEach((robot) => {
    const marker = document.createElement('span'); marker.className = 'robot';
    // read model 좌표는 이 간단한 화면에서 0~100 지도 비율로 제한한다.
    marker.style.left = `${Math.max(0, Math.min(100, robot.x))}%`; marker.style.top = `${Math.max(0, Math.min(100, robot.y))}%`;
    marker.title = `${robot.robot_id}: ${robot.safety_state}`; marker.append(text(robot.robot_id)); map.append(marker);
  });
  const robots = byId('robots'); clear(robots);
  snapshot.robots.forEach((robot) => { const row = document.createElement('tr'); cell(row, robot.robot_id); cell(row, `${robot.battery_percent}%`); cell(row, robot.safety_state); cell(row, `${robot.job_id || '-'} / ${robot.stage}`); cell(row, robot.error || '-'); robots.append(row); });
  const jobs = byId('jobs'); clear(jobs);
  snapshot.jobs.forEach((job) => { const row = document.createElement('tr'); cell(row, job.job_id); cell(row, `${job.order_id} / ${job.item_ids.join(', ')}`); cell(row, job.robot_id || '-'); cell(row, job.stage); cell(row, job.state); jobs.append(row); });
  const incidents = byId('incidents'); clear(incidents);
  snapshot.incidents.forEach((incident) => { const alert = document.createElement('article'); alert.className = 'incident'; alert.dataset.acknowledged = incident.acknowledged; alert.append(text(`${incident.location_id} · ${incident.camera_id} · ${new Date(incident.occurred_at_s * 1000).toLocaleString()}${incident.acknowledged ? ' · 확인됨' : ' · 확인 필요'}`)); incidents.append(alert); });
  renderCameraChoices(snapshot.incidents);
}

function renderCameraChoices(incidents) {
  const select = byId('camera-select'); const previous = select.value; clear(select);
  const off = document.createElement('option'); off.value = ''; off.append(text('재생 안 함')); select.append(off);
  [...new Set(incidents.map((incident) => incident.camera_id))].forEach((cameraId) => { const option = document.createElement('option'); option.value = cameraId; option.append(text(cameraId)); select.append(option); });
  select.value = previous;
}

byId('camera-select').addEventListener('change', async (event) => {
  const player = byId('camera-player'); const cameraId = event.target.value;
  if (!cameraId) { player.removeAttribute('src'); player.load(); return; }
  try {
    // 재생 URL은 선택 시점에만 Gateway에서 받고, 이 화면은 recorder를 시작/중지하지 않는다.
    const response = await fetch(`/api/v1/cameras/${encodeURIComponent(cameraId)}/playback`);
    if (!response.ok) throw new Error(`camera playback request failed: ${response.status}`);
    player.src = (await response.json()).playback_url;
  } catch (error) { player.removeAttribute('src'); player.load(); showError(error); }
});

// 예약 이상은 snapshot이 아니라 Gateway 원장에서 온다. 자원은 풀렸는데 로봇이 아직
// 거기 있을 수 있는 상태이고, 사람이 확인하기 전까지 그 job은 다시 배정되지 않는다.
// 확인할 곳이 없으면 이상은 열리기만 하고 아무도 닫지 못해 job이 영구히 멈춘다.
function renderAnomalies(anomalies) {
  const container = byId('anomalies'); clear(container);
  anomalies.forEach((anomaly) => {
    const row = document.createElement('article'); row.className = 'anomaly';
    row.append(text(`작업 ${anomaly.job_id ?? '-'} · ${anomaly.device_id || '자원'} · ${new Date(anomaly.occurred_at).toLocaleString()}`));
    const button = document.createElement('button'); button.type = 'button'; button.append(text('확인'));
    button.addEventListener('click', () => acknowledgeAnomaly(anomaly.correlation_uuid).catch(showError));
    row.append(button); container.append(row);
  });
}

async function acknowledgeAnomaly(correlationUuid) {
  const response = await fetch(`/api/v1/operations/anomalies/${encodeURIComponent(correlationUuid)}/acknowledge`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ worker_id: byId('anomaly-worker').value, note: '관제 화면에서 확인' }),
  });
  if (!response.ok) throw new Error(`acknowledge failed: ${response.status}`);
  await refreshAnomalies();
}

async function refreshAnomalies() {
  const response = await fetch('/api/v1/operations/anomalies?state=open', { headers: { Accept: 'application/json' } });
  if (!response.ok) throw new Error(`anomaly request failed: ${response.status}`);
  renderAnomalies((await response.json()).anomalies);
}

async function refresh() {
  const response = await fetch('/api/v1/operations', { headers: { Accept: 'application/json' } });
  if (!response.ok) throw new Error(`snapshot request failed: ${response.status}`);
  render(await response.json()); await refreshAnomalies(); byId('connection-state').textContent = '연결됨';
}

function connectEvents() {
  const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
  const socket = new WebSocket(`${protocol}//${location.host}/api/v1/events/ws`);
  socket.onmessage = () => refresh().catch(showError);
  socket.onerror = () => { byId('connection-state').textContent = '이벤트 재연결 중'; };
  // 현재 Gateway는 one-shot event frame을 보내므로 close 후 재연결한다.
  socket.onclose = () => window.setTimeout(connectEvents, 1000);
}

function showError(error) { byId('connection-state').textContent = `연결 오류: ${error.message}`; }
refresh().catch(showError); connectEvents();
