"""Extrapolate sidecar for Grund. Separate from the verified answer path.
A short JSON-action loop: the model may search Statistics Iceland tables,
read table metadata, fetch cells, and compute. Every number it writes is
checked: verified (in the answer or question), fetched (in a tool result),
computed (from calc), or inferred (tagged). Anything else is dropped."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ast, hashlib, hmac, json, os, operator, re, time, urllib.parse, urllib.request
try:
    import elab_guard
except Exception:
    elab_guard = None
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

BASE = os.environ["GRUND_LLM_BASE_URL"].rstrip("/")
MODEL = os.environ.get("GRUND_ELAB_MODEL") or os.environ["GRUND_LLM_MODEL"]
KEY = os.environ["GRUND_LLM_API_KEY"]
HKEY = os.environ.get("GRUND_ELAB_HMAC_KEY", "").encode()
TIMEOUT = float(os.environ.get("GRUND_LLM_TIMEOUT", "40"))
LOG = os.environ.get("GRUND_ELAB_LOG", "/srv/log/extrapolate.jsonl")
PX = {"en": "https://px.hagstofa.is/pxen/api/v1/en/", "is": "https://px.hagstofa.is/pxis/api/v1/is/"}
MAX_STEPS = 6
NUM = re.compile(r"(?<![\w])-?\d[\d.,]*\d%?|(?<![\w])\d%?")

def norm(tok):
    t = tok.rstrip("%").strip(".,")
    t = t.replace(",", "") if re.fullmatch(r"-?\d{1,3}(,\d{3})+(\.\d+)?", t) else t
    if re.fullmatch(r"-?\d{1,3}(\.\d{3})+(,\d+)?", t):
        t = t.replace(".", "").replace(",", ".")
    t = t.replace(",", ".")
    try:
        v = float(t)
    except ValueError:
        return None
    return round(v, 6)

def nums(text):
    out = set()
    for m in NUM.findall(text or ""):
        v = norm(m)
        if v is not None:
            out.add(v)
    return out

def context_num(v):
    return v == 100 or (v == int(v) and 1800 <= v <= 2100)

def close(v, pool):
    if context_num(v): return True
    for p in pool:
        if p == v or (p != 0 and abs(v - p) / abs(p) < 0.0051) or abs(v - p) < 0.051:
            return True
    return False

# ---- tools ----
OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
       ast.Pow: operator.pow, ast.USub: operator.neg, ast.UAdd: operator.pos}
def calc(expr):
    def ev(n):
        if isinstance(n, ast.Expression): return ev(n.body)
        if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)): return n.value
        if isinstance(n, ast.BinOp) and type(n.op) in OPS:
            if isinstance(n.op, ast.Pow) and abs(ev(n.right)) > 10: raise ValueError("power too large")
            return OPS[type(n.op)](ev(n.left), ev(n.right))
        if isinstance(n, ast.UnaryOp) and type(n.op) in OPS: return OPS[type(n.op)](ev(n.operand))
        raise ValueError("only numbers and + - * / ** ( )")
    if len(expr) > 300: raise ValueError("expression too long")
    return round(ev(ast.parse(expr, mode="eval")), 6)

def http(url, body=None):
    u = urllib.parse.urlparse(url)
    if u.scheme != "https" or u.hostname != "px.hagstofa.is":
        raise ValueError("only https://px.hagstofa.is is allowed")
    req = urllib.request.Request(url, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())

DBS = ["Atvinnuvegir", "Efnahagur", "Ibuar", "Samfelag", "Umhverfi"]
def search_tables(query, lang="en"):
    root = PX.get(lang, PX["en"]); hits = []
    for db in DBS:
        try:
            for t in http(root + db + "?query=" + urllib.parse.quote(query))[:5]:
                hits.append({"id": t.get("id"), "title": t.get("title"), "score": t.get("score", 0),
                             "url": root + db + (t.get("path") or "").rstrip("/") + "/" + t.get("id", "")})
        except Exception:
            continue
    hits.sort(key=lambda h: -float(h.get("score") or 0))
    return [{k: h[k] for k in ("id", "title", "url")} for h in hits[:8]]

def table_meta(url):
    meta = http(url)
    vs = []
    for v in meta.get("variables", []):
        codes, labels = v.get("values", []), v.get("valueTexts", [])
        pairs = list(zip(codes, labels))
        if len(pairs) > 25: pairs = pairs[:10] + [("...", "...")] + pairs[-10:]
        vs.append({"code": v.get("code"), "text": v.get("text"), "values": [f"{c}={l}" for c, l in pairs]})
    return {"title": meta.get("title"), "variables": vs}

def fetch_pxweb(url, query):
    body = {"query": query, "response": {"format": "json"}}
    res = http(url, body)
    rows = [{"key": d.get("key"), "values": d.get("values")} for d in res.get("data", [])[:40]]
    return {"columns": [c.get("text") for c in res.get("columns", [])], "rows": rows}

def island_ok(url):
    h = (urllib.parse.urlparse(url).hostname or "").lower()
    return urllib.parse.urlparse(url).scheme == "https" and (h == "island.is" or h.endswith(".island.is"))

def search_official(query):
    q = {"query": "query($q:String!){searchResults(query:{queryString:$q,types:[webArticle],size:5}){items{... on Article{title slug}}}}",
         "variables": {"q": query[:200]}}
    req = urllib.request.Request("https://island.is/api/graphql", data=json.dumps(q).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        if not island_ok(r.geturl()): raise ValueError("redirect off island.is")
        items = json.loads(r.read())["data"]["searchResults"]["items"]
    return [{"title": i.get("title"), "url": "https://island.is/" + i.get("slug", "")} for i in items if i.get("slug")]

OFFICIAL_FETCHES = {"n": 0}
def fetch_official(url):
    if not island_ok(url): raise ValueError("only island.is is allowed")
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "grund-extrapolate"}), timeout=20) as r:
        if not island_ok(r.geturl()): raise ValueError("redirect off island.is")
        html = r.read(800000).decode("utf-8", "replace")
    html = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", html)
    text = re.sub(r"\s+", " ", re.sub(r"(?s)<[^>]+>", " ", html)).strip()
    import html as _h
    return {"url": url, "text": _h.unescape(text)[:6000]}

TOOLS = {"search_tables": lambda a, lang: search_tables(str(a.get("query", "")), a.get("lang") or lang),
         "table_meta": lambda a, lang: table_meta(str(a.get("url", ""))),
         "fetch_pxweb": lambda a, lang: fetch_pxweb(str(a.get("url", "")), a.get("query") or []),
         "search_official": lambda a, lang: search_official(str(a.get("query", ""))),
         "fetch_official": lambda a, lang: fetch_official(str(a.get("url", ""))),
         "calc": lambda a, lang: {"expression": str(a.get("expression", "")), "result": calc(str(a.get("expression", "")))}}

SYSTEM = """You extend a verified Statistics Iceland answer. You may use tools to fetch more tables and compute.
Reply with ONE JSON object per turn and nothing else.
To use a tool: {"tool":"search_tables","args":{"query":"..."}} | {"tool":"table_meta","args":{"url":"https://px.hagstofa.is/..."}} | {"tool":"fetch_pxweb","args":{"url":"...","query":[{"code":"VarCode","selection":{"filter":"item","values":["code"]}}]}} | {"tool":"calc","args":{"expression":"(a-b)/b*100"}} | {"tool":"search_official","args":{"query":"..."}} (official island.is pages, Icelandic queries work best) | {"tool":"fetch_official","args":{"url":"https://island.is/..."}} (at most 2)
Use table_meta before fetch_pxweb. Select one value per variable where possible. Use at most 5 tool calls.
When done: {"final":{"from_data":[{"text":"...","source":"TABLEID"}],"beyond":[{"text":"...","kind":"fetched|computed|source|inferred","step":N}]}}
Rules: "from_data" holds only facts from the supplied verified answer, each with its table id. "beyond" holds context, interpretation, follow-up questions and new numbers. Every "beyond" item needs a kind: "fetched" (number from a fetch_pxweb step, give its step number), "computed" (from a calc step, give its step number), "source" (from a fetch_official page, give its step number) or "inferred" (your own interpretation or estimate). Never present inference as data. Every number in a fetched or computed item must appear in that step's result: compute any derived number (difference, ratio, percent) with calc first. Indices with different base years are not directly comparable; say so instead of comparing levels. Keep it short: at most 3 from_data and 5 beyond items. Reply in LANGUAGE."""

