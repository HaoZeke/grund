import { useEffect, useRef, useState } from "react";
import { Button } from "./components/ui/button";
import { Card } from "./components/ui/card";
import { Input } from "./components/ui/input";
import {
  answerParts,
  cautionText,
  cellLine,
  computedLine,
  formatStat,
  refusalLinks,
  refusalReason,
  rephraseFor,
  type Cell,
  type PartView,
  type Source,
} from "./card";
import { COPY, type Language } from "./copy";
import { EXAMPLES } from "./examples";
import { clearSettings, isEmpty, loadSettings, saveSettings, secureContext, settingsHeaders, type LlmSettings } from "./llmSettings";

function apiUrl(path: string): string {
  const base = new URL(import.meta.env.BASE_URL, window.location.href);
  return new URL(path.replace(/^\//, ""), base).href;
}

type AskResponse = {
  answer: string;
  refused: boolean;
  clarify: boolean;
  language: Language;
  value: string | null;
  value_display?: string | null;
  table_id: string | null;
  tables?: string[];
  source: Source | null;
  candidates: { table_id: string; title: string; score: number }[];
  detail?: unknown;
  elapsed_ms?: number;
  operation?: string | null;
};

type Turn = {
  question: string;
  chrome: Language;
  response?: AskResponse;
  error?: string;
};

export default function App() {
  const [language, setLanguage] = useState<Language>("is");
  const [question, setQuestion] = useState("");
  const [turns, setTurns] = useState<Turn[]>([]);
  const [busy, setBusy] = useState(false);
  const [agentMode, setAgentMode] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const dialogRef = useRef<HTMLDialogElement>(null);
  const latestRef = useRef<HTMLElement>(null);
  const startedRef = useRef(0);
  const copy = COPY[language];

  useEffect(() => {
    document.documentElement.lang = language;
  }, [language]);

  useEffect(() => {
    if (!busy) return;
    const timer = window.setInterval(() => {
      setElapsed(Math.floor((Date.now() - startedRef.current) / 1000));
    }, 500);
    return () => window.clearInterval(timer);
  }, [busy]);

  useEffect(() => {
    if (!busy && turns.length > 0) {
      latestRef.current?.focus();
    }
  }, [busy, turns]);

  async function submit(text: string) {
    const trimmed = text.trim();
    if (!trimmed || busy) return;
    const chrome = language;
    startedRef.current = Date.now();
    setElapsed(0);
    setBusy(true);
    setTurns((current) => [...current, { question: trimmed, chrome }]);
    try {
      const response = await fetch("/api/ask", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: trimmed }),
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const payload = (await response.json()) as AskResponse;
      setTurns((current) => {
        const next = [...current];
        next[next.length - 1] = { question: trimmed, chrome, response: payload };
        return next;
      });
      setQuestion("");
    } catch {
      setTurns((current) => {
        const next = [...current];
        next[next.length - 1] = { question: trimmed, chrome, error: copy.error };
        return next;
      });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto flex min-h-screen max-w-3xl min-w-0 flex-col overflow-x-hidden px-4 pb-16 pt-4 sm:px-6">
      <a
        href="#ask"
        className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-20 focus:bg-[#fbf8f2] focus:px-3 focus:py-2 focus:text-[#143d66]"
      >
        {copy.skip}
      </a>
      <header className="border-b border-[#1c1915] pb-5">
        <div className="flex items-start justify-between gap-3">
          <div>
            <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-[#8f1d2c]">
              {copy.kicker}
            </p>
            <h1 className="mt-1 font-serif text-5xl font-medium tracking-tight text-[#143d66] sm:text-6xl">
              Grund
            </h1>
          </div>
          <div
            role="group"
            aria-label={copy.language}
            className="flex shrink-0 border border-[#1c1915]"
          >
            {(
              [
                ["is", copy.icelandic],
                ["en", copy.english],
              ] as const
            ).map(([code, label]) => (
              <button
                key={code}
                type="button"
                aria-pressed={language === code}
                onClick={() => setLanguage(code)}
                className={`min-h-11 px-3 text-sm font-semibold focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#143d66] ${
                  language === code ? "bg-[#1c1915] text-[#f4efe6]" : "bg-transparent text-[#1c1915]"
                }`}
              >
                {label}
              </button>
            ))}
          </div>
        </div>
        <p className="mt-4 max-w-xl text-lg leading-snug text-[#1c1915]">{copy.deck}</p>
        <p className="mt-2 max-w-xl text-sm leading-snug text-[#3a342c]">{copy.chromeHint}</p>
        <label className="mt-3 flex min-h-11 items-center gap-2 text-sm font-semibold text-[#1c1915]">
          <input
            type="checkbox"
            className="h-4 w-4 accent-[#143d66]"
            checked={agentMode}
            onChange={(event) => setAgentMode(event.target.checked)}
          />
          {language === "is" ? "Sýna Útvíkka (gervigreind, prófun)" : "Show Extrapolate (AI-generated, beta)"}
        </label>
        {agentMode && <ExtraStats is={language === "is"} />}
        {agentMode && <ExtraSettings is={language === "is"} />}
        <button
          type="button"
          className="mt-3 min-h-11 text-sm font-semibold text-[#143d66] underline decoration-[#143d66] underline-offset-4 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#143d66]"
          onClick={() => dialogRef.current?.showModal()}
        >
          {copy.about}
        </button>
      </header>

      <main className="flex min-w-0 flex-1 flex-col gap-8 py-6 pb-28">
        {turns.length === 0 && (
          <ExampleList copy={copy} language={language} onPick={submit} disabled={busy} />
        )}

        {turns.map((turn, index) => {
          const last = index === turns.length - 1;
          const cardCopy = COPY[turn.chrome];
          return (
            <article
              key={`${turn.question}-${index}`}
              className="flex min-w-0 flex-col gap-4"
              lang={turn.response?.language || turn.chrome}
              ref={last ? latestRef : undefined}
              tabIndex={last ? -1 : undefined}
            >
              <h2 className="font-serif text-2xl leading-tight break-words text-[#1c1915]">{turn.question}</h2>
              {last && busy && <Loading copy={cardCopy} elapsed={elapsed} />}
              {turn.error && (
                <p className="border border-[#8f1d2c] bg-[#fbf8f2] px-3 py-3 text-sm text-[#8f1d2c]" role="alert">
                  {turn.error}
                </p>
              )}
              {turn.response && <Answer turn={turn.response} question={turn.question} chrome={turn.chrome} />}
              {turn.response && agentMode && <Extrapolate turn={turn.response} question={turn.question} chrome={turn.chrome} />}
            </article>
          );
        })}

        {turns.length > 0 && (
          <ExampleList
            copy={copy}
            language={language}
            onPick={submit}
            disabled={busy}
            heading={copy.moreExamples}
          />
        )}
      </main>

      <form
        className="sticky bottom-0 flex flex-col gap-2 border-t border-[#cfc6b8] bg-[#e7e1d6]/95 py-3 sm:flex-row sm:items-end"
        onSubmit={(event) => {
          event.preventDefault();
          void submit(question);
        }}
      >
        <div className="flex min-w-0 flex-1 flex-col gap-1">
          <label htmlFor="ask" className="text-sm font-semibold text-[#1c1915]">
            {copy.question}
          </label>
          <Input
            id="ask"
            value={question}
            placeholder={copy.placeholder}
            onChange={(event) => setQuestion(event.target.value)}
            disabled={busy}
          />
        </div>
        <Button
          type="submit"
          variant="stamp"
          className="min-h-12"
          disabled={!question.trim()}
          aria-disabled={busy || !question.trim()}
        >
          {busy ? copy.asking : copy.ask}
        </Button>
      </form>
      <p className="mt-4 text-sm leading-relaxed text-[#4a433c]">{copy.footer}</p>

      <dialog
        ref={dialogRef}
        aria-labelledby="about-title"
        className="m-auto w-[min(36rem,calc(100%-2rem))] border border-[#1c1915] bg-[#fbf8f2] p-5 text-[#1c1915] backdrop:bg-[#1c1915]/45"
      >
        <h2 id="about-title" className="font-serif text-3xl text-[#143d66]">
          {copy.aboutTitle}
        </h2>
        <div className="mt-3 flex flex-col gap-2 text-sm leading-relaxed">
          {copy.aboutBody.map((line) => (
            <p key={line}>{line}</p>
          ))}
        </div>
        <form method="dialog" className="mt-4">
          <Button type="submit" variant="stamp">
            {copy.close}
          </Button>
        </form>
      </dialog>
    </div>
  );
}

function ExampleList({
  copy,
  language,
  onPick,
  disabled,
  heading,
}: {
  copy: (typeof COPY)[Language];
  language: Language;
  onPick: (text: string) => void;
  disabled: boolean;
  heading?: string;
}) {
  return (
    <section aria-label={heading || copy.examples}>
      <h2 className="text-sm font-semibold uppercase tracking-[0.14em] text-[#3a342c]">
        {heading || copy.examples}
      </h2>
      <div className="mt-3 flex flex-col gap-2">
        {EXAMPLES[language].map((example) => (
          <button
            key={example.id}
            type="button"
            disabled={disabled}
            onClick={() => onPick(example.text)}
            className="min-h-11 border border-[#cfc6b8] bg-[#fbf8f2] px-3 py-3 text-left text-sm leading-snug text-[#1c1915] hover:border-[#143d66] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#143d66] disabled:text-[#3a342c]"
          >
            {example.text}
          </button>
        ))}
      </div>
      {!heading && <p className="mt-4 text-sm text-[#3a342c]">{copy.empty}</p>}
    </section>
  );
}

function Loading({
  copy,
  elapsed,
}: {
  copy: (typeof COPY)[Language];
  elapsed: number;
}) {
  const phase = elapsed >= 18 ? copy.loadingStill : elapsed >= 8 ? copy.loadingRange : copy.loading;
  return (
    <div className="border border-[#143d66] bg-[#fbf8f2] px-3 py-3" aria-busy="true">
      <p className="text-sm text-[#1c1915]" role="status">
        {phase}
      </p>
      {phase !== copy.loadingRange && (
        <p className="mt-1 text-sm text-[#4a433c]">{copy.loadingRange}</p>
      )}
      <p className="mt-1 font-mono text-sm tabular-nums text-[#1c1915]">{copy.elapsed(elapsed)}</p>
      <div className="grund-wait mt-3" aria-hidden="true">
        <span />
      </div>
    </div>
  );
}

function Answer({
  turn,
  question,
  chrome,
}: {
  turn: AskResponse;
  question: string;
  chrome: Language;
}) {
  const answerLang = turn.language || chrome;
  const copy = COPY[answerLang];
  const labels = COPY[chrome];
  if (turn.refused || !turn.value) {
    return <Refusal turn={turn} copy={copy} chrome={chrome} />;
  }
  const parts = answerParts(turn, answerLang);
  const banner = cautionText(question, turn.answer, turn.source, answerLang);
  const ratio = turn.operation === "ratio" ? (turn.value_display || "").trim() : "";
  const note =
    answerLang !== chrome ? (answerLang === "is" ? labels.answeredIs : labels.answeredEn) : "";
  return (
    <div className="flex min-w-0 flex-col gap-4">
      {note && <p className="text-sm font-semibold text-[#143d66]">{note}</p>}
      {banner && (
        <p className="border border-[#8f1d2c] bg-[#fbf8f2] px-3 py-3 text-base leading-snug text-[#1c1915]" role="status">
          {banner}
        </p>
      )}
      {ratio && (
        <p className="font-serif text-4xl tracking-tight text-[#143d66] tabular-nums sm:text-5xl">{ratio}</p>
      )}
      {parts.map((part) => (
        <PartCard key={`${part.tableId}-${part.apiUrl}`} part={part} copy={copy} language={answerLang} source={turn.source} operation={turn.operation} />
      ))}
      <details className="min-w-0 text-sm">
        <summary className="min-h-11 cursor-pointer font-semibold text-[#143d66]">{copy.sentence}</summary>
        <p className="mt-2 break-anywhere leading-relaxed text-[#1c1915]">
          <LinkedText text={turn.answer} />
        </p>
      </details>
    </div>
  );
}

type ExtraItem = { text: string; source?: string; kind?: string; step?: number | null; table?: string | null; expression?: string | null; url?: string | null };
type ExtraStep = { n: number; tool: string; args: Record<string, unknown>; ok: boolean; result: unknown };
type ExtraResponse = {
  from_data: ExtraItem[];
  beyond: ExtraItem[];
  steps: ExtraStep[];
  dropped: { text: string; why: string }[];
  verified_numbers: number[];
  stats: { tools: number; kept: Record<string, number>; dropped: number; ms: number };
  error?: string | null;
  stamp?: string;
};

const NUM_RE = /(-?\d[\d.,]*\d%?|\d%?)/g;

function numValue(token: string): number | null {
  let t = token.replace(/%$/, "").replace(/^[.,]+|[.,]+$/g, "");
  if (/^-?\d{1,3}(,\d{3})+(\.\d+)?$/.test(t)) t = t.replace(/,/g, "");
  else if (/^-?\d{1,3}(\.\d{3})+(,\d+)?$/.test(t)) t = t.replace(/\./g, "").replace(",", ".");
  else t = t.replace(",", ".");
  const v = Number(t);
  return Number.isFinite(v) ? v : null;
}

function MarkedText({ text, verified, is }: { text: string; verified: number[]; is: boolean }) {
  const clean = text.replace(/[\u200b\u200c\u2060]/g, "");
  const pieces = clean.split(NUM_RE);
  return (
    <>
      {pieces.map((piece, i) => {
        if (i % 2 === 0) return <span key={i}>{piece}</span>;
        const v = numValue(piece);
        const ok = v !== null && verified.some((w) => w === v || (w !== 0 && Math.abs(v - w) / Math.abs(w) < 0.0051) || Math.abs(v - w) < 0.051);
        return ok ? (
          <span key={i} className="num-verified font-semibold text-[#1f6b3a]" title={is ? "Í staðfesta svarinu" : "In the verified answer"}>
            {piece}✓
          </span>
        ) : (
          <span
            key={i}
            className="num-unverified bg-[#fbe7b5] underline decoration-dotted decoration-[#a15c00] underline-offset-2"
            title={is ? "Óstaðfest tala" : "Unverified number"}
          >
            {piece}
            <sup className="text-[#a15c00]">?</sup>
          </span>
        );
      })}
      <span aria-hidden="true" className="hidden">{text}</span>
    </>
  );
}

function badgeFor(item: ExtraItem, is: boolean): string {
  if (item.kind === "fetched") return `${is ? "óstaðfest sókn" : "unverified fetch"}${item.table ? " · " + item.table : ""}`;
  if (item.kind === "source") return is ? "heimild · island.is" : "source · island.is";
  if (item.kind === "computed") return `${is ? "reiknað" : "computed"}${item.expression ? " · " + item.expression : ""}`;
  return is ? "ályktun" : "inferred";
}

function ExtraStats({ is }: { is: boolean }) {
  const [stats, setStats] = useState<{ calls: number; ok: number; tool_calls: number; dropped: number; ms_avg: number } | null>(null);
  useEffect(() => {
    fetch(apiUrl("agent/stats"))
      .then((r) => (r.ok ? r.json() : null))
      .then(setStats)
      .catch(() => setStats(null));
  }, []);
  if (!stats) return null;
  return (
    <p className="mt-1 text-xs text-[#6b6257]">
      {is ? "Útvíkkanir" : "Extensions"} {stats.calls} · {is ? "tókust" : "ok"} {stats.ok} · {is ? "tólaköll" : "tool calls"} {stats.tool_calls} ·{" "}
      {is ? "fellt út" : "dropped"} {stats.dropped} · {is ? "meðaltími" : "avg"} {(stats.ms_avg / 1000).toFixed(1)} s · {is ? "hvaða OpenAI-samhæfður endapunktur sem er" : "any OpenAI-compatible endpoint"}
    </p>
  );
}

function ExtraSettings({ is }: { is: boolean }) {
  const [settings, setSettings] = useState<LlmSettings>(() => loadSettings());
  const [saved, setSaved] = useState(false);
  const secure = secureContext();
  const field = "mt-1 h-10 text-sm";
  function update(patch: Partial<LlmSettings>) {
    setSettings((current) => ({ ...current, ...patch }));
    setSaved(false);
  }
  return (
    <details className="ask-extra-settings mt-1 max-w-xl text-sm text-[#1c1915]">
      <summary className="min-h-11 cursor-pointer font-semibold text-[#143d66]">
        {is ? "Stillingar líkans (valfrjálst)" : "Model settings (optional)"}
        {!isEmpty(settings) && <span className="ml-2 text-xs font-normal text-[#6b6257]">{is ? "eigin endapunktur" : "own endpoint"}</span>}
      </summary>
      <form
        className="mt-2 flex flex-col gap-2"
        autoComplete="off"
        onSubmit={(event) => {
          event.preventDefault();
          saveSettings(settings);
          setSaved(true);
        }}
      >
        {!secure && (
          <p role="alert" className="ask-extra-insecure border-l-4 border-[#8f1d2c] bg-[#fbe9ec] px-2 py-1 text-xs font-semibold text-[#8f1d2c]">
            {is
              ? "Þessi síða er ekki á https. Stillingar líkans eru óvirkar og engin þeirra er send, því lykillinn færi ódulkóðaður. Opnaðu síðuna á https-slóðinni."
              : "This page is not on https. Model settings are disabled and none of them is sent, because the key would travel in cleartext. Open the page at its https address."}
          </p>
        )}
        <p className="text-xs text-[#6b6257]">
          {is
            ? "Autt notar sjálfgefinn endapunkt þjónsins. Gildin eru aðeins geymd í þessum vafra og send sem haus með hverri Útvíkka-beiðni, og aðeins yfir https. Hliðarþjónustan skráir þau hvorki né geymir; vefþjónninn fyrir framan hana gerir það ekki heldur þegar hann keyrir síuna sem fylgir deploy/Caddyfile."
            : "Leave blank to use the server default. Values are kept only in this browser and sent as headers with each Extrapolate request, over https only. The sidecar neither logs nor stores them; the web server in front of it does not either when it runs the filter shipped in deploy/Caddyfile."}
        </p>
        <fieldset disabled={!secure} className="flex flex-col gap-2 disabled:opacity-60">
          <label className="flex flex-col font-semibold">
            {is ? "Grunnslóð endapunkts (OpenAI-samhæfður, https)" : "Endpoint base URL (OpenAI-compatible, https)"}
            <Input className={field} type="url" inputMode="url" spellCheck={false} placeholder="https://api.example.com/v1" value={settings.base} onChange={(event) => update({ base: event.target.value })} />
          </label>
          <label className="flex flex-col font-semibold">
            {is ? "API-lykill" : "API key"}
            <Input className={field} type="password" autoComplete="off" spellCheck={false} value={settings.key} onChange={(event) => update({ key: event.target.value })} />
          </label>
          <label className="flex flex-col font-semibold">
            {is ? "Heiti líkans" : "Model name"}
            <Input className={field} type="text" autoComplete="off" spellCheck={false} value={settings.model} onChange={(event) => update({ model: event.target.value })} />
          </label>
          <label className="flex min-h-11 items-center gap-2">
            <input type="checkbox" className="h-4 w-4 accent-[#143d66]" checked={settings.remember} onChange={(event) => update({ remember: event.target.checked })} />
            {is ? "Muna á þessu tæki (localStorage)" : "Remember on this device (localStorage)"}
          </label>
        </fieldset>
        <div className="flex flex-wrap items-center gap-2">
          <Button type="submit" className="min-h-11" disabled={!secure}>
            {is ? "Vista" : "Save"}
          </Button>
          <button
            type="button"
            className="min-h-11 border border-[#143d66] px-3 font-semibold text-[#143d66]"
            onClick={() => {
              clearSettings();
              setSettings(loadSettings());
              setSaved(false);
            }}
          >
            {is ? "Hreinsa" : "Clear"}
          </button>
          {saved && (
            <span role="status" className="text-xs text-[#1f6b3a]">
              {settings.remember ? (is ? "Vistað á þessu tæki." : "Saved on this device.") : is ? "Vistað fyrir þessa lotu." : "Saved for this session."}
            </span>
          )}
        </div>
      </form>
    </details>
  );
}

function Extrapolate({ turn, question, chrome }: { turn: AskResponse; question: string; chrome: Language }) {
  const [state, setState] = useState<"idle" | "busy" | "done" | "error">("idle");
  const [data, setData] = useState<ExtraResponse | null>(null);
  const [failure, setFailure] = useState("");
  const [withheld, setWithheld] = useState(false);
  const is = chrome === "is";
  if (turn.refused || !turn.value) return null;
  async function run() {
    setState("busy");
    setWithheld(!secureContext() && !isEmpty(loadSettings()));
    try {
      const response = await fetch(apiUrl("agent/extrapolate"), {
        method: "POST",
        headers: { "Content-Type": "application/json", ...settingsHeaders(loadSettings()) },
        body: JSON.stringify({ question, language: chrome, answer: turn }),
      });
      if (!response.ok) {
        const body = (await response.json().catch(() => null)) as { error?: string } | null;
        throw new Error(body?.error || `HTTP ${response.status}`);
      }
      setData((await response.json()) as ExtraResponse);
      setState("done");
    } catch (error) {
      setFailure(error instanceof Error ? error.message : "");
      setState("error");
    }
  }
  if (state === "idle") {
    return (
      <button
        type="button"
        className="self-start min-h-11 border border-[#143d66] px-3 text-sm font-semibold text-[#143d66] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#143d66]"
        onClick={() => void run()}
      >
        {is ? "Útvíkka" : "Extrapolate"}
      </button>
    );
  }
  const verified = data?.verified_numbers || [];
  return (
    <section className="ask-turn--extra min-w-0 border-2 border-dashed border-[#a15c00] bg-[#fdf6e3] px-3 py-3 text-sm text-[#3a342c]">
      <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-[#a15c00]">
        {is ? "Handan gagnanna · gervigreind" : "Beyond the data · AI-generated"}
      </p>
      {state === "busy" && <p className="mt-2">{is ? "Útvíkka út frá staðfestu gögnunum…" : "Extending from the verified data…"}</p>}
      {withheld && (
        <p role="alert" className="mt-2 text-xs font-semibold text-[#8f1d2c]">
          {is
            ? "Stillingar líkans voru ekki sendar: síðan er ekki á https. Sjálfgefinn endapunktur þjónsins var notaður."
            : "Your model settings were not sent: this page is not on https. The server default was used."}
        </p>
      )}
      {state === "error" && <p className="mt-2 text-[#8f1d2c]">{is ? "Útvíkkun tókst ekki." : "The extension did not finish."}{failure ? ` ${failure}` : ""}</p>}
      {state === "done" && data && (
        <div className="mt-2 flex flex-col gap-3">
          {data.from_data.length > 0 && (
            <div>
              <h3 className="font-semibold text-[#1c1915]">{is ? "Úr gögnunum" : "From the data"}</h3>
              <ul className="mt-1 list-disc pl-5">
                {data.from_data.map((item, i) => (
                  <li key={i} className="break-anywhere">
                    <MarkedText text={item.text} verified={verified} is={is} /> <span className="text-xs text-[#6b6257]">[{item.source}]</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
          {data.beyond.length > 0 && (
            <div>
              <h3 className="font-semibold text-[#1c1915]">{is ? "Handan gagnanna" : "Beyond the data"}</h3>
              <ul className="mt-1 list-disc pl-5">
                {data.beyond.map((item, i) => (
                  <li key={i} className="break-anywhere">
                    <MarkedText text={item.text} verified={verified} is={is} />{" "}
                    {item.kind === "source" && item.url ? (
                      <a className="whitespace-nowrap border border-[#143d66] px-1 text-[11px] font-semibold text-[#143d66] underline" href={item.url} target="_blank" rel="noreferrer">
                        {badgeFor(item, is)}
                      </a>
                    ) : (
                      <span className="whitespace-nowrap border border-[#a15c00] px-1 text-[11px] font-semibold text-[#a15c00]">{badgeFor(item, is)}</span>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          )}
          {data.from_data.length === 0 && data.beyond.length === 0 && <p>{is ? "Ekkert stóðst skoðun." : "Nothing passed the checks."}</p>}
          {data.steps.length > 0 && (
            <details>
              <summary className="min-h-11 cursor-pointer font-semibold text-[#143d66]">
                {is ? "Skref" : "Steps"} ({data.steps.length})
              </summary>
              <ol className="mt-1 list-decimal pl-5 font-mono text-xs">
                {data.steps.map((step) => (
                  <li key={step.n} className="break-anywhere">
                    {step.tool} {JSON.stringify(step.args)} → {typeof step.result === "string" ? step.result.slice(0, 240) : JSON.stringify(step.result)}
                  </li>
                ))}
              </ol>
            </details>
          )}
          <p className="text-xs text-[#6b6257]">
            {is ? "Tól" : "Tools"} {data.stats.tools} · {is ? "staðfestar" : "verified"} {data.stats.kept.verified || 0} · {is ? "merktar" : "marked"}{" "}
            {(data.stats.kept.fetched || 0) + (data.stats.kept.computed || 0) + (data.stats.kept.source || 0) + (data.stats.kept.inferred || 0)} · {is ? "fellt út" : "dropped"} {data.stats.dropped} ·{" "}
            {(data.stats.ms / 1000).toFixed(1)} s
          </p>
        </div>
      )}
      {data?.stamp && <p className="mt-2 text-xs font-semibold text-[#a15c00]">{data.stamp}</p>}
      <p className="mt-2 text-xs text-[#6b6257]">
        {is
          ? "Staðfesta svarið hér að ofan breytist ekki. Tölur merktar ? eru ekki staðfestar."
          : "The verified answer above does not change. Numbers marked ? are not verified."}
      </p>
    </section>
  );
}

function PartCard({
  part,
  copy,
  language,
  source,
  operation,
}: {
  part: PartView;
  copy: (typeof COPY)[Language];
  language: Language;
  source: Source | null;
  operation?: string | null;
}) {
  const caption = part.caption === "share" ? copy.share : part.caption === "difference" ? copy.difference : copy.figure;
  const computed = part.cells.length > 0 ? computedLine(source, operation, language) : null;
  return (
    <Card className="min-w-0 overflow-hidden border-l-4 border-l-[#143d66] p-4">
      <p className="text-sm font-semibold uppercase tracking-[0.12em] text-[#8f1d2c]">{caption}</p>
      <p className="mt-1 font-serif text-4xl tracking-tight break-words text-[#143d66] tabular-nums sm:text-5xl">
        {part.figure}
      </p>
      <dl className="mt-4 grid gap-3 text-sm sm:grid-cols-2">
        <Field label={copy.unit} value={part.unit} missing={copy.missing} />
        <Field label={copy.period} value={part.period} missing={copy.missing} />
        <Field label={copy.table} value={part.tableId} missing={copy.missing} mono />
        {part.title && <Field label={copy.title} value={part.title} missing={copy.missing} />}
      </dl>
      {part.cells.length > 0 && (
        <p className="mt-3 break-anywhere text-sm text-[#1c1915]">
          <span className="font-semibold">{copy.cell}: </span>
          {part.cells.map((cell) => cellLine(cell)).filter(Boolean).join(" / ")}
        </p>
      )}
      {computed && <p className="mt-3 text-sm leading-relaxed text-[#1c1915]">{computed}</p>}
      <div className="mt-4 flex flex-col gap-2 sm:flex-row sm:flex-wrap">
        {part.apiUrl && (
          <Button asChild variant="default">
            <a className="whitespace-normal text-center" href={part.apiUrl} target="_blank" rel="noreferrer">
              {copy.open}
            </a>
          </Button>
        )}
        {part.humanUrl && (
          <Button asChild variant="outline">
            <a href={part.humanUrl} target="_blank" rel="noreferrer">
              {copy.human}
            </a>
          </Button>
        )}
      </div>
      {part.cells.length > 0 && source && <SourceDetails source={source} copy={copy} language={language} />}
    </Card>
  );
}

function Refusal({
  turn,
  copy,
  chrome,
}: {
  turn: AskResponse;
  copy: (typeof COPY)[Language];
  chrome: Language;
}) {
  const hint = rephraseFor(turn.detail, turn.clarify, turn.language);
  const links = refusalLinks(turn.answer);
  const labels = COPY[chrome];
  const note = turn.language !== chrome ? (turn.language === "is" ? labels.answeredIs : labels.answeredEn) : "";
  return (
    <Card className="min-w-0 border-l-4 border-l-[#8f1d2c] p-4" role="status">
      {note && <p className="mb-2 text-sm font-semibold text-[#143d66]">{note}</p>}
      <h3 className="font-serif text-3xl text-[#8f1d2c]">{copy.refusedTitle}</h3>
      <p className="mt-3 text-base leading-relaxed break-anywhere text-[#1c1915]">
        <LinkedText text={refusalReason(turn.answer)} />
      </p>
      <p className="mt-3 text-base leading-relaxed text-[#1c1915]">{hint}</p>
      {links.length > 0 && (
        <ul className="mt-4 flex flex-col gap-2">
          {links.map((link) => (
            <li key={link.href}>
              <a
                href={link.href}
                target="_blank"
                rel="noreferrer"
                className="break-anywhere text-sm font-semibold text-[#143d66] underline"
              >
                {link.label}
              </a>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

function LinkedText({ text }: { text: string }) {
  const bits = text.split(/(https:\/\/\S+)/g);
  return bits.map((bit, index) =>
    bit.startsWith("https://") ? (
      <a key={index} href={bit} target="_blank" rel="noreferrer" className="break-anywhere underline">
        {bit}
      </a>
    ) : (
      <span key={index}>{bit}</span>
    ),
  );
}

function Field({
  label,
  value,
  missing,
  mono = false,
}: {
  label: string;
  value: string;
  missing: string;
  mono?: boolean;
}) {
  return (
    <div>
      <dt className="text-sm font-semibold text-[#3a342c]">{label}</dt>
      <dd className={`mt-0.5 text-[#1c1915] ${mono ? "font-mono" : ""}`}>{value || missing}</dd>
    </div>
  );
}

function SourceDetails({
  source,
  copy,
  language,
}: {
  source: Source;
  copy: (typeof COPY)[Language];
  language: Language;
}) {
  return (
    <div className="mt-4 border-t border-[#e4dccc] pt-3 text-sm">
      <dl className="grid gap-2 sm:grid-cols-2">
        {source.retrieved_at && (
          <div>
            <dt className="text-sm font-semibold text-[#3a342c]">{copy.retrieved}</dt>
            <dd className="font-mono text-xs">{source.retrieved_at}</dd>
          </div>
        )}
        {source.table_updated && (
          <div>
            <dt className="text-sm font-semibold text-[#3a342c]">{copy.updated}</dt>
            <dd className="font-mono text-xs">{source.table_updated}</dd>
          </div>
        )}
      </dl>
      <div className="mt-2 flex gap-2">
        {source.preliminary && <Stamp>{copy.preliminary}</Stamp>}
        {source.revised && <Stamp>{copy.revised}</Stamp>}
      </div>
      {source.cells && source.cells.length > 0 && (
        <>
          <p className="mt-3 text-sm font-semibold text-[#3a342c]">{copy.cells}</p>
          <ul className="mt-1 divide-y divide-[#e4dccc] border-y border-[#e4dccc]">
            {source.cells.map((cell, index) => (
              <li key={cellKey(cell, index)} className="flex items-baseline justify-between gap-3 py-1.5">
                <span className="min-w-0 break-anywhere text-[#1c1915]">{cellLine(cell)}</span>
                <span className="font-mono tabular-nums">{formatStat(String(cell.value ?? ""), language)}</span>
              </li>
            ))}
          </ul>
        </>
      )}
      {source.footnotes && source.footnotes.length > 0 && (
        <div className="mt-3 text-sm leading-relaxed text-[#1c1915]">
          <p className="font-semibold">{copy.notes}</p>
          {source.footnotes.map((note) => (
            <p key={note.text} className="mt-1 whitespace-pre-wrap">
              {note.text}
            </p>
          ))}
        </div>
      )}
      <details className="mt-3">
        <summary className="min-h-11 cursor-pointer text-[#143d66]">{copy.query}</summary>
        <pre className="mt-2 max-w-full overflow-x-auto bg-[#f4efe6] p-2 font-mono text-xs leading-relaxed">
          {JSON.stringify(source.query, null, 2)}
        </pre>
      </details>
    </div>
  );
}

function cellKey(cell: Cell, index: number): string {
  if (cell.key && cell.key.length) return cell.key.join("|");
  return String(index);
}

function Stamp({ children }: { children: string }) {
  return (
    <span className="border border-[#8f1d2c] px-1.5 py-0.5 text-sm font-semibold text-[#8f1d2c]">
      {children}
    </span>
  );
}
