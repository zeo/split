const token = document.querySelector('meta[name="split-token"]')?.content ?? "";

async function request(method, url, body) {
  const headers = { "x-split-token": token };
  let payload = body;
  if (body && !(body instanceof FormData)) {
    headers["content-type"] = "application/json";
    payload = JSON.stringify(body);
  }
  const response = await fetch(url, { method, headers, body: payload });
  if (!response.ok) {
    const detail = await response.json().catch(() => ({}));
    throw new Error(detail.detail || `${response.status} ${response.statusText}`);
  }
  return response.json();
}

export const api = {
  get: (url) => request("GET", url),
  post: (url, body) => request("POST", url, body ?? {}),
  remove: (url) => request("DELETE", url),
};

// one stream carries every job, download and device update as a full snapshot
export function subscribe(onSnapshot) {
  let source;
  const open = () => {
    source = new EventSource("/api/events");
    source.onmessage = (event) => onSnapshot(JSON.parse(event.data));
    source.onerror = () => {
      source.close();
      setTimeout(open, 1500);
    };
  };
  open();
}

// pywebview injects window.pywebview after load; browser mode never has it
export function native() {
  return window.pywebview?.api ?? null;
}

export function whenNative(callback) {
  if (native()) callback(native());
  else window.addEventListener("pywebviewready", () => callback(native()), { once: true });
}