INJECT = re.compile(r"ignore (all|previous|the above)|system prompt|api[_ ]?key|bearer\s|password", re.I)
def redact(text):
    text = text.replace(KEY, "[redacted]") if KEY else text
    return re.sub(r"\b(sk-[A-Za-z0-9]{8,}|[A-Za-z0-9_\-]{40,})\b", "[redacted]", text)

ZW = ["\u200b", "\u200c"]
def watermark(text):
    if not HKEY: return text
    mac = hmac.new(HKEY, text.encode(), hashlib.sha256).digest()[:4]
    bits = "".join(f"{b:08b}" for b in mac)
    return text + "\u2060" + "".join(ZW[int(b)] for b in bits)

FALLBACK = os.environ.get("GRUND_ELAB_FALLBACK", "")
def llm(messages, model=None):
    model = model or MODEL
    body = {"model": model, "temperature": 0.1, "messages": messages}
    req = urllib.request.Request(BASE + "/chat/completions", data=json.dumps(body).encode(),
                                 headers={"Authorization": "Bearer " + KEY, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        msg = json.loads(r.read())["choices"][0]["message"]
    text = msg.get("content") or ""
    return re.sub(r"<think>.*?</think>", "", text, flags=re.S)

def parse(raw):
    raw = raw.strip()
    if not raw: raise ValueError("empty reply")
    m = re.search(r"\{.*\}", raw, re.S)
    if not m: raise ValueError("no JSON object")
    return json.loads(m.group(0))

def slim(answer):
    keep = {k: answer.get(k) for k in ("answer", "value", "value_display", "table_id", "tables", "operation", "language") if k in answer}
    src = answer.get("source")
    if isinstance(src, dict):
        keep["source"] = {k: src.get(k) for k in list(src)[:12]}
    return keep

def extrapolate(question, lang, answer):
    t0 = time.time()
    lang = "is" if lang == "is" else "en"
    verified = slim(answer)
    vtext = json.dumps(verified, ensure_ascii=False)[:8000]
    verified_nums = nums(vtext) | nums(question)
    msgs = [{"role": "system", "content": SYSTEM.replace("LANGUAGE", "Icelandic" if lang == "is" else "English")},
            {"role": "user", "content": question},
            {"role": "assistant", "content": "Verified answer: " + vtext},
            {"role": "user", "content": "Extend this answer. Fetch a related table and compute if it adds value."}]
    steps, final, err = [], None, None
    used_fallback = False
    for _ in range(MAX_STEPS + 2):
        if time.time() - t0 > 110:
            err = "time budget used"; break
        try:
            raw = llm(msgs)
        except Exception as exc:
            try:
                raw = llm(msgs)
            except Exception as exc2:
                err = f"model call failed: {type(exc2).__name__}"; break
        if not raw.strip() and FALLBACK:
            try:
                raw = llm(msgs, FALLBACK); used_fallback = True
            except Exception:
                pass
        msgs.append({"role": "assistant", "content": raw[:3000]})
        try:
            act = parse(raw)
        except Exception as exc:
            msgs.append({"role": "user", "content": f"Not valid JSON ({exc}). Reply with one JSON object."}); continue
        if "final" in act:
            final = act["final"]; break
        tool = act.get("tool")
        if tool == "fetch_official" and sum(1 for x in steps if x["tool"] == "fetch_official") >= 2:
            msgs.append({"role": "user", "content": "Official page budget used. Continue or give the final JSON."}); continue
        if tool not in TOOLS or len(steps) >= MAX_STEPS:
            msgs.append({"role": "user", "content": "Unknown tool or tool budget used. Give the final JSON now."}); continue
        args = act.get("args") or {}
        st = {"n": len(steps) + 1, "tool": tool, "args": args}
        try:
            res = TOOLS[tool](args, lang); st["ok"] = True
        except Exception as exc:
            res = {"error": f"{type(exc).__name__}: {str(exc)[:200]}"}; st["ok"] = False
        rtext = json.dumps(res, ensure_ascii=False)[:4000]
        st["result"] = res if tool == "calc" else rtext[:600]
        if tool == "fetch_official" and isinstance(res, dict): st["url"] = res.get("url")
        st["_nums"] = nums(rtext); st["_raw"] = json.dumps(res, ensure_ascii=False)
        steps.append(st)
        left = MAX_STEPS - len(steps)
        msgs.append({"role": "user", "content": f"Step {st['n']} result: {rtext}" + ("\nNo tool calls left. Give the final JSON now." if left <= 0 else f"\n{left} tool calls left.")})
    if final is None:
        err = err or "no final answer"
        final = {"from_data": [], "beyond": []}
    kept = {"verified": 0, "fetched": 0, "computed": 0, "source": 0, "inferred": 0}; dropped = []
    from_data, beyond = [], []
    for it in (final.get("from_data") or [])[:5]:
        text = redact(str(it.get("text", "")))
        if INJECT.search(text): dropped.append({"text": text[:120], "why": "injection"}); continue
        bad = [n for n in nums(text) if not close(n, verified_nums)]
        if bad: dropped.append({"text": text[:160], "why": "number not in verified answer"}); continue
        kept["verified"] += len(nums(text))
        from_data.append({"text": text, "source": str(it.get("source") or verified.get("table_id") or "")})
    by_n = {s["n"]: s for s in steps}
    for it in (final.get("beyond") or [])[:8]:
        text = redact(str(it.get("text", ""))); kind = it.get("kind")
        if INJECT.search(text): dropped.append({"text": text[:120], "why": "injection"}); continue
        if kind not in ("fetched", "computed", "source", "inferred"): dropped.append({"text": text[:160], "why": "untagged"}); continue
        step = by_n.get(it.get("step")) if kind != "inferred" else None
        pool = verified_nums | (step["_nums"] if step else set())
        if step is not None:
            for other in steps: pool |= other["_nums"]
        new = [n for n in nums(text) if not close(n, verified_nums)]
        new_shown = [n for n in new if not context_num(n)]
        if kind in ("fetched", "computed", "source"):
            need = {"computed": "calc", "fetched": "fetch_pxweb", "source": "fetch_official"}[kind]
            if step is None or step["tool"] != need or not step.get("ok"):
                dropped.append({"text": text[:160], "why": f"{kind} without a matching step"}); continue
            if [n for n in new if not close(n, pool)]:
                dropped.append({"text": text[:160], "why": f"number not in step {step['n']}"}); continue
        kept[kind] += len(new_shown)
        beyond.append({"text": text, "kind": kind, "step": step["n"] if step else None,
                       "table": (step["args"].get("url", "").rsplit("/", 1)[-1] if step and kind == "fetched" else None),
                       "expression": (step["args"].get("expression") if step and kind == "computed" else None),
                       "url": (step.get("url") if step and kind == "source" else None),
                       "new_numbers": sorted(new_shown)})
    stamp = ""
    if elab_guard is not None:
        records = []
        for st in steps:
            if not st.get("ok"): continue
            if st["tool"] == "fetch_pxweb":
                cells = []
                try:
                    for row in json.loads(st["_raw"]).get("rows", []): cells += [v for v in row.get("values") or []]
                except Exception: pass
                records.append({"id": str(st["n"]), "kind": "fetch", "table": st["args"].get("url", "").rsplit("/", 1)[-1].replace(".px", ""), "cells": cells})
            elif st["tool"] == "calc":
                records.append({"id": str(st["n"]), "kind": "calc", "expression": st["args"].get("expression"), "result": st["result"].get("result")})
            elif st["tool"] == "fetch_official":
                try: page = json.loads(st["_raw"])
                except Exception: page = {}
                records.append({"id": str(st["n"]), "kind": "source", "url": page.get("url"), "text": page.get("text", "")})
        heads = ("Úr gögnunum", "Handan gagnanna", "(ályktun)") if lang == "is" else ("From the data", "Beyond the data", "(inferred)")
        def gate(head, line):
            try:
                r = elab_guard.check(head + "\n" + line, answer, question, lang, records)
                return not r["dropped_sentences"]
            except Exception:
                return False
        keep_fd = []
        for it in from_data:
            if gate(heads[0], it["text"]): keep_fd.append(it)
            else: dropped.append({"text": it["text"][:160], "why": "elab_guard"})
        keep_b = []
        for it in beyond:
            mark = {"fetched": f" [fetch:{(it.get('table') or '').replace('.px', '')}]", "computed": f" [calc:{it.get('step')}]",
                    "source": f" [source:{it.get('url')}]", "inferred": " " + heads[2]}[it["kind"]]
            if gate(heads[1], it["text"].rstrip() + mark): keep_b.append(it)
            else: dropped.append({"text": it["text"][:160], "why": "elab_guard"})
        from_data, beyond = keep_fd, keep_b
        try:
            meta = {"answer": slim(answer), "model": MODEL, "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "lang": lang}
            stamp = elab_guard.watermark("", meta).strip("\n"); stamp_meta = meta
        except Exception:
            stamp = ""
    for it in from_data + beyond:
        it["text"] = watermark(it["text"])
    pub_steps = [{k: v for k, v in s.items() if k not in ("_nums", "_raw")} for s in steps]
    stats_dropped = len(dropped)
    stats = {"tools": len(steps), "kept": kept, "dropped": len(dropped), "guard": "elab_guard" if elab_guard else "builtin", "ms": int((time.time() - t0) * 1000)}
    rec = {"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "q": hashlib.sha256(question.encode()).hexdigest()[:12],
           "mode": "extrapolate", "model": MODEL, "tool_calls": len(steps), "tools": [s["tool"] for s in steps],
           "kept": kept, "dropped": len(dropped), "ms": stats["ms"], "outcome": "error" if err else ("empty" if not (from_data or beyond) else "ok")}
    try:
        with open(LOG, "a") as f: f.write(json.dumps(rec) + "\n")
    except OSError:
        pass
    return {"mode": "extrapolate", "label": "AI-generated", "model": MODEL, "from_data": from_data, "beyond": beyond,
            "steps": pub_steps, "dropped": dropped, "verified_numbers": sorted(verified_nums), "stats": stats, "error": err, "stamp": stamp, "fallback_used": used_fallback}

def stats():
    tot = {"calls": 0, "ok": 0, "tool_calls": 0, "dropped": 0, "kept": {"verified": 0, "fetched": 0, "computed": 0, "source": 0, "inferred": 0}, "ms_sum": 0}
    try:
        for line in open(LOG):
            r = json.loads(line); tot["calls"] += 1; tot["ok"] += r.get("outcome") == "ok"
            tot["tool_calls"] += r.get("tool_calls", 0); tot["dropped"] += r.get("dropped", 0); tot["ms_sum"] += r.get("ms", 0)
            for k, v in (r.get("kept") or {}).items(): tot["kept"][k] = tot["kept"].get(k, 0) + v
    except OSError:
        pass
    tot["ms_avg"] = int(tot["ms_sum"] / tot["calls"]) if tot["calls"] else 0
    tot.pop("ms_sum"); return tot

class H(BaseHTTPRequestHandler):
    def _send(self, code, obj):
        b = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
    def do_GET(self):
        if self.path.startswith("/health"): return self._send(200, {"ok": True})
        if self.path.startswith("/stats"): return self._send(200, stats())
        self._send(404, {"error": "not found"})
    def do_POST(self):
        if not self.path.startswith("/extrapolate"): return self._send(404, {"error": "not found"})
        try:
            n = int(self.headers.get("Content-Length", "0"))
            if n > 300000: return self._send(413, {"error": "too large"})
            data = json.loads(self.rfile.read(n) or b"{}")
            ans = data.get("answer") or {}
            if not isinstance(ans, dict) or ans.get("refused") or not ans.get("value"):
                return self._send(400, {"error": "extrapolate needs a verified answer"})
            self._send(200, extrapolate(str(data.get("question", ""))[:2000], data.get("language"), ans))
        except Exception as exc:
            self._send(502, {"error": type(exc).__name__})
    def log_message(self, fmt, *args): pass

if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", int(os.environ.get("GRUND_ELAB_PORT", "8743"))), H).serve_forever()
