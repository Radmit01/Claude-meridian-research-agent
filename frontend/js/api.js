// API client — the single place the frontend talks to the backend.
// Every endpoint in server/routers/ has a matching function here.

export class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status;
  }
}

async function request(path, { method = "GET", body, headers, raw = false } = {}) {
  const init = { method, headers: { ...(headers || {}) } };
  if (body !== undefined) {
    init.body = JSON.stringify(body);
    init.headers["Content-Type"] = "application/json";
  }
  const res = await fetch(path, init);
  if (!res.ok) throw await toError(res);
  if (raw) return res.text();
  const ct = res.headers.get("content-type") || "";
  return ct.includes("json") ? res.json() : res.text();
}

async function toError(res) {
  let msg = `${res.status} ${res.statusText}`;
  try {
    const j = await res.json();
    if (typeof j.detail === "string") msg = j.detail;
    else if (Array.isArray(j.detail)) msg = j.detail.map((d) => d.msg).join("; ");
  } catch (_) {}
  return new ApiError(msg, res.status);
}

// Raw-body upload with progress (XHR: fetch has no upload progress events).
function uploadFile(path, file, params, onProgress) {
  const qs = new URLSearchParams({ filename: file.name });
  Object.entries(params || {}).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== "") qs.set(k, v);
  });
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${path}?${qs}`);
    xhr.setRequestHeader("Content-Type", "application/octet-stream");
    xhr.upload.onprogress = (e) => e.lengthComputable && onProgress && onProgress(e.loaded / e.total);
    xhr.onload = () => {
      let data = null;
      try { data = JSON.parse(xhr.responseText); } catch (_) {}
      if (xhr.status >= 200 && xhr.status < 300) return resolve(data);
      const msg = data && typeof data.detail === "string" ? data.detail : `${xhr.status} ${xhr.statusText}`;
      reject(new ApiError(msg, xhr.status));
    };
    xhr.onerror = () => reject(new ApiError("Network error during upload", 0));
    xhr.send(file);
  });
}

const enc = encodeURIComponent;

export const api = {
  overview: () => request("/api/overview"),
  health: () => request("/api/health"),
  questions: () => request("/api/questions"),

  packs: {
    list: () => request("/api/packs"),
    get: (name) => request(`/api/packs/${enc(name)}`),
    raw: (name) => request(`/api/packs/${enc(name)}/raw`, { raw: true }),
    rawUrl: (name) => `/api/packs/${enc(name)}/raw`,
    import: (file, onProgress) => uploadFile("/api/packs/upload", file, {}, onProgress),
    remove: (name) => request(`/api/packs/${enc(name)}`, { method: "DELETE" }),
  },

  corpus: {
    list: () => request("/api/corpus"),
    get: (docId) => request(`/api/corpus/${enc(docId)}`),
    fileUrl: (docId) => `/api/corpus/${enc(docId)}/file`,
    sync: (force = false) => request("/api/corpus/sync", { method: "POST", body: { force } }),
    /** mode: "new" | "replace"; for new pass setKey (CL|EX|PV), optional docId + title. */
    upload: ({ file, mode, docId, title, setKey }, onProgress) =>
      uploadFile("/api/corpus/upload", file, { mode, doc_id: docId, title, set_key: setKey }, onProgress),
    restore: (docId) => request(`/api/corpus/${enc(docId)}/restore`, { method: "POST" }),
    remove: (docId) => request(`/api/corpus/${enc(docId)}`, { method: "DELETE" }),
  },

  runs: {
    list: () => request("/api/runs"),
    get: (id) => request(`/api/runs/${enc(id)}`),
    start: (question) => request("/api/runs", { method: "POST", body: { question } }),
    cancel: (id) => request(`/api/runs/${enc(id)}/cancel`, { method: "POST" }),
    /** Server-sent events. handlers: { log(ev), state(snapshot), end() }. Returns close(). */
    stream: (id, since, handlers) => {
      const es = new EventSource(`/api/runs/${enc(id)}/stream?since=${since || 0}`);
      es.addEventListener("log", (e) => handlers.log && handlers.log(JSON.parse(e.data)));
      es.addEventListener("state", (e) => handlers.state && handlers.state(JSON.parse(e.data)));
      es.addEventListener("end", () => { es.close(); handlers.end && handlers.end(); });
      es.onerror = () => {};
      return () => es.close();
    },
  },
};
