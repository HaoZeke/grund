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
