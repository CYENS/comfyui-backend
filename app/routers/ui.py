from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter(prefix="/ui", tags=["ui"])


@router.get("", response_class=HTMLResponse)
def ui_index():
    return HTMLResponse("""
<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <title>ComfyUI Wrapper UI</title>
  <style>
    body { font-family: Arial, sans-serif; margin: 24px; }
    a { display: block; margin: 8px 0; }
    .crumbs a { display: inline; margin: 0; }
  </style>
</head>
<body>
  <div class="crumbs"><a href="/ui">Home</a></div>
  <h1>ComfyUI Wrapper</h1>
  <a href="/ui/auth">Auth</a>
  <a href="/ui/workflows">Workflows</a>
  <a href="/ui/builder/">Workflow Builder</a>
  <a href="/ui/builder/workflows">Workflow CRUD</a>
  <a href="/ui/jobs">Jobs</a>
  <a href="/ui/assets">Assets</a>
  <a href="/ui/admin">Model Requirements (Admin)</a>
</body>
</html>
""")


@router.get("/index", response_class=HTMLResponse)
def ui_index_alias():
    return ui_index()


@router.get("/auth", response_class=HTMLResponse)
def ui_auth():
    return HTMLResponse("""
<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <title>Auth</title>
  <style>
    body { font-family: Arial, sans-serif; margin: 24px; }
    .crumbs { margin-bottom: 12px; }
    .crumbs a { text-decoration: none; color: #0a58ca; }
    .row { margin: 10px 0; max-width: 380px; }
    .row label { display: block; margin-bottom: 4px; font-weight: bold; }
    .row input { width: 100%; box-sizing: border-box; padding: 8px; }
    button { margin-right: 8px; }
    pre { background: #f7f7f7; padding: 12px; border: 1px solid #ddd; }
  </style>
</head>
<body>
  <div class="crumbs"><a href="/ui">Home</a> / <a href="/ui/auth">Auth</a></div>
  <h1>Auth</h1>
  <div class="row">
    <label for="username">Username</label>
    <input id="username" value="admin" />
  </div>
  <div class="row">
    <label for="password">Password</label>
    <input id="password" type="password" value="change-me" />
  </div>
  <button id="loginBtn">Login</button>
  <button id="meBtn">Who Am I</button>
  <button id="logoutBtn">Logout</button>
  <pre id="result"></pre>
  <script>
    const ACCESS_KEY = 'auth.access_token';
    const REFRESH_KEY = 'auth.refresh_token';

    function authHeaders() {
      const token = localStorage.getItem(ACCESS_KEY);
      return token ? { Authorization: `Bearer ${token}` } : {};
    }

    async function login() {
      const username = document.getElementById('username').value.trim();
      const password = document.getElementById('password').value;
      const res = await fetch('/api/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, password })
      });
      const data = await res.json();
      if (!res.ok) {
        document.getElementById('result').textContent = JSON.stringify(data, null, 2);
        return;
      }
      localStorage.setItem(ACCESS_KEY, data.access_token);
      localStorage.setItem(REFRESH_KEY, data.refresh_token);
      document.getElementById('result').textContent = JSON.stringify(data, null, 2);
    }

    async function me() {
      const res = await fetch('/api/auth/me', { headers: authHeaders() });
      const data = await res.json();
      document.getElementById('result').textContent = JSON.stringify(data, null, 2);
    }

    async function logout() {
      const refreshToken = localStorage.getItem(REFRESH_KEY);
      if (refreshToken) {
        await fetch('/api/auth/logout', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ refresh_token: refreshToken })
        });
      }
      localStorage.removeItem(ACCESS_KEY);
      localStorage.removeItem(REFRESH_KEY);
      document.getElementById('result').textContent = JSON.stringify({ status: 'logged out' }, null, 2);
    }

    document.getElementById('loginBtn').addEventListener('click', login);
    document.getElementById('meBtn').addEventListener('click', me);
    document.getElementById('logoutBtn').addEventListener('click', logout);
  </script>
</body>
</html>
""")


