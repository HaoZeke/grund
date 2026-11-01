"""Crawl the PxWeb table tree in Icelandic and English.

Writes one JSON object per table-language to data/catalog/tables.jsonl.
GET responses are cached, so a rerun resumes. Priority folders (CPI,
population, internal migration, and one level of every database) are fetched
first and marked with data/catalog/PRIORITY_DONE so an index can be built
before the full tree finishes.

Usage:
    python -m grund_index.crawl --out data/catalog/tables.jsonl
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
import urllib.parse
from pathlib import Path
from typing import Any

from grund_index.client import BASE, PxWebClient, PxWebError, RateLimiter

# Folders fetched before the full walk. Paths are API id segments, not titles.
PRIORITY_FOLDERS: list[list[str]] = [
    ["Efnahagur", "visitolur", "1_vnv", "1_vnv"],
    ["Efnahagur", "visitolur", "1_vnv"],
    ["Efnahagur", "visitolur"],
    ["Efnahagur", "thjodhagsreikningar"],
    ["Efnahagur", "thjodhagsspa"],
    ["Efnahagur", "utanrikisverslun"],
    ["Ibuar", "mannfjoldi", "1_yfirlit", "yfirlit_mannfjolda"],
    ["Ibuar", "mannfjoldi", "1_yfirlit", "arsfjordungstolur"],
    ["Ibuar", "mannfjoldi", "1_yfirlit"],
    ["Ibuar", "buferlaflutningar", "buferlaflinnanlands", "buferlaflinnanlands"],
    ["Ibuar", "buferlaflutningar", "buferlaflinnanlands"],
    ["Ibuar", "buferlaflutningar"],
    ["Ibuar", "mannfjoldi"],
    ["Atvinnuvegir"],
    ["Samfelag"],
    ["Umhverfi"],
    ["Sogulegar"],
]


def api_url(lang: str, segments: list[str]) -> str:
    quoted = [urllib.parse.quote(segment, safe="") for segment in segments]
    return BASE[lang] + ("/" + "/".join(quoted) if quoted else "/")


def _load_seen(path: Path) -> set[str]:
    seen: set[str] = set()
    if not path.exists():
        return seen
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                seen.add(json.loads(line)["url"])
            except (json.JSONDecodeError, KeyError):
                continue
    return seen


class CatalogWriter:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._lock = threading.Lock()
        self.count = 0
        self.seen = _load_seen(path)
        self._handle = path.open("a", encoding="utf-8")

    def add(self, record: dict[str, Any]) -> bool:
        url = record["url"]
        with self._lock:
            if url in self.seen:
                return False
            self._handle.write(json.dumps(record, ensure_ascii=False) + "\n")
            self._handle.flush()
            self.seen.add(url)
            self.count += 1
            return True

    def close(self) -> None:
        self._handle.close()


def _variables(metadata: dict[str, Any]) -> list[dict[str, Any]]:
    variables = []
    for variable in metadata.get("variables") or []:
        codes = variable.get("values") or []
        texts = variable.get("valueTexts") or [""] * len(codes)
        if len(texts) != len(codes):
            texts = list(texts) + [""] * (len(codes) - len(texts))
        variables.append(
            {
                "code": variable.get("code"),
                "text": variable.get("text"),
                "time": bool(variable.get("time")),
                "elimination": bool(variable.get("elimination")),
                "values": list(zip(codes, texts)),
            }
        )
    return variables


def _record_table(
    client: PxWebClient,
    writer: CatalogWriter,
    lang: str,
    db: str,
    folder_ids: list[str],
    folder_texts: list[str],
    node: dict[str, Any],
) -> None:
    segments = folder_ids + [node["id"]]
    url = api_url(lang, segments)
    if url in writer.seen:
        return
    try:
        metadata = client.get_json(url)
    except PxWebError as exc:
        print(f"skip table {url}: {exc}", file=sys.stderr)
        return
    record = {
        "lang": lang,
        "db": db,
        "id": node["id"],
        "title": metadata.get("title") or node.get("text") or node["id"],
        "path": folder_ids,
        "path_texts": folder_texts,
        "url": url,
        "updated": node.get("updated"),
        "variables": _variables(metadata),
        "notes": metadata.get("notes") or metadata.get("info"),
    }
    writer.add(record)


def _list_folder(client: PxWebClient, lang: str, segments: list[str]) -> list[dict[str, Any]]:
    try:
        payload = client.get_json(api_url(lang, segments))
    except PxWebError as exc:
        print(f"skip {lang} {'/'.join(segments)}: {exc}", file=sys.stderr)
        return []
    if not isinstance(payload, list):
        return []
    return payload


def _path_texts(client: PxWebClient, lang: str, folder: list[str]) -> list[str]:
    roots = _list_folder(client, lang, [])
    names = {}
    for root in roots:
        names[root.get("dbid") or root.get("id")] = root.get("text") or root.get("dbid")
    texts = [names.get(folder[0], folder[0])]
    segments = [folder[0]]
    for segment in folder[1:]:
        nodes = _list_folder(client, lang, segments)
        match = next((node for node in nodes if node.get("id") == segment), None)
        texts.append((match or {}).get("text") or segment)
        segments.append(segment)
    return texts


def crawl_priority(client: PxWebClient, writer: CatalogWriter, languages: list[str]) -> None:
    """One and two levels under the priority folders, both languages."""
    for lang in languages:
        for folder in PRIORITY_FOLDERS:
            if folder[0] == "Sogulegar" and lang != "is":
                continue
            folder_texts = _path_texts(client, lang, folder)
            nodes = _list_folder(client, lang, folder)
            db = folder[0]
            for node in nodes:
                if node.get("type") == "t" or str(node.get("id", "")).endswith(".px"):
                    _record_table(client, writer, lang, db, folder, folder_texts, node)
                elif node.get("type") == "l":
                    child = folder + [node["id"]]
                    child_texts = folder_texts + [node.get("text") or node["id"]]
                    for sub in _list_folder(client, lang, child):
                        if sub.get("type") == "t" or str(sub.get("id", "")).endswith(".px"):
                            _record_table(client, writer, lang, db, child, child_texts, sub)
            print(f"priority {lang} {'/'.join(folder)} catalog={len(writer.seen)}", file=sys.stderr)


def crawl_full(client: PxWebClient, writer: CatalogWriter, languages: list[str]) -> None:
    for lang in languages:
        roots = _list_folder(client, lang, [])
        stack: list[tuple[str, list[str], list[str]]] = []
        for root in roots:
            dbid = root.get("dbid") or root.get("id")
            if not dbid:
                continue
            stack.append((dbid, [dbid], [root.get("text") or dbid]))
        while stack:
            db, folder_ids, folder_texts = stack.pop()
            nodes = _list_folder(client, lang, folder_ids)
            for node in nodes:
                node_id = node.get("id")
                if not node_id:
                    continue
                if node.get("type") == "l":
                    stack.append((db, folder_ids + [node_id], folder_texts + [node.get("text") or node_id]))
                elif node.get("type") == "t" or node_id.endswith(".px"):
                    _record_table(client, writer, lang, db, folder_ids, folder_texts, node)
            if len(writer.seen) % 100 < 3:
                print(
                    f"full {lang} depth={len(folder_ids)} catalog={len(writer.seen)} queue={len(stack)}",
                    file=sys.stderr,
                )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Crawl Statistics Iceland PxWeb metadata")
    parser.add_argument("--out", type=Path, default=Path("data/catalog/tables.jsonl"))
    parser.add_argument("--cache", type=Path, default=Path("data/cache"))
    parser.add_argument("--rate", type=float, default=6.0)
    parser.add_argument("--languages", default="en,is")
    parser.add_argument("--priority-only", action="store_true")
    parser.add_argument("--skip-priority", action="store_true")
    args = parser.parse_args(argv)
    languages = [part.strip() for part in args.languages.split(",") if part.strip()]
    limiter = RateLimiter(args.rate)
    client = PxWebClient(cache_dir=args.cache, limiter=limiter)
    writer = CatalogWriter(args.out)
    started = time.time()
    print(f"resume with {len(writer.seen)} cached tables", file=sys.stderr)
    try:
        if not args.skip_priority:
            crawl_priority(client, writer, languages)
            marker = args.out.parent / "PRIORITY_DONE"
            marker.write_text(time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), encoding="utf-8")
        if not args.priority_only:
            crawl_full(client, writer, languages)
    finally:
        writer.close()
    print(
        f"catalog {args.out} records={len(writer.seen)} seconds={time.time() - started:.0f}",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
