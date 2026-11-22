'use strict';

let latestResult = null;
const $ = (id) => document.getElementById(id);
const fmt = (value) => Number(value || 0).toFixed(2);
const escapeHTML = (value) => String(value).replace(/[&<>"']/g, (c) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

async function api(url, options = {}) {
  const response = await fetch(url, options);
  let data;
  try { data = await response.json(); } catch { throw new Error('The server returned an unreadable response.'); }
  if (!response.ok || data.success === false) throw new Error(data.message || `Request failed (${response.status}).`);
  return data;
}
function setBusy(button, busy, label) {
  if (!button) return;
  button.disabled = busy;
  if (busy) { button.dataset.oldText = button.innerHTML; button.textContent = label || 'Working…'; }
  else if (button.dataset.oldText) { button.innerHTML = button.dataset.oldText; delete button.dataset.oldText; }
}
function status(id, message, error = false) {
  const node = $(id); node.textContent = message; node.style.color = error ? '#b45c48' : '';
}

async function calculate(event) {
  event?.preventDefault();
  const button = $('calculateBtn');
  const payload = {
    vehicle: $('vehicle').value,
    distance_km: $('distance').value || 0,
    electricity_units: $('units').value || 0,
    meals: $('meals').value || 0,
    food_type: $('foodType').value
  };
  setBusy(button, true, 'Calculating…');
  try {
    latestResult = await api('/api/calculate', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload)});
    renderResult(latestResult);
    $('recommendBtn').disabled = false; $('simulateBtn').disabled = false;
    $('recommendations').textContent = 'Your estimate is ready. Generate an action plan to get practical next steps.';
    $('simulationResult').textContent = '';
    await loadHistory();
  } catch (error) { alert(error.message); }
  finally { setBusy(button, false); }
}

function renderResult(result) {
  $('totalMetric').textContent = fmt(result.total);
  $('transportMetric').textContent = fmt(result.transport);
  $('electricityMetric').textContent = fmt(result.electricity);
  $('foodMetric').textContent = fmt(result.food);
  $('donutTotal').textContent = fmt(result.total);
  $('legendTransport').textContent = `${fmt(result.transport)} kg`;
  $('legendElectricity').textContent = `${fmt(result.electricity)} kg`;
  $('legendFood').textContent = `${fmt(result.food)} kg`;
  $('latestLabel').textContent = 'Latest calculation · illustrative estimate';
  $('resultState').textContent = 'CALCULATED';
  const total = Math.max(result.total, 0.0001);
  const t = result.transport / total * 360, e = result.electricity / total * 360;
  $('donut').style.background = `conic-gradient(#3c8b65 0deg ${t}deg,#e4bc57 ${t}deg ${t+e}deg,#e28c70 ${t+e}deg 360deg)`;
  $('totalBar').style.width = `${Math.min(100, result.total / Math.max(result.total, 100) * 100)}%`;
  const largest = Object.entries({Transport:result.transport, Electricity:result.electricity, Food:result.food}).sort((a,b)=>b[1]-a[1])[0];
  $('resultNote').textContent = `${largest[0]} is your largest estimated category in this calculation (${fmt(largest[1])} kg CO₂e). ${result.assumptions || 'Values are based on simplified illustrative emission factors.'}`;
}

async function loadHistory() {
  try {
    const data = await api('/api/history');
    const body = $('historyBody');
    if (!data.entries.length) { body.innerHTML = '<tr><td colspan="5" class="empty-cell">No calculations yet. Your first result will show up here.</td></tr>'; return; }
    if (!latestResult) { latestResult = data.entries[0]; renderResult(latestResult); $('recommendBtn').disabled = false; $('simulateBtn').disabled = false; }
    body.innerHTML = data.entries.map((entry) => `<tr><td>${escapeHTML(new Date(entry.created_at).toLocaleString())}</td><td>${fmt(entry.transport)} kg</td><td>${fmt(entry.electricity)} kg</td><td>${fmt(entry.food)} kg</td><td>${fmt(entry.total)} kg CO₂e</td></tr>`).join('');
  } catch (error) { $('historyBody').innerHTML = `<tr><td colspan="5" class="empty-cell">${escapeHTML(error.message)}</td></tr>`; }
}

async function generateRecommendations() {
  if (!latestResult) return;
  const button = $('recommendBtn'); setBusy(button, true, 'Generating…');
  try {
    const data = await api('/api/recommendations', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({transport:latestResult.transport,electricity:latestResult.electricity,food:latestResult.food})});
    $('recommendations').textContent = `${data.message}${data.note ? `\n\n${data.note}` : ''}\n\nSource: ${data.mode}`;
  } catch (error) { status('recommendations', error.message, true); }
  finally { setBusy(button, false); }
}
function simulate() {
  if (!latestResult) return;
  const saved = latestResult.electricity * .2;
  $('simulationResult').textContent = `A 20% reduction in the electricity estimate would reduce this calculation by about ${fmt(saved)} kg CO₂e. New estimated total: ${fmt(latestResult.total - saved)} kg CO₂e. This is a scenario, not a forecast.`;
}