@router.get("/workflows", response_class=HTMLResponse)
def ui_workflows():
    return HTMLResponse("""
<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <title>Workflows</title>
  <style>
    body { font-family: Arial, sans-serif; margin: 24px; }
    .crumbs { margin-bottom: 12px; }
    .crumbs a { text-decoration: none; color: #0a58ca; }
    .topbar { display: flex; gap: 8px; margin-bottom: 12px; }
    .layout { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
    table { border-collapse: collapse; width: 100%; }
    th, td { border: 1px solid #ccc; padding: 8px; text-align: left; }
    tr.active { background: #eef5ff; }
    button { margin: 4px; }
    .panel { border: 1px solid #ccc; padding: 12px; }
    .row { margin: 10px 0; }
    .row label { display: block; margin-bottom: 4px; font-weight: bold; }
    .row input, .row textarea { width: 100%; box-sizing: border-box; padding: 6px; }
    .row textarea { height: 90px; }
    .actions { margin-top: 12px; }
  </style>
</head>
<body>
  <div class="crumbs"><a href="/ui">Home</a> / <a href="/ui/workflows">Workflows</a></div>
  <h1>Workflows</h1>
  <div class="topbar">
    <button id="addWorkflowBtn">+ Add Workflow</button>
    <button id="refreshBtn">Refresh</button>
  </div>

  <div class="layout">
    <div class="panel">
      <table>
        <thead>
          <tr><th>Name</th><th>Key</th><th>Version</th><th>Owner</th></tr>
        </thead>
        <tbody id="workflowRows"></tbody>
      </table>
    </div>
    <div class="panel">
      <h2 id="selectedTitle">Select a workflow</h2>
      <div class="actions">
        <button id="newVersionBtn">Create New Version</button>
        <button id="duplicateBtn">Duplicate</button>
        <button id="editBtn">Edit</button>
        <button id="deleteBtn">Delete</button>
      </div>
      <div id="fields"></div>
      <div class="actions">
        <button id="runBtn">Run Workflow</button>
      </div>
      <pre id="result"></pre>
    </div>
  </div>

  <script>
    function authHeaders() {
      const token = localStorage.getItem('auth.access_token');
      return token ? { Authorization: `Bearer ${token}` } : {};
    }

    async function authFetch(url, options = {}) {
      const headers = { ...(options.headers || {}), ...authHeaders() };
      return fetch(url, { ...options, headers });
    }

    let workflows = [];
    let currentWorkflow = null;
    let currentVersion = null;

    function renderFields(inputs) {
      const container = document.getElementById('fields');
      container.innerHTML = '';
      inputs.forEach(input => {
        const row = document.createElement('div');
        row.className = 'row';
        const label = document.createElement('label');
        label.textContent = input.label || input.id;
        row.appendChild(label);

        let field;
        if (input.type === 'number') {
          field = document.createElement('input');
          field.type = 'number';
          field.value = input.default ?? '';
        } else if (input.type === 'boolean') {
          field = document.createElement('input');
          field.type = 'checkbox';
          field.checked = Boolean(input.default);
        } else {
          field = document.createElement('textarea');
          field.value = input.default ?? '';
        }
        field.id = `input_${input.id}`;
        row.appendChild(field);
        container.appendChild(row);
      });
    }

    async function loadWorkflowDetail(id) {
      const res = await authFetch(`/api/workflows/${id}`);
      const data = await res.json();
      currentWorkflow = data;
      currentVersion = (data.versions || []).find(v => v.id === data.current_version_id) || null;
      document.getElementById('selectedTitle').textContent = data.name || 'Workflow';
      renderFields((currentVersion && currentVersion.inputs_schema_json) || []);
      renderWorkflowTable();
    }

    function renderWorkflowTable() {
      const tbody = document.getElementById('workflowRows');
      tbody.innerHTML = '';
      workflows.forEach((wf) => {
        const tr = document.createElement('tr');
        if (currentWorkflow && currentWorkflow.id === wf.id) tr.className = 'active';
        tr.innerHTML = `
          <td>${wf.name || ''}</td>
          <td>${wf.key || ''}</td>
          <td>${wf.current_version_id ? 'v' + ((wf.versions_count || '') || '') : '-'}</td>
          <td>${wf.created_by_user_id || ''}</td>
        `;
        tr.addEventListener('click', () => loadWorkflowDetail(wf.id));
        tbody.appendChild(tr);
      });
    }

    async function loadWorkflows() {
      const res = await authFetch('/api/workflows');
      workflows = await res.json();
      renderWorkflowTable();
      if (workflows.length && !currentWorkflow) {
        await loadWorkflowDetail(workflows[0].id);
      }
    }

    async function runWorkflow() {
      if (!currentWorkflow || !currentVersion) return;
      const inputs = currentVersion.inputs_schema_json || [];
      const params = {};
      inputs.forEach(input => {
        const el = document.getElementById(`input_${input.id}`);
        if (!el) return;
        let value = el.value;
        if (input.type === 'number') value = Number(el.value);
        if (input.type === 'boolean') value = Boolean(el.checked);
        params[input.id] = value;
      });

      const res = await authFetch('/api/jobs', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ workflow_id: currentWorkflow.id, params })
      });
      const data = await res.json();
      document.getElementById('result').textContent = JSON.stringify(data, null, 2);
    }

    async function createNewVersion() {
      if (!currentWorkflow || !currentVersion) return;
      const changeNote = window.prompt('Change note for new version', 'UI version update') || 'UI version update';
      const payload = {
        prompt_json: currentVersion.prompt_json,
        inputs_schema_json: currentVersion.inputs_schema_json,
        change_note: changeNote
      };
      const res = await authFetch(`/api/workflows/${currentWorkflow.id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      const data = await res.json();
      document.getElementById('result').textContent = JSON.stringify(data, null, 2);
      await loadWorkflows();
      await loadWorkflowDetail(currentWorkflow.id);
    }

    async function deleteWorkflow() {
      if (!currentWorkflow) return;
      if (!window.confirm(`Delete workflow "${currentWorkflow.name}"?`)) return;
      const res = await authFetch(`/api/workflows/${currentWorkflow.id}`, { method: 'DELETE' });
      const data = await res.json();
      document.getElementById('result').textContent = JSON.stringify(data, null, 2);
      currentWorkflow = null;
      currentVersion = null;
      document.getElementById('selectedTitle').textContent = 'Select a workflow';
      document.getElementById('fields').innerHTML = '';
      await loadWorkflows();
    }

    async function duplicateWorkflow() {
      if (!currentWorkflow) return;
      const key = window.prompt('New workflow key', `${currentWorkflow.key}_copy`);
      if (!key) return;
      const name = window.prompt('New workflow name', `${currentWorkflow.name} Copy`);
      if (!name) return;
      const res = await authFetch(`/api/workflows/${currentWorkflow.id}/duplicate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ key, name })
      });
      const data = await res.json();
      document.getElementById('result').textContent = JSON.stringify(data, null, 2);
      await loadWorkflows();
    }

    document.getElementById('runBtn').addEventListener('click', runWorkflow);
    document.getElementById('newVersionBtn').addEventListener('click', createNewVersion);
    document.getElementById('deleteBtn').addEventListener('click', deleteWorkflow);
    document.getElementById('duplicateBtn').addEventListener('click', duplicateWorkflow);
    document.getElementById('editBtn').addEventListener('click', () => { window.location.href = '/ui/builder/workflows'; });
    document.getElementById('addWorkflowBtn').addEventListener('click', () => { window.location.href = '/ui/builder/'; });
    document.getElementById('refreshBtn').addEventListener('click', loadWorkflows);

    loadWorkflows();
  </script>
</body>
</html>
""")


