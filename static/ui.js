// Same-origin requests with a session-bound CSRF token on mutations.
function apiFetch(url, options = {}) {
  const headers = new Headers(options.headers || {});
  if (!['GET', 'HEAD', 'OPTIONS'].includes((options.method || 'GET').toUpperCase())) {
    headers.set('X-CSRF-Token', document.querySelector('meta[name="csrf-token"]').content);
  }
  return fetch(url, {...options, headers, credentials: 'same-origin'});
}
