from flask import Flask, Response

app = Flask(__name__)


@app.get("/")
def index():
    html = """
<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <title>Workflow Builder</title>
  <style>
    body { font-family: Arial, sans-serif; margin: 24px; }
    .crumbs { margin-bottom: 12px; }
    .crumbs a { text-decoration: none; color: #0a58ca; }
    label { display: block; margin-top: 12px; font-weight: bold; }
    input, textarea, select, button { width: 520px; margin-top: 6px; padding: 6px; }
    textarea { height: 120px; }
    .section { margin-top: 24px; }
    .candidate { border: 1px solid #ddd; padding: 8px; margin: 8px 0; }
    .row { display: flex; gap: 8px; align-items: center; }
    .row input { width: auto; }
    .row .wide { width: 260px; }
  </style>
</head>
<body>
  <div class="crumbs"><a href="/ui">Home</a> / <a href="/ui/builder/">Builder</a></div>
  <h1>Workflow Builder</h1>
  <p><a href="/ui/builder/workflows">Workflow CRUD</a></p>

  <div class="section">
    <label>Workflow JSON (API format — required)</label>
    <textarea id="promptJson" placeholder='Paste ComfyUI API-format prompt JSON here'></textarea>
    <button id="parse">Parse Prompt</button>

    <label style="margin-top:16px">UI Workflow JSON (optional — for model URL extraction)</label>
    <small style="display:block;margin-bottom:4px;color:#555">
      Export from ComfyUI using <em>Save (UI format)</em> instead of <em>Save (API format)</em>.
      Enables automatic extraction of HuggingFace / Civitai download URLs embedded by ComfyUI.
    </small>
    <textarea id="uiJson" placeholder='Paste ComfyUI UI-format workflow JSON here (optional)'></textarea>
  </div>

  <div class="section">
    <label>Key</label>
    <input id="key" placeholder="text_to_audio" />

    <label>Name</label>
    <input id="name" placeholder="Text to Audio" />

    <label>Description</label>
    <textarea id="description" placeholder="Optional"></textarea>
  </div>

  <div class="section">
    <h2>Candidate Inputs</h2>
    <div id="candidates"></div>
  </div>

  <div class="section">
    <button id="save">Save Workflow</button>
    <pre id="result"></pre>
  </div>

<script src="/ui/shared.js"></script>
<script>
let promptJson = null;
let candidates = [];


function renderCandidates() {
  const el = document.getElementById('candidates');
  el.innerHTML = '';
  candidates.forEach((c, idx) => {
    const div = document.createElement('div');
    div.className = 'candidate';
    div.innerHTML = `
      <div class="row">
        <input type="checkbox" id="enable_${idx}" />
        <strong>${c.node_type || 'Node'} #${c.node_id}</strong>
        <span>${c.path}</span>
      </div>
      <div class="row">
        <label>Label</label>
        <input class="wide" id="label_${idx}" value="${c.path}" />
      </div>
      <div class="row">
        <label>Required</label>
        <input type="checkbox" id="required_${idx}" />
      </div>
      <div class="row">
        <label>Default</label>
        <input class="wide" id="default_${idx}" value="${c.default ?? ''}" />
      </div>
    `;
    el.appendChild(div);
  });
}

async function parsePrompt() {
  if (!promptJson) return;
  const res = await authFetch('/api/workflows/parse', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ prompt_json: promptJson })
  });
  const data = await res.json();
  candidates = data.candidate_inputs || [];
  renderCandidates();
}

function buildInputsSchema() {
  const inputs = [];
  candidates.forEach((c, idx) => {
    const enabled = document.getElementById(`enable_${idx}`).checked;
    if (!enabled) return;
    const label = document.getElementById(`label_${idx}`).value.trim() || c.path;
    const required = document.getElementById(`required_${idx}`).checked;
    const defaultValue = document.getElementById(`default_${idx}`).value;

    inputs.push({
      id: `${c.node_id}_${c.path.replace('.', '_')}`,
      label,
      type: c.value_type,
      required,
      default: defaultValue,
      mapping: [{ node_id: c.node_id, path: c.path }]
    });
  });
  return inputs;
}

async function saveWorkflow() {
  const key = document.getElementById('key').value.trim();
  const name = document.getElementById('name').value.trim();
  const description = document.getElementById('description').value.trim();

  if (!key || !name || !promptJson) {
    alert('Missing required fields or prompt JSON');
    return;
  }

  let uiJson = null;
  const rawUiJson = document.getElementById('uiJson').value.trim();
  if (rawUiJson) {
    try {
      uiJson = JSON.parse(rawUiJson);
    } catch (e) {
      alert('UI JSON is not valid JSON: ' + e.message);
      return;
    }
  }

  const inputs_schema = buildInputsSchema();
  const payload = {
    key,
    name,
    description,
    prompt_json: promptJson,
    inputs_schema_json: inputs_schema,
    ...(uiJson !== null && { ui_json: uiJson }),
  };

  const res = await authFetch('/api/workflows', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  });
  const data = await res.json();
  document.getElementById('result').textContent = JSON.stringify(data, null, 2);
}

document.getElementById('parse').addEventListener('click', async () => {
  const raw = document.getElementById('promptJson').value.trim();
  if (!raw) return alert('Paste a prompt JSON first');
  promptJson = JSON.parse(raw);
  await parsePrompt();
});

document.getElementById('save').addEventListener('click', saveWorkflow);
</script>

</body>
</html>
"""
    return Response(html, mimetype="text/html")