@router.get("/jobs", response_class=HTMLResponse)
def ui_jobs():
    return HTMLResponse("""
<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <title>Jobs</title>
  <style>
    body { font-family: Arial, sans-serif; margin: 24px; }
    .crumbs { margin-bottom: 12px; }
    .crumbs a { text-decoration: none; color: #0a58ca; }
    table { border-collapse: collapse; width: 100%; }
    th, td { border: 1px solid #ccc; padding: 8px; text-align: left; }
  </style>
</head>
<body>
  <div class="crumbs"><a href="/ui">Home</a> / <a href="/ui/jobs">Jobs</a></div>
  <h1>Jobs</h1>
  <table>
    <thead>
      <tr><th>ID</th><th>Status</th><th>Workflow</th><th>Submitted</th></tr>
    </thead>
    <tbody id="rows"></tbody>
  </table>

  <script>
    function authHeaders() {
      const token = localStorage.getItem('auth.access_token');
      return token ? { Authorization: `Bearer ${token}` } : {};
    }

    async function loadJobs() {
      const res = await fetch('/api/jobs', { headers: authHeaders() });
      const data = await res.json();
      const rows = document.getElementById('rows');
      rows.innerHTML = '';
      data.forEach(job => {
        const tr = document.createElement('tr');
        tr.innerHTML = `
          <td>${job.id}</td>
          <td>${job.status}</td>
          <td>${job.workflow_id}</td>
          <td>${job.submitted_at}</td>
        `;
        rows.appendChild(tr);
      });
    }
    loadJobs();
  </script>
</body>
</html>
""")


