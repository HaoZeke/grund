import type { Language } from "./copy";

export type CellLabel = {
  variable?: string;
  variable_text?: string;
  label?: string;
  code?: string;
};

export type Cell = {
  key?: string[];
  labels?: CellLabel[];
  value?: string;
};

export type Source = {
  table_id?: string;
  title?: string;
  api_url?: string;
  web_url?: string;
  query?: unknown;
  retrieved_at?: string;
  table_updated?: string | null;
  cells?: Cell[];
  derived?: { name?: string; value?: string; formula?: string; inputs?: string[] } | null;
  footnotes?: { text?: string }[];
  preliminary?: boolean;
  revised?: boolean;
  operation?: string;
  notes?: string[];
};

const MONTHS: Record<Language, string[]> = {
  en: ["", "January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"],
  is: ["", "janúar", "febrúar", "mars", "apríl", "maí", "júní", "júlí", "ágúst", "september", "október", "nóvember", "desember"],
};

const TIME_NAME = /\b(year|years|month|months|quarter|quarters|time|period|ar|manudur|arsfjordungur|timabil)\b/;
const UNIT_NAME = /^(unit|eining)$/;
const TOTAL = /^(total|alls|samtals|all)$/;

export function formatStat(raw: string, language: Language): string {
  const text = String(raw ?? "").trim();
  if (!/^-?\d+(?:\.\d+)?$/.test(text)) return text;
  const neg = text.startsWith("-");
  const body = neg ? text.slice(1) : text;
  const [whole, fractionRaw = ""] = body.split(".");
  const fraction = fractionRaw.replace(/0+$/, "");
  const grouped = Number(whole).toLocaleString("en-US");
  const sign = neg ? "-" : "";
  if (language === "is") {
    const local = grouped.replace(/,/g, ".");
    return fraction ? `${sign}${local},${fraction}` : `${sign}${local}`;
  }
  return fraction ? `${sign}${grouped}.${fraction}` : `${sign}${grouped}`;
}

export function humanPeriod(code: string, language: Language): string {
  const text = (code || "").trim();
  const month = text.match(/^(\d{4})M(\d{2})$/i);
  if (month) {
    const name = MONTHS[language][Number(month[2])];
    if (name) return `${name} ${month[1]}`;
  }
  const quarter = text.match(/^(\d{4})Q([1-4])$/i);
  if (quarter) {
    return language === "is" ? `${quarter[2]}. ársfjórðungur ${quarter[1]}` : `Q${quarter[2]} ${quarter[1]}`;
  }
  return text;
}

function fold(value: string): string {
  return value
    .toLowerCase()
    .replace(/ð/g, "d")
    .replace(/þ/g, "th")
    .replace(/æ/g, "ae")
    .replace(/ö/g, "o")
    .replace(/á|é|í|ó|ú|ý/g, (letter) => ({ á: "a", é: "e", í: "i", ó: "o", ú: "u", ý: "y" })[letter] ?? letter);
}

export function humanTableUrl(apiUrl: string): string | null {
  const match = apiUrl.match(
    /^https:\/\/px\.hagstofa\.is\/(pxen|pxis)\/api\/v1\/(en|is)\/([^/]+)\/(.+)\/([^/]+\.px)$/i,
  );
  if (!match) return null;
  const [, edition, lang, db, middle, file] = match;
  const joined = middle.split("/").join("__");
  return `https://px.hagstofa.is/${edition}/pxweb/${lang}/${db}/${db}__${joined}/${file}`;
}

export type PartView = {
  figure: string;
  caption: string;
  tableId: string;
  title: string;
  period: string;
  unit: string;
  apiUrl: string;
  humanUrl: string | null;
  cells: Cell[];
  lead: string;
};

function lastWrittenNumber(text: string): string {
  const found = text.match(/\d{1,3}(?:[.\s\u00a0]\d{3})+(?:[.,]\d+)?|\d+(?:[.,]\d+)?/g);
  if (!found || found.length === 0) return "";
  return found[found.length - 1];
}

function periodFrom(chunk: string, language: Language): string {
  const match = chunk.match(/(?:period|tímabil)\s+([^.\n]+)/i);
  if (!match) return "";
  return humanPeriod(match[1].trim(), language);
}

