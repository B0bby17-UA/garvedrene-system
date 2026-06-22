const API_BASE = "/api";

function getToken() { return localStorage.getItem("aptidao_token"); }
function setToken(t) { localStorage.setItem("aptidao_token", t); }
function clearToken() { localStorage.removeItem("aptidao_token"); }
function getUser() {
  try { return JSON.parse(localStorage.getItem("aptidao_user")); } catch { return null; }
}
function setUser(u) { localStorage.setItem("aptidao_user", JSON.stringify(u)); }
function clearUser() { localStorage.removeItem("aptidao_user"); }
function isLoggedIn() { return !!getToken(); }
function logout() { clearToken(); clearUser(); window.location.href = "/"; }

async function api(path, options = {}) {
  const token = getToken();
  const headers = { "Content-Type": "application/json", ...options.headers };
  if (token) headers["Authorization"] = `Bearer ${token}`;
  const res = await fetch(`${API_BASE}${path}`, { ...options, headers });
  if (res.status === 401 && path !== "/auth/login" && path !== "/auth/register") {
    logout();
    return null;
  }
  return res.json();
}
