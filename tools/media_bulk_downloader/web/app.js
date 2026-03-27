const urlsInput = document.getElementById('urlsInput');
const runBtn = document.getElementById('runBtn');
const loadSampleBtn = document.getElementById('loadSampleBtn');
const openOutputBtn = document.getElementById('openOutputBtn');
const rerunFailedBtn = document.getElementById('rerunFailedBtn');
const statusBadge = document.getElementById('statusBadge');
const outputDir = document.getElementById('outputDir');
const resultsList = document.getElementById('resultsList');
const sumTotal = document.getElementById('sumTotal');
const sumSuccess = document.getElementById('sumSuccess');
const sumFailed = document.getElementById('sumFailed');
const sumSkipped = document.getElementById('sumSkipped');

function setStatus(status) {
  statusBadge.textContent = status;
  statusBadge.className = `badge ${status}`;
}

function renderResults(results = []) {
  if (!results.length) {
    resultsList.innerHTML = '<div class="result-item"><div class="result-url">还没有运行记录。</div></div>';
    return;
  }
  resultsList.innerHTML = results.map(item => `
    <article class="result-item">
      <div class="result-top">
        <div>
          <div class="result-platform">${item.platform}</div>
          <div class="result-url">${item.source_url}</div>
        </div>
        <strong class="result-status ${item.status}">${item.status}</strong>
      </div>
      ${item.file_path ? `<div class="result-file">${item.file_path}</div>` : ''}
      ${item.error ? `<div class="result-error">${item.error}</div>` : ''}
    </article>
  `).join('');
}

function updateSummary(summary) {
  sumTotal.textContent = summary?.total ?? '-';
  sumSuccess.textContent = summary?.success ?? '-';
  sumFailed.textContent = summary?.failed ?? '-';
  sumSkipped.textContent = summary?.skipped ?? '-';
}

function applyRunData(data) {
  setStatus(data.status || 'done');
  updateSummary(data.summary);
  outputDir.textContent = data.output_dir || '-';
  renderResults(data.results || []);
}

async function loadStatus() {
  const res = await fetch('/api/status');
  const data = await res.json();
  applyRunData(data);
}

async function postJson(url, payload = {}) {
  const res = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  });
  const data = await res.json();
  if (!res.ok) {
    throw new Error(data.error || '请求失败');
  }
  return data;
}

runBtn.addEventListener('click', async () => {
  const urls = urlsInput.value.trim();
  if (!urls) {
    alert('先贴链接。');
    return;
  }
  try {
    setStatus('running');
    runBtn.disabled = true;
    runBtn.textContent = 'Running...';
    resultsList.innerHTML = '<div class="result-item"><div class="result-url">任务执行中，请稍等…</div></div>';
    const data = await postJson('/api/run', { urls });
    applyRunData({ ...data, status: 'done' });
  } catch (err) {
    setStatus('error');
    alert(err.message || '执行失败');
  } finally {
    runBtn.disabled = false;
    runBtn.textContent = 'Start Download';
  }
});

rerunFailedBtn.addEventListener('click', async () => {
  try {
    setStatus('running');
    const data = await postJson('/api/rerun-failed');
    applyRunData({ ...data, status: 'done' });
  } catch (err) {
    setStatus('error');
    alert(err.message || '重跑失败');
  }
});

openOutputBtn.addEventListener('click', async () => {
  try {
    await postJson('/api/open-output');
  } catch (err) {
    alert(err.message || '打开目录失败');
  }
});

loadSampleBtn.addEventListener('click', () => {
  urlsInput.value = [
    'https://www.instagram.com/reel/DOz-9tTkoXx/?igsh=cjVsdmUyNjRrcmJm',
    'https://www.instagram.com/reel/DVyGvtmD0Ba/?igsh=aW84b2F5NWxmeWVy',
    'https://www.tiktok.com/@saitamasuhesaa/video/7620009482332032277'
  ].join('\n');
});

loadStatus();