export function answerParts(
  turn: {
    answer: string;
    value?: string | null;
    value_display?: string | null;
    table_id?: string | null;
    tables?: string[];
    operation?: string | null;
    source?: Source | null;
  },
  language: Language,
): PartView[] {
  const answer = turn.answer || "";
  const re = /(?:Table|Tafla)\s+([A-Za-z]{3}\d{4,5})[\s\S]*?(https:\/\/px\.hagstofa\.is\/\S+)/g;
  const matches = [...answer.matchAll(re)];
  const sourceId = (turn.source?.table_id || turn.table_id || "").replace(/\.px$/i, "");
  const views: PartView[] = [];
  let cursor = 0;
  if (matches.length === 0) {
    const api = turn.source?.web_url || turn.source?.api_url || "";
    views.push({
      figure: (turn.value_display || "").trim(),
      caption: "figure",
      tableId: sourceId,
      title: turn.source?.title || "",
      period: "",
      unit: "",
      apiUrl: api,
      humanUrl: api ? humanTableUrl(api) : null,
      cells: turn.source?.cells || [],
      lead: answer,
    });
    return decorate(views, turn, language);
  }
  matches.forEach((match, index) => {
    const start = match.index ?? 0;
    const lead = answer.slice(cursor, start);
    const tableId = match[1];
    const apiUrl = match[2];
    const same = tableId.toUpperCase() === sourceId.toUpperCase();
    const figure = index === 0 && turn.value_display && turn.operation !== "ratio"
      ? turn.value_display
      : lastWrittenNumber(lead);
    views.push({
      figure,
      caption: "figure",
      tableId,
      title: same ? turn.source?.title || "" : "",
      period: periodFrom(match[0], language),
      unit: "",
      apiUrl,
      humanUrl: humanTableUrl(apiUrl),
      cells: same ? turn.source?.cells || [] : [],
      lead,
    });
    cursor = start + match[0].length;
  });
  return decorate(views, turn, language);
}

function decorate(
  views: PartView[],
  turn: { source?: Source | null; operation?: string | null; value_display?: string | null },
  language: Language,
): PartView[] {
  const derived = turn.source?.derived?.name || "";
  const operation = turn.operation || turn.source?.operation || "";
  return views.map((view, index) => {
    let caption = "figure";
    if (index === 0 && (derived === "share_percent" || operation === "share")) caption = "share";
    if (index === 0 && (derived === "difference" || operation === "difference")) caption = "difference";
    const unit = index === 0 ? unitFrom(turn.source, language, derived, operation) : "";
    return { ...view, caption, unit };
  });
}

function unitFrom(source: Source | null | undefined, language: Language, derived: string, operation: string): string {
  if (derived === "share_percent" || derived === "yoy_pct" || operation === "share") {
    return language === "is" ? "prósent" : "percent";
  }
  const labels = (source?.cells ?? []).flatMap((cell) => cell.labels ?? []);
  const units = labels
    .filter((label) => UNIT_NAME.test(fold(`${label.variable_text || ""} ${label.variable || ""}`).trim()))
    .map((label) => label.label || "")
    .filter((label) => label && !TOTAL.test(fold(label)));
  return [...new Set(units)].join(", ");
}

export function computedLine(source: Source | null | undefined, operation: string | null | undefined, language: Language): string | null {
  const derived = source?.derived?.name || "";
  const op = operation || source?.operation || "";
  if (!derived && op !== "share" && op !== "difference" && op !== "yoy_pct" && op !== "ratio") return null;
  if (derived === "share_percent" || op === "share") {
    return language === "is" ? "Hlutfall, reiknað úr þessum reitum." : "A share, computed from these cells.";
  }
  if (derived === "difference" || op === "difference") {
    return language === "is" ? "Mismunur, reiknaður úr þessum reitum." : "A difference, computed from these cells.";
  }
  return language === "is" ? "Reiknað úr þessum reitum." : "Computed from these cells.";
}

function yearsIn(text: string): Set<string> {
  const found = new Set<string>();
  for (const match of text.matchAll(/\b((?:1[7-9]|2\d)\d{2})(?:M\d{2}|Q[1-4])?\b/g)) found.add(match[1]);
  return found;
}