@router.get("/assets", response_class=HTMLResponse)
def ui_assets():
    return HTMLResponse("""
<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <title>Assets</title>
  <style>
    body { font-family: Arial, sans-serif; margin: 24px; }
    .crumbs { margin-bottom: 12px; }
    .crumbs a { text-decoration: none; color: #0a58ca; }
    table { border-collapse: collapse; width: 100%; }
    th, td { border: 1px solid #ccc; padding: 8px; text-align: left; }
  </style>
</head>
<body>
  <div class="crumbs"><a href="/ui">Home</a> / <a href="/ui/assets">Assets</a></div>
  <h1>Assets</h1>
  <table>
    <thead>
      <tr><th>ID</th><th>Job</th><th>Type</th><th>Size</th><th>Status</th><th>Validated</th><th>Download</th></tr>
    </thead>
    <tbody id="rows"></tbody>
  </table>

  <script>
    let isModerator = false;

    function authHeaders() {
      const token = localStorage.getItem('auth.access_token');
      return token ? { Authorization: `Bearer ${token}` } : {};
    }

    async function loadMe() {
      const res = await fetch('/api/auth/me', { headers: authHeaders() });
      if (!res.ok) return;
      const me = await res.json();
      const roles = me.roles || [];
      isModerator = roles.includes('moderator') || roles.includes('admin');
    }

    async function downloadAsset(assetId) {
      const res = await fetch(`/api/assets/${assetId}/download`, { headers: authHeaders() });
      if (!res.ok) {
        alert(`Download failed: ${res.status}`);
        return;
      }
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = assetId;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    }

    async function setValidation(assetId, checked) {
      if (!isModerator) return;
      const payload = {
        status: checked ? 'APPROVED' : 'REJECTED',
        notes: checked ? 'Validated from moderator table' : 'Rejected from moderator table'
      };
      const res = await fetch(`/api/assets/${assetId}/review`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify(payload),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        alert(`Validation failed: ${res.status} ${err.detail || ''}`);
      }
      await loadAssets();
    }

    async function loadAssets() {
      const res = await fetch('/api/assets?mine=false', { headers: authHeaders() });
      const data = await res.json();
      const rows = document.getElementById('rows');
      rows.innerHTML = '';
      data.forEach(asset => {
        const isApproved = asset.validation_status === 'APPROVED';
        const tr = document.createElement('tr');
        tr.innerHTML = `
          <td>${asset.id}</td>
          <td>${asset.job_id}</td>
          <td>${asset.type}</td>
          <td>${asset.size_bytes}</td>
          <td>${asset.validation_status || 'PENDING'}</td>
          <td>
            <input type="checkbox" data-validate-id="${asset.id}" ${isApproved ? 'checked' : ''} ${isModerator ? '' : 'disabled'} />
          </td>
          <td><button data-download-id="${asset.id}">Download</button></td>
        `;
        rows.appendChild(tr);
      });
      rows.querySelectorAll('[data-download-id]').forEach((el) => {
        el.addEventListener('click', () => downloadAsset(el.dataset.downloadId));
      });
      rows.querySelectorAll('[data-validate-id]').forEach((el) => {
        el.addEventListener('change', () => setValidation(el.dataset.validateId, el.checked));
      });
    }
    loadMe().then(loadAssets);
  </script>
</body>
</html>
""")