function extractUnits(text) {
  const patterns = [/(?:units? consumed|consumption|energy consumed|total units|units|kwh)\s*[:#=\-]?\s*(\d{1,5}(?:\.\d+)?)/i,/(\d{1,5}(?:\.\d+)?)\s*(?:units|kwh)\b/i];
  for (const pattern of patterns) { const match = text.match(pattern); if (match) { const n = Number(match[1]); if (n >= 0 && n <= 100000) return n; } }
  return null;
}
async function uploadBill() {
  const file = $('billFile').files[0]; if (!file) return;
  if (!file.type.startsWith('image/')) { status('ocrStatus','Please choose an image file.',true); return; }
  if (!window.Tesseract) { status('ocrStatus','OCR library did not load. Enter the units manually.',true); return; }
  status('ocrStatus','Reading the bill image. This can take a few seconds…');
  try {
    const result = await window.Tesseract.recognize(file, 'eng');
    const units = extractUnits(result?.data?.text || '');
    if (units === null) { status('ocrStatus','Could not confidently find the units value. Please enter it manually; OCR can misread bill numbers.',true); return; }
    $('units').value = units; status('ocrStatus',`OCR suggestion: ${units} units. Please verify it against your bill before calculating.`);
  } catch { status('ocrStatus','OCR failed. Try a sharper, well-lit bill image or enter units manually.',true); }
}

async function analyzeFood() {
  const file = $('foodFile').files[0]; if (!file) return;
  if (!['image/jpeg','image/png','image/webp'].includes(file.type)) { status('foodStatus','Use a JPG, PNG or WebP image.',true); return; }
  if (file.size > 7 * 1024 * 1024) { status('foodStatus','Image must be smaller than 7 MB.',true); return; }
  status('foodStatus','AI is examining the image…');
  const form = new FormData(); form.append('image', file);
  try {
    const data = await api('/api/analyze-food',{method:'POST',body:form});
    const result = data.result;
    if (['vegetarian','chicken','fish','mutton'].includes(result.food_type)) $('foodType').value = result.food_type;
    status('foodStatus',`${result.dish_name || 'Food detected'} · ${result.food_type} · confidence ${Math.round((Number(result.confidence)||0)*100)}%. ${data.disclaimer}`);
  } catch (error) { status('foodStatus',error.message,true); }
}

async function compareRoute(event) {
  event.preventDefault(); const button = $('routeBtn'); setBusy(button,true,'Finding route…');
  try {
    const data = await api('/api/route',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({origin:$('origin').value.trim(),destination:$('destination').value.trim()})});
    const entries = Object.entries(data.comparison).sort((a,b)=>a[1]-b[1]);
    $('routeResult').innerHTML = `<div class="route-distance">${fmt(data.distance_km)} km</div><div>Estimated driving-route distance · ${escapeHTML(data.source)}</div><div class="route-modes">${entries.map(([mode,value],i)=>`<div class="route-mode ${i===0?'best':''}"><small>${i===0?'LOWEST FACTOR':'ESTIMATED'} · ${escapeHTML(mode)}</small><b>${fmt(value)} kg CO₂e</b></div>`).join('')}</div><p>${escapeHTML(data.note)}</p>`;
  } catch (error) { $('routeResult').textContent = error.message; }
  finally { setBusy(button,false); }
}
async function saveRoutine(event) {
  event.preventDefault(); const button = $('routineForm').querySelector('button[type=submit]'); setBusy(button,true,'Saving…');
  try {
    const data = await api('/api/routine',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({origin:$('routineOrigin').value.trim(),destination:$('routineDestination').value.trim(),vehicle:$('routineVehicle').value})});
    status('routineStatus',data.message);
  } catch (error) { status('routineStatus',error.message,true); }
  finally { setBusy(button,false); }
}
async function loadRoutine() {
  try { const data = await api('/api/routine'); if (data.routine) { $('routineOrigin').value=data.routine.origin; $('routineDestination').value=data.routine.destination; $('routineVehicle').value=data.routine.vehicle; status('routineStatus','Saved routine loaded from this server.'); } } catch {}
}
async function clearHistory() {
  if (!confirm('Delete all saved calculations from this app database?')) return;
  try { await api('/api/history',{method:'DELETE'}); latestResult=null; $('totalMetric').textContent='—'; $('transportMetric').textContent='—'; $('electricityMetric').textContent='—'; $('foodMetric').textContent='—'; $('donutTotal').textContent='—'; $('resultState').textContent='AWAITING DATA'; $('donut').style.background='conic-gradient(#dfe8df 0deg 360deg)'; $('recommendBtn').disabled=true; $('simulateBtn').disabled=true; await loadHistory(); } catch(error) { alert(error.message); }
}

window.addEventListener('DOMContentLoaded', async () => {
  $('snapshotDate').textContent = new Date().toLocaleDateString(undefined,{weekday:'short',month:'short',day:'numeric',year:'numeric'});
  $('calculatorForm').addEventListener('submit',calculate);
  $('routeForm').addEventListener('submit',compareRoute);
  $('routineForm').addEventListener('submit',saveRoutine);
  $('billFile').addEventListener('change',uploadBill);
  $('foodFile').addEventListener('change',analyzeFood);
  $('recommendBtn').addEventListener('click',generateRecommendations);
  $('simulateBtn').addEventListener('click',simulate);
  $('clearHistoryBtn').addEventListener('click',clearHistory);
  $('refreshBtn').addEventListener('click',async()=>{await loadHistory();await loadRoutine();});
  await Promise.all([loadHistory(),loadRoutine()]);
});