export function cautionText(question: string, answer: string, source: Source | null | undefined, language: Language): string | null {
  const named = /No period was named|Ekkert tímabil var nefnt/.test(answer);
  const asked = yearsIn(question);
  const present = yearsIn(answer);
  for (const cell of source?.cells ?? []) {
    for (const label of cell.labels ?? []) {
      for (const year of yearsIn(`${label.code || ""} ${label.label || ""}`)) present.add(year);
    }
  }
  const missing = [...asked].filter((year) => !present.has(year));
  if (missing.length > 0) {
    const shown = [...present].sort().join(", ");
    return language === "is"
      ? `Spurt er um ${missing.join(", ")}. Reiturinn er fyrir ${shown || "annað tímabil"}.`
      : `The question says ${missing.join(", ")}. The cell is for ${shown || "another period"}.`;
  }
  if (named) {
    return language === "is"
      ? "Ekkert tímabil var nefnt, svo nýjasta tímabilið í töflunni er notað."
      : "No period was named, so the latest period in the table is used.";
  }
  return null;
}

export function refusalReason(answer: string): string {
  return answer.split(/Tables considered:|Töflur sem komu til greina:/)[0].trim();
}

export function refusalLinks(answer: string): { href: string; label: string }[] {
  const links: { href: string; label: string }[] = [];
  const re = /([A-Za-z]{3}\d{4,5})?[^\n]{0,120}?(https:\/\/px\.hagstofa\.is\/\S+)/g;
  for (const match of answer.matchAll(re)) {
    const href = match[2];
    if (links.some((item) => item.href === href)) continue;
    const id = match[1] || "";
    const label = id || href;
    links.push({ href, label });
    if (links.length >= 4) break;
  }
  return links;
}

export function cellLine(cell: Cell): string {
  return (cell.labels ?? [])
    .map((label) => label.label || label.code || "")
    .filter(Boolean)
    .join(" · ");
}

export function isTimeLabel(label: CellLabel): boolean {
  return TIME_NAME.test(fold(`${label.variable_text || ""} ${label.variable || ""}`));
}

export function detailText(detail: unknown): string {
  if (detail == null) return "";
  if (typeof detail === "string") return detail;
  if (typeof detail === "object") {
    const record = detail as Record<string, unknown>;
    if (typeof record.reason === "string") return record.reason;
    if (typeof record.kind === "string") return record.kind;
  }
  return "";
}

const HINTS: { test: RegExp; is: string; en: string }[] = [
  { test: /month_missing|clarify_month/, is: "Nefndu mánuðinn, eða biddu um ársmeðaltalið.", en: "Name the month, or ask for the annual average." },
  { test: /future/, is: "Spyrðu um ár sem taflan nær yfir. Ókomið ár hefur ekki útgefna tölu.", en: "Ask for a year the table covers. A future year has no published figure." },
  { test: /level against change/, is: "Spyrðu annaðhvort um stöðuna eða um breytinguna.", en: "Ask either for the level or for the change." },
  { test: /measure does not match/, is: "Nefndu mælinguna, til dæmis vísitölu, breytingu eða fjölda.", en: "Name the measure, for example an index, a change, or a count." },
  { test: /did not agree/, is: "Tvær lesningar náðu ekki sama reit. Þrengdu spurninguna að einu viðfangsefni.", en: "The two readings did not land on the same cell. Narrow the question to one subject." },
  { test: /one of the two parts/, is: "Skiptu spurningunni í tvær, eina um hvorn hlut.", en: "Split the question into two, one for each part." },
  { test: /out_of_scope|non_statistics|opinion/, is: "Spyrðu um viðfangsefni í töflu, til dæmis mannfjölda, verðlag eða vinnumarkað, og nefndu tímabilið.", en: "Ask about a subject in a table, such as population, prices, or the labour market, and name the period." },
];

export function rephraseFor(detail: unknown, clarify: boolean, language: Language): string {
  const text = detailText(detail);
  const folded = fold(text);
  for (const hint of HINTS) {
    if (hint.test.test(folded) || hint.test.test(text)) return hint[language];
  }
  if (clarify) {
    return language === "is"
      ? "Nefndu tímabilið, svæðið, eða hvort þú eigir við sveitarfélag eða landshluta."
      : "Name the period, the area, or whether you mean a municipality or a region.";
  }
  return language === "is"
    ? "Prófaðu aftur með einu viðfangsefni og einu tímabili."
    : "Try again with one subject and one period.";
}
