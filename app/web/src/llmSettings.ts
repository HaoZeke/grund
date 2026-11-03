export type LlmSettings = { base: string; key: string; model: string; remember: boolean };

const STORE_KEY = "grund.extrapolate.llm";
const EMPTY: LlmSettings = { base: "", key: "", model: "", remember: false };

type Stores = { session: Storage; local: Storage };

function browserStores(): Stores | null {
  try {
    return { session: window.sessionStorage, local: window.localStorage };
  } catch {
    return null;
  }
}

function parse(raw: string | null): Omit<LlmSettings, "remember"> | null {
  if (!raw) return null;
  try {
    const value = JSON.parse(raw) as Partial<LlmSettings>;
    return { base: String(value.base || ""), key: String(value.key || ""), model: String(value.model || "") };
  } catch {
    return null;
  }
}

export function loadSettings(stores: Stores | null = browserStores()): LlmSettings {
  if (!stores) return { ...EMPTY };
  const local = parse(stores.local.getItem(STORE_KEY));
  if (local) return { ...local, remember: true };
  const session = parse(stores.session.getItem(STORE_KEY));
  return session ? { ...session, remember: false } : { ...EMPTY };
}

export function saveSettings(settings: LlmSettings, stores: Stores | null = browserStores()): void {
  if (!stores) return;
  const value = JSON.stringify({ base: settings.base.trim(), key: settings.key.trim(), model: settings.model.trim() });
  const [keep, drop] = settings.remember ? [stores.local, stores.session] : [stores.session, stores.local];
  drop.removeItem(STORE_KEY);
  if (isEmpty(settings)) keep.removeItem(STORE_KEY);
  else keep.setItem(STORE_KEY, value);
}

export function clearSettings(stores: Stores | null = browserStores()): void {
  if (!stores) return;
  stores.session.removeItem(STORE_KEY);
  stores.local.removeItem(STORE_KEY);
}

export function isEmpty(settings: LlmSettings): boolean {
  return !settings.base.trim() && !settings.key.trim() && !settings.model.trim();
}

export function secureContext(): boolean {
  try {
    return window.isSecureContext === true;
  } catch {
    return false;
  }
}

/** No model setting leaves a page that is not a secure context: over plain
 * http the key would travel in cleartext. */
export function settingsHeaders(settings: LlmSettings, secure: boolean = secureContext()): Record<string, string> {
  const headers: Record<string, string> = {};
  if (!secure) return headers;
  if (settings.base.trim()) headers["X-Grund-LLM-Base"] = settings.base.trim();
  if (settings.key.trim()) headers["X-Grund-LLM-Key"] = settings.key.trim();
  if (settings.model.trim()) headers["X-Grund-LLM-Model"] = settings.model.trim();
  return headers;
}
