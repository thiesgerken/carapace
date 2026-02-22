const SERVER_KEY = "carapace_server";
const TOKEN_KEY = "carapace_token";

export function getServer(): string {
  if (typeof window === "undefined") return "";
  return localStorage.getItem(SERVER_KEY) ?? "";
}

export function getToken(): string {
  if (typeof window === "undefined") return "";
  return localStorage.getItem(TOKEN_KEY) ?? "";
}

export function saveConnection(server: string, token: string) {
  localStorage.setItem(SERVER_KEY, server);
  localStorage.setItem(TOKEN_KEY, token);
}

export function clearConnection() {
  localStorage.removeItem(SERVER_KEY);
  localStorage.removeItem(TOKEN_KEY);
}

export function hasConnection(): boolean {
  return !!getServer() && !!getToken();
}