@router.get("/admin", response_class=HTMLResponse)
def ui_admin():
    return HTMLResponse("""
<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <title>Model Requirements Admin</title>
  <style>
    body { font-family: Arial, sans-serif; margin: 24px; }
    .crumbs { margin-bottom: 12px; }
    .crumbs a { text-decoration: none; color: #0a58ca; }
    h2 { margin-top: 28px; border-bottom: 1px solid #ccc; padding-bottom: 6px; }
    table { border-collapse: collapse; width: 100%; margin-top: 10px; font-size: 13px; }
    th, td { border: 1px solid #ccc; padding: 7px 10px; text-align: left; vertical-align: top; }
    th { background: #f0f0f0; }
    tr.available td:first-child { border-left: 3px solid #2e7d32; }
    tr.missing td:first-child { border-left: 3px solid #c62828; }
    tr.unknown td:first-child { border-left: 3px solid #999; }
    .badge { display: inline-block; padding: 2px 7px; border-radius: 10px; font-size: 11px; font-weight: bold; }
    .badge.ok { background: #c8e6c9; color: #1b5e20; }
    .badge.missing { background: #ffcdd2; color: #b71c1c; }
    .badge.approved { background: #bbdefb; color: #0d47a1; }
    .badge.pending { background: #fff9c4; color: #f57f17; }
    .badge.unknown { background: #eeeeee; color: #555; }
    button { padding: 4px 10px; cursor: pointer; }
    button:disabled { opacity: 0.4; cursor: default; }
    .url-input { width: 340px; padding: 3px; font-size: 12px; }
    select { padding: 5px; font-size: 14px; }
    .topbar { margin-bottom: 14px; display: flex; gap: 8px; align-items: center; }
    pre.msg { background: #f5f5f5; border: 1px solid #ddd; padding: 10px; margin-top: 10px; font-size: 12px; white-space: pre-wrap; max-height: 200px; overflow: auto; }
  </style>
</head>
<body>
  <div class="crumbs"><a href="/ui">Home</a> / <a href="/ui/admin">Model Requirements Admin</a></div>
  <h1>Model Requirements Admin</h1>

  <!-- ── Section 1: Pending approval queue ── -->
  <h2>Pending URL Approvals</h2>
  <div class="topbar">
    <button id="refreshPendingBtn">Refresh</button>
  </div>
  <table id="pendingTable">
    <thead>
      <tr>
        <th>Workflow</th>
        <th>Model</th>
        <th>Folder / Type</th>
        <th>Download URL</th>
        <th>Actions</th>
      </tr>
    </thead>
    <tbody id="pendingRows"><tr><td colspan="5">Loading…</td></tr></tbody>
  </table>

  <!-- ── Section 2: Per-workflow requirements ── -->
  <h2>Requirements by Workflow</h2>
  <div class="topbar">
    <select id="workflowSelect"><option value="">— select workflow —</option></select>
    <button id="checkReqBtn">Check Availability</button>
  </div>
  <table id="reqTable">
    <thead>
      <tr>
        <th>Model</th>
        <th>Folder / Type</th>
        <th>Available</th>
        <th>URL</th>
        <th>Approved</th>
        <th>Actions</th>
      </tr>
    </thead>
    <tbody id="reqRows"><tr><td colspan="6">Select a workflow above.</td></tr></tbody>
  </table>

  <pre class="msg" id="msg"></pre>

<script>
function authHeaders() {
  const token = localStorage.getItem('auth.access_token');
  return token ? { Authorization: `Bearer ${token}` } : {};
}

async function authFetch(url, options = {}) {
  const headers = { ...(options.headers || {}), ...authHeaders() };
  return fetch(url, { ...options, headers });
}

function log(obj) {
  document.getElementById('msg').textContent = typeof obj === 'string'
    ? obj
    : JSON.stringify(obj, null, 2);
}

// ── Pending table ──────────────────────────────────────────────

async function loadPending() {
  document.getElementById('pendingRows').innerHTML = '<tr><td colspan="5">Loading…</td></tr>';
  const res = await authFetch('/api/admin/model-requirements/pending');
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    document.getElementById('pendingRows').innerHTML =
      `<tr><td colspan="5" style="color:red">Error ${res.status}: ${err.detail || ''}</td></tr>`;
    return;
  }
  const items = await res.json();
  const tbody = document.getElementById('pendingRows');
  tbody.innerHTML = '';
  if (!items.length) {
    tbody.innerHTML = '<tr><td colspan="5">No pending approvals.</td></tr>';
    return;
  }
  items.forEach(item => {
    const tr = document.createElement('tr');
    tr.dataset.id = item.id;
    tr.innerHTML = `
      <td><strong>${escHtml(item.workflow_name)}</strong><br><small>${escHtml(item.workflow_key)}</small></td>
      <td>${escHtml(item.model_name)}</td>
      <td>${escHtml(item.folder)}<br><small>${escHtml(item.model_type)}</small></td>
      <td><a href="${escHtml(item.download_url)}" target="_blank" style="word-break:break-all;font-size:11px">${escHtml(item.download_url)}</a></td>
      <td>
        <button data-approve="${item.id}">Approve</button>
        <button data-reject="${item.id}">Reject</button>
        <button data-download="${item.id}">Download</button>
      </td>
    `;
    tbody.appendChild(tr);
  });

  tbody.querySelectorAll('[data-approve]').forEach(btn =>
    btn.addEventListener('click', () => approve(btn.dataset.approve)));
  tbody.querySelectorAll('[data-reject]').forEach(btn =>
    btn.addEventListener('click', () => reject(btn.dataset.reject)));
  tbody.querySelectorAll('[data-download]').forEach(btn =>
    btn.addEventListener('click', () => triggerDownload(btn.dataset.download)));
}

async function approve(id) {
  const res = await authFetch(`/api/admin/model-requirements/${id}/approve`, { method: 'POST' });
  const data = await res.json();
  log(data);
  await loadPending();
  await reloadCurrentWorkflowReqs();
}

async function reject(id) {
  if (!confirm('Clear the download URL and reset approval?')) return;
  const res = await authFetch(`/api/admin/model-requirements/${id}/reject`, { method: 'POST' });
  const data = await res.json();
  log(data);
  await loadPending();
  await reloadCurrentWorkflowReqs();
}

async function triggerDownload(id) {
  if (!confirm('Trigger server-side download from the approved URL?')) return;
  const res = await authFetch(`/api/admin/model-requirements/${id}/download`, { method: 'POST' });
  const data = await res.json();
  log(data);
}

// ── Workflow requirements ──────────────────────────────────────

let currentWorkflowId = null;

async function loadWorkflows() {
  const res = await authFetch('/api/workflows');
  const workflows = await res.json();
  const sel = document.getElementById('workflowSelect');
  workflows.forEach(wf => {
    const opt = document.createElement('option');
    opt.value = wf.id;
    opt.textContent = `${wf.name} (${wf.key})`;
    sel.appendChild(opt);
  });
}

async function loadWorkflowRequirements(workflowId) {
  currentWorkflowId = workflowId;
  const tbody = document.getElementById('reqRows');
  tbody.innerHTML = '<tr><td colspan="6">Loading…</td></tr>';
  const res = await authFetch(`/api/workflows/${workflowId}/requirements`);
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    tbody.innerHTML = `<tr><td colspan="6" style="color:red">Error ${res.status}: ${JSON.stringify(err.detail || err)}</td></tr>`;
    return;
  }
  const data = await res.json();
  renderRequirements(data.requirements);
  log({ all_available: data.all_available, missing_count: data.missing.length });
}

function renderRequirements(reqs) {
  const tbody = document.getElementById('reqRows');
  tbody.innerHTML = '';
  if (!reqs.length) {
    tbody.innerHTML = '<tr><td colspan="6">No model requirements for this workflow.</td></tr>';
    return;
  }
  reqs.forEach(req => {
    const avClass = req.available === true ? 'available' : req.available === false ? 'missing' : 'unknown';
    const avBadge = req.available === true
      ? '<span class="badge ok">Available</span>'
      : req.available === false
        ? '<span class="badge missing">Missing</span>'
        : '<span class="badge unknown">Unknown</span>';
    const approvedBadge = req.url_approved
      ? `<span class="badge approved">Approved</span><br><small>${escHtml(req.approved_by_username || '')}</small>`
      : req.download_url
        ? '<span class="badge pending">Pending</span>'
        : '—';

    const tr = document.createElement('tr');
    tr.className = avClass;
    tr.dataset.id = req.id;
    tr.innerHTML = `
      <td>${escHtml(req.model_name)}</td>
      <td>${escHtml(req.folder)}<br><small>${escHtml(req.model_type)}</small></td>
      <td>${avBadge}</td>
      <td>
        <input class="url-input" data-url-for="${req.id}"
               value="${escHtml(req.download_url || '')}"
               placeholder="https://huggingface.co/…" />
        <br>
        <button data-set-url="${req.id}" style="margin-top:4px">Set URL</button>
      </td>
      <td>${approvedBadge}</td>
      <td>
        <button data-approve="${req.id}" ${!req.download_url ? 'disabled' : ''}>Approve</button>
        <button data-reject="${req.id}" ${!req.download_url && !req.url_approved ? 'disabled' : ''}>Reject</button>
        <button data-download="${req.id}" ${!req.url_approved ? 'disabled' : ''}>Download</button>
      </td>
    `;
    tbody.appendChild(tr);
  });

  tbody.querySelectorAll('[data-set-url]').forEach(btn => {
    btn.addEventListener('click', async () => {
      const id = btn.dataset.setUrl;
      const url = tbody.querySelector(`[data-url-for="${id}"]`).value.trim();
      await setUrl(id, url);
    });
  });
  tbody.querySelectorAll('[data-approve]').forEach(btn =>
    btn.addEventListener('click', () => approve(btn.dataset.approve)));
  tbody.querySelectorAll('[data-reject]').forEach(btn =>
    btn.addEventListener('click', () => reject(btn.dataset.reject)));
  tbody.querySelectorAll('[data-download]').forEach(btn =>
    btn.addEventListener('click', () => triggerDownload(btn.dataset.download)));
}

async function setUrl(reqId, url) {
  if (!url) return alert('Enter a URL first.');
  const res = await authFetch(`/api/workflows/${currentWorkflowId}/requirements/${reqId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ download_url: url }),
  });
  const data = await res.json();
  log(data);
  if (res.ok) {
    await loadWorkflowRequirements(currentWorkflowId);
    await loadPending();
  }
}

async function reloadCurrentWorkflowReqs() {
  if (currentWorkflowId) await loadWorkflowRequirements(currentWorkflowId);
}

function escHtml(str) {
  return String(str ?? '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

// ── Init ──────────────────────────────────────────────────────

document.getElementById('refreshPendingBtn').addEventListener('click', loadPending);

document.getElementById('workflowSelect').addEventListener('change', async function() {
  if (this.value) await loadWorkflowRequirements(this.value);
});

document.getElementById('checkReqBtn').addEventListener('click', async () => {
  const id = document.getElementById('workflowSelect').value;
  if (id) await loadWorkflowRequirements(id);
});

loadPending();
loadWorkflows();
</script>
</body>
</html>
""")