@app.get("/workflows")
def workflows_crud():
    html = """
<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <title>Workflow CRUD</title>
  <style>
    body { font-family: Arial, sans-serif; margin: 24px; }
    .crumbs { margin-bottom: 12px; }
    .crumbs a { text-decoration: none; color: #0a58ca; }
    table { border-collapse: collapse; width: 100%; margin-top: 12px; }
    th, td { border: 1px solid #ccc; padding: 8px; text-align: left; }
    input, textarea, button { width: 520px; margin-top: 6px; padding: 6px; }
    textarea { height: 120px; }
    .row { margin-top: 12px; }
    .actions button { width: auto; margin-right: 8px; }
  </style>
</head>
<body>
  <div class="crumbs"><a href="/ui">Home</a> / <a href="/ui/builder/">Builder</a> / <a href="/ui/builder/workflows">Workflow CRUD</a></div>
  <h1>Workflow CRUD</h1>
  <p><a href="/ui/builder/">Workflow Builder</a></p>

  <div class="row">
    <button id="refresh">Refresh</button>
  </div>

  <table>
    <thead>
      <tr>
        <th>ID</th>
        <th>Key</th>
        <th>Name</th>
        <th>Active</th>
        <th>Actions</th>
      </tr>
    </thead>
    <tbody id="rows"></tbody>
  </table>

  <h2 id="formTitle">Create / Edit Workflow</h2>
  <div class="row">
    <label>ID (for edit)</label>
    <input id="wf_id" placeholder="auto for create" />
  </div>
  <div class="row">
    <label>Key</label>
    <input id="key" placeholder="text_to_audio" />
  </div>
  <div class="row">
    <label>Name</label>
    <input id="name" placeholder="Text to Audio" />
  </div>
  <div class="row">
    <label>Description</label>
    <textarea id="description"></textarea>
  </div>
  <div class="row">
    <label>Prompt JSON</label>
    <textarea id="prompt_json" placeholder='{"1": {...}}'></textarea>
  </div>
  <div class="row">
    <label>Inputs Schema (JSON)</label>
    <textarea id="inputs_schema" placeholder='[{"id":"text","mapping":[...]}]'></textarea>
  </div>
  <div class="row">
    <label>UI Workflow JSON (optional — for model URL extraction)</label>
    <textarea id="ui_json" placeholder='Paste ComfyUI UI-format JSON here (optional)'></textarea>
  </div>
  <div class="row actions">
    <button id="create">Create</button>
    <button id="update">Update</button>
    <button id="delete">Delete</button>
  </div>
  <pre id="result"></pre>

<script src="/ui/shared.js"></script>
<script>

async function refreshList() {
  const res = await authFetch('/api/workflows');
  const data = await res.json();
  const rows = document.getElementById('rows');
  rows.innerHTML = '';
  data.forEach(wf => {
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td>${wf.id}</td>
      <td>${wf.key}</td>
      <td>${wf.name}</td>
      <td>${wf.is_active ?? true}</td>
      <td>
        <button onclick="loadWorkflow('${wf.id}')">Edit</button>
      </td>
    `;
    rows.appendChild(tr);
  });
}

async function loadWorkflow(id) {
  const res = await authFetch(`/api/workflows/${id}`);
  const wf = await res.json();
  document.getElementById('wf_id').value = wf.id;
  document.getElementById('key').value = wf.key || '';
  document.getElementById('name').value = wf.name || '';
  document.getElementById('description').value = wf.description || '';
  const currentVersion = (wf.versions || []).find(v => v.id === wf.current_version_id);
  document.getElementById('prompt_json').value = JSON.stringify((currentVersion && currentVersion.prompt_json) || {}, null, 2);
  document.getElementById('inputs_schema').value = JSON.stringify((currentVersion && currentVersion.inputs_schema_json) || [], null, 2);
}

function parseJsonField(id) {
  const raw = document.getElementById(id).value.trim();
  if (!raw) return null;
  return JSON.parse(raw);
}

async function createWorkflow() {
  const uiJson = parseJsonField('ui_json');
  const payload = {
    key: document.getElementById('key').value.trim(),
    name: document.getElementById('name').value.trim(),
    description: document.getElementById('description').value.trim(),
    prompt_json: parseJsonField('prompt_json') || {},
    inputs_schema_json: parseJsonField('inputs_schema') || [],
    ...(uiJson !== null && { ui_json: uiJson }),
  };
  const res = await authFetch('/api/workflows', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  });
  const data = await res.json();
  document.getElementById('result').textContent = JSON.stringify(data, null, 2);
  await refreshList();
}

async function updateWorkflow() {
  const id = document.getElementById('wf_id').value.trim();
  if (!id) return alert('Workflow ID required for update');
  const uiJson = parseJsonField('ui_json');
  const payload = {
    name: document.getElementById('name').value.trim(),
    description: document.getElementById('description').value.trim(),
    prompt_json: parseJsonField('prompt_json'),
    inputs_schema_json: parseJsonField('inputs_schema'),
    ...(uiJson !== null && { ui_json: uiJson }),
  };
  const res = await authFetch(`/api/workflows/${id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  });
  const data = await res.json();
  document.getElementById('result').textContent = JSON.stringify(data, null, 2);
  await refreshList();
}

async function deleteWorkflow() {
  const id = document.getElementById('wf_id').value.trim();
  if (!id) return alert('Workflow ID required for delete');
  const res = await authFetch(`/api/workflows/${id}`, { method: 'DELETE' });
  const data = await res.json();
  document.getElementById('result').textContent = JSON.stringify(data, null, 2);
  await refreshList();
}

document.getElementById('refresh').addEventListener('click', refreshList);
document.getElementById('create').addEventListener('click', createWorkflow);
document.getElementById('update').addEventListener('click', updateWorkflow);
document.getElementById('delete').addEventListener('click', deleteWorkflow);

refreshList();
</script>

</body>
</html>
"""
    return Response(html, mimetype="text/html")
