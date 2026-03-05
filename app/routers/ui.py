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
      <tr><th>ID</th><th>Job</th><th>Type</th><th>Size</th><th>Download</th></tr>
    </thead>
    <tbody id="rows"></tbody>
  </table>

  <script>
    function authHeaders() {
      const token = localStorage.getItem('auth.access_token');
      return token ? { Authorization: `Bearer ${token}` } : {};
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

    async function loadAssets() {
      const res = await fetch('/api/assets', { headers: authHeaders() });
      const data = await res.json();
      const rows = document.getElementById('rows');
      rows.innerHTML = '';
      data.forEach(asset => {
        const tr = document.createElement('tr');
        tr.innerHTML = `
          <td>${asset.id}</td>
          <td>${asset.job_id}</td>
          <td>${asset.type}</td>
          <td>${asset.size_bytes}</td>
          <td><button data-download-id="${asset.id}">Download</button></td>
        `;
        rows.appendChild(tr);
      });
      rows.querySelectorAll('[data-download-id]').forEach((el) => {
        el.addEventListener('click', () => downloadAsset(el.dataset.downloadId));
      });
    }
    loadAssets();
  </script>
</body>
</html>
""")
