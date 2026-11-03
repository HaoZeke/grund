"""Dated snapshot of Statistics Iceland PxWeb tables.

There is no database dump on px.hagstofa.is. The API root lists five databases,
folder listings carry each table's `updated` time, and a table is downloaded
with POST. json-stat2 is the smallest format that keeps value codes. One POST
is enough when the table is within maxCells 100000 and maxValues 5000
(https://px.hagstofa.is/pxen/api/v1/en/?config). Larger tables are posted in
chunks under those caps. CSV and the PC-Axis text format are also accepted by
the same POST, and they are smaller than PX-JSON, but CSV drops the codes.

The mirror directory comes from GRUND_MIRROR_DIR. Nothing in that directory
belongs in the repository. A manifest records the snapshot id and, per table,
the PxWeb updated time, the fetch time, and a sha256.

Answers read the snapshot through the same POST the live API would receive.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import time
import urllib.parse
from pathlib import Path
from typing import Any, Iterator

from grund_index.client import MAX_CELLS, MAX_VALUES, PxWebClient, PxWebError

SOURCE = "https://px.hagstofa.is"


def mirror_root() -> Path | None:
    raw = os.environ.get("GRUND_MIRROR_DIR", "").strip()
    if not raw:
        return None
    return Path(raw)


def _stamp() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _load(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _dump(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(raw + "\n", encoding="utf-8")
    for attempt in range(5):
        try:
            temporary.replace(path)
            return
        except OSError:
            if attempt == 4:
                raise
            time.sleep(0.2)


class Snapshot:
    """The current manifest and the content-addressed table files under it."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.manifest_path = self.root / "manifest.json"
        self.manifest = _load(self.manifest_path)
        self.manifest.setdefault("source", SOURCE)
        self.manifest.setdefault("tables", {})
        if not self.manifest.get("snapshot"):
            self.manifest["snapshot"] = _stamp()

    @property
    def snapshot_id(self) -> str:
        return str(self.manifest.get("snapshot") or "")

    def entry(self, url: str) -> dict[str, Any] | None:
        found = self.manifest.get("tables", {}).get(_table_key(url))
        return found if isinstance(found, dict) else None

    def blob(self, digest: str) -> dict[str, Any] | None:
        path = self._blob_path(digest)
        if not path.is_file():
            return None
        payload = _load(path)
        return payload or None

    def save(self) -> None:
        _dump(self.manifest_path, self.manifest)
        pinned = self.root / "snapshots" / f"{self.snapshot_id}.json"
        _dump(pinned, self.manifest)

    def store_table(
        self,
        *,
        url: str,
        table_id: str,
        lang: str,
        title: str,
        updated: str,
        variables: list[dict[str, Any]],
        parts: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Write one or more json-stat2 parts and point the manifest at them."""
        chunks = []
        digest = hashlib.sha256()
        total = 0
        fetched_at = _stamp()
        for part in parts:
            body = {
                "url": url,
                "table_id": table_id,
                "lang": lang,
                "title": title,
                "updated": updated,
                "fetched_at": fetched_at,
                "variables": variables,
                "dataset": part,
            }
            raw = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
            part_sha = _sha256(raw)
            path = self._blob_path(part_sha)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
            digest.update(raw)
            total += len(raw)
            chunks.append({"sha256": part_sha, "bytes": len(raw), "codes": _codes_of(part)})
        entry = {
            "table_id": table_id,
            "lang": lang,
            "url": url,
            "title": title,
            "updated": updated,
            "fetched_at": fetched_at,
            "sha256": digest.hexdigest(),
            "bytes": total,
            "chunks": chunks,
        }
        self.manifest["tables"][_table_key(url)] = entry
        self.manifest["snapshot"] = fetched_at
        self.save()
        return entry

    def _blob_path(self, digest: str) -> Path:
        return self.root / "blobs" / digest[:2] / f"{digest}.json"


def _table_key(url: str) -> str:
    name = urllib.parse.urlsplit(url).path.rstrip("/").rsplit("/", 1)[-1]
    lang = "is" if "/api/v1/is/" in url else "en"
    stem = name.removesuffix(".px")
    return f"{lang}/{stem}"


def _codes_of(dataset: dict[str, Any]) -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    ids = [str(item) for item in dataset.get("id") or []]
    size = [int(item) for item in dataset.get("size") or []]
    dimension = dataset.get("dimension") or {}
    for dim_id, count in zip(ids, size):
        category = (dimension.get(dim_id) or {}).get("category") or {}
        found[dim_id] = _category_codes(category, count)
    return found


def _category_codes(category: dict[str, Any], count: int) -> list[str]:
    index = category.get("index")
    if isinstance(index, dict) and index:
        positions = [str(pos) for pos in range(count or len(index))]
        for code, pos in index.items():
            slot = int(pos)
            if 0 <= slot < len(positions):
                positions[slot] = str(code)
        return positions
    if isinstance(index, list) and index:
        return [str(code) for code in index]
    labels = category.get("label")
    if isinstance(labels, dict) and labels:
        return [str(code) for code in labels]
    return [str(pos) for pos in range(count)]


def _max_age() -> float | None:
    raw = os.environ.get("GRUND_MIRROR_MAX_AGE", "").strip()
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def _is_old(fetched_at: str | None) -> bool:
    limit = _max_age()
    if limit is None or not fetched_at:
        return False
    try:
        parsed = time.strptime(fetched_at, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        return False
    import calendar

    return time.time() - calendar.timegm(parsed) > limit


def query_mirror(url: str, body: dict[str, Any], *, allow_stale: bool = False):
    """Return (pxjson, FetchInfo) or None when this URL is not in the snapshot."""
    from grund_index.client import FetchInfo

    root = mirror_root()
    if root is None or not (root / "manifest.json").is_file():
        return None
    snapshot = Snapshot(root)
    entry = snapshot.entry(url)
    if entry is None:
        return None
    stale = _is_old(entry.get("fetched_at"))
    if stale and not allow_stale:
        return None
    rows_columns = _rows_for(snapshot, entry, body)
    if rows_columns is None:
        return None
    columns, rows, label = rows_columns
    payload = {
        "columns": columns,
        "comments": [],
        "data": rows,
        "metadata": [
            {
                "updated": entry.get("updated") or "",
                "label": label,
                "snapshot": snapshot.snapshot_id,
                "fetched_at": entry.get("fetched_at") or "",
            }
        ],
    }
    info = FetchInfo(
        origin="mirror",
        stale=stale,
        fetched_at=entry.get("fetched_at"),
        updated=entry.get("updated"),
        snapshot=snapshot.snapshot_id,
    )
    return payload, info


def _rows_for(snapshot: Snapshot, entry: dict[str, Any], body: dict[str, Any]):
    selections = _selection_map(body)
    columns: list[dict[str, str]] | None = None
    rows: list[dict[str, Any]] = []
    label = str(entry.get("title") or "")
    chunks = entry.get("chunks") or []
    if not chunks:
        return None
    for chunk in chunks:
        if not _chunk_hits(chunk.get("codes") or {}, selections):
            continue
        stored = snapshot.blob(str(chunk.get("sha256") or ""))
        if stored is None:
            return None
        dataset = stored.get("dataset") or {}
        variables = stored.get("variables") or []
        label = str(stored.get("title") or dataset.get("label") or label)
        piece_columns, piece_rows = _slice(dataset, variables, selections, label)
        if columns is None:
            columns = piece_columns
        rows.extend(piece_rows)
    if columns is None:
        return None
    return columns, rows, label


def _selection_map(body: dict[str, Any]) -> dict[str, dict[str, Any]]:
    found = {}
    for item in body.get("query") or []:
        if isinstance(item, dict) and item.get("code"):
            found[str(item["code"])] = item.get("selection") or {}
    return found


def _chunk_hits(codes: dict[str, list[str]], selections: dict[str, dict[str, Any]]) -> bool:
    for code, selection in selections.items():
        present = codes.get(code)
        if not present:
            continue
        filt = (selection or {}).get("filter") or "item"
        if filt != "item":
            continue
        wanted = {str(value) for value in (selection or {}).get("values") or []}
        if wanted and not (wanted & set(present)):
            return False
    return True


def _slice(dataset: dict[str, Any], variables: list[dict[str, Any]], selections: dict[str, dict[str, Any]], label: str):
    ids = [str(item) for item in dataset.get("id") or []]
    size = [int(item) for item in dataset.get("size") or []]
    dimension = dataset.get("dimension") or {}
    by_code = {str(item.get("code")): item for item in variables if isinstance(item, dict)}
    role_time = set((dataset.get("role") or {}).get("time") or [])
    keep: list[list[int]] = []
    output: list[int] = []
    code_lists: list[list[str]] = []
    for index, dim_id in enumerate(ids):
        count = size[index] if index < len(size) else 1
        category = (dimension.get(dim_id) or {}).get("category") or {}
        codes = _category_codes(category, count)
        code_lists.append(codes)
        variable = by_code.get(dim_id) or {}
        selection = selections.get(dim_id)
        if selection is None:
            if variable.get("elimination"):
                keep.append([0])
                continue
            keep.append(list(range(len(codes))))
            output.append(index)
            continue
        chosen = _chosen(selection, codes)
        positions = []
        locate = {code: pos for pos, code in enumerate(codes)}
        for code in chosen:
            if code in locate:
                positions.append(locate[code])
        keep.append(positions)
        output.append(index)
    columns = []
    for index in output:
        dim_id = ids[index]
        variable = by_code.get(dim_id) or {}
        dim = dimension.get(dim_id) or {}
        time_var = bool(variable.get("time")) or dim_id in role_time
        columns.append({
            "code": dim_id,
            "text": str(dim.get("label") or variable.get("text") or dim_id),
            "type": "t" if time_var else "d",
        })
    decimals = ((dataset.get("extension") or {}).get("px") or {}).get("decimals")
    value_name = label or "value"
    columns.append({"code": value_name, "text": value_name, "type": "c"})
    rows = []
    coords = [0] * len(ids)

    def walk(dim: int) -> None:
        if dim == len(ids):
            flat = 0
            for coord, count in zip(coords, size):
                flat = flat * max(1, count) + coord
            key = [code_lists[index][coords[index]] for index in output]
            rows.append({"key": key, "values": [_cell_string(dataset, flat, decimals)]})
            return
        for pos in keep[dim]:
            coords[dim] = pos
            walk(dim + 1)

    if ids and all(keep):
        walk(0)
    return columns, rows


def _chosen(selection: dict[str, Any], codes: list[str]) -> list[str]:
    filt = selection.get("filter") or "item"
    values = [str(value) for value in selection.get("values") or []]
    if filt == "all":
        return list(codes)
    if filt == "top" and values and values[0].isdigit():
        return codes[: int(values[0])]
    if filt == "bottom" and values and values[0].isdigit():
        return codes[-int(values[0]) :]
    wanted = set(values)
    return [code for code in codes if code in wanted]


def _cell_string(dataset: dict[str, Any], index: int, decimals: Any) -> str:
    status = dataset.get("status") or {}
    if isinstance(status, dict) and str(index) in status and status[str(index)] in {".", "..", "..."}:
        symbol = str(status[str(index)])
        values = dataset.get("value")
        raw = None
        if isinstance(values, list) and index < len(values):
            raw = values[index]
        if raw in (None, ""):
            return symbol
    values = dataset.get("value")
    raw = None
    if isinstance(values, list):
        raw = values[index] if index < len(values) else None
    elif isinstance(values, dict):
        raw = values.get(str(index), values.get(index))
    if raw is None:
        return "."
    if isinstance(raw, str):
        return raw
    if isinstance(raw, bool):
        return str(raw)
    if isinstance(raw, int):
        return str(raw)
    if isinstance(raw, float):
        # A whole number stays an integer. decimals 0 must not turn 18.6 into 19.
        if abs(raw) < 10**15 and raw.is_integer():
            return str(int(raw))
        if isinstance(decimals, int) and not isinstance(decimals, bool) and decimals > 0:
            return f"{raw:.{decimals}f}"
        text = format(raw, ".12f").rstrip("0").rstrip(".")
        return text or "0"
    return str(raw)


def chunk_plan(variables: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """PxWeb query lists that stay under maxCells and maxValues."""
    lengths = [len(item.get("values") or []) for item in variables]
    if not lengths:
        return [[]]
    caps = [min(length, MAX_VALUES) if length else 1 for length in lengths]
    guard = 0
    while math.prod(caps) > MAX_CELLS and guard < 64:
        index = max(range(len(caps)), key=lambda item: caps[item])
        if caps[index] <= 1:
            break
        others = math.prod(caps[pos] for pos in range(len(caps)) if pos != index)
        room = max(1, MAX_CELLS // max(1, others))
        caps[index] = max(1, min(caps[index] - 1, room))
        guard += 1
    ranges: list[list[tuple[int, int]]] = []
    for length, cap in zip(lengths, caps):
        if length <= 0:
            ranges.append([(0, 0)])
            continue
        ranges.append([(start, min(length, start + cap)) for start in range(0, length, cap)])
    plans: list[list[dict[str, Any]]] = []
    for combo in _product(ranges):
        query = []
        for variable, (start, stop) in zip(variables, combo):
            codes = [str(pair[0]) for pair in (variable.get("values") or [])[start:stop]]
            if not codes:
                continue
            query.append({"code": variable.get("code"), "selection": {"filter": "item", "values": codes}})
        plans.append(query)
    return plans or [[]]


def _product(parts: list[list[tuple[int, int]]]) -> Iterator[list[tuple[int, int]]]:
    if not parts:
        yield []
        return
    head, *tail = parts
    for item in head:
        for rest in _product(tail):
            yield [item, *rest]


def _variables_from_metadata(metadata: dict[str, Any]) -> list[dict[str, Any]]:
    variables = []
    for variable in metadata.get("variables") or []:
        codes = [str(code) for code in variable.get("values") or []]
        texts = [str(text) for text in variable.get("valueTexts") or []]
        if len(texts) < len(codes):
            texts = texts + [""] * (len(codes) - len(texts))
        variables.append(
            {
                "code": variable.get("code"),
                "text": variable.get("text") or variable.get("code"),
                "time": bool(variable.get("time")),
                "elimination": bool(variable.get("elimination")),
                "values": list(zip(codes, texts[: len(codes)])),
            }
        )
    return variables


def _variables_from_index(record: dict[str, Any]) -> list[dict[str, Any]]:
    variables = []
    for variable in record.get("variables") or []:
        variables.append(
            {
                "code": variable.get("code"),
                "text": variable.get("text") or variable.get("code"),
                "time": bool(variable.get("time")),
                "elimination": bool(variable.get("elimination")),
                "values": [[str(code), str(label)] for code, label in variable.get("values") or []],
            }
        )
    return variables


def sync(
    index_dir: Path,
    mirror_dir: Path,
    *,
    client: PxWebClient | None = None,
    limit: int | None = None,
    ids: set[str] | None = None,
    languages: set[str] | None = None,
) -> dict[str, Any]:
    """Download catalogue tables into mirror_dir. Safe to run again.

    A table is skipped when its folder-listing `updated` time still matches
    the manifest and the file is on disk. Pass ids to limit the run to those
    table stems. The caller chooses the ids. This module does not.
    """
    records = _read_index(index_dir)
    if ids:
        wanted = {item.removesuffix(".px") for item in ids}
        records = [record for record in records if str(record.get("id", "")).removesuffix(".px") in wanted]
    if languages:
        records = [record for record in records if record.get("lang") in languages]
    if limit is not None:
        records = records[:limit]
    client = client or PxWebClient(cache_dir=mirror_dir / "http-cache")
    snapshot = Snapshot(mirror_dir)
    folders: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        parent = str(record.get("url") or "").rsplit("/", 1)[0]
        folders.setdefault(parent, []).append(record)
    fetched = 0
    skipped = 0
    failed = 0
    started = time.time()
    catalogue_editions = len(_read_index(index_dir))
    for parent, group in folders.items():
        listing = _listing(client, parent)
        by_id = {str(item.get("id")): item for item in listing if isinstance(item, dict)}
        for record in group:
            url = str(record.get("url") or "")
            node = by_id.get(str(record.get("id"))) or {}
            updated = str(node.get("updated") or record.get("updated") or "")
            current = snapshot.entry(url)
            if current and current.get("updated") == updated and _chunks_present(snapshot, current):
                skipped += 1
                print(f"skip {record.get('lang')} {record.get('id')} updated {updated}", flush=True)
                continue
            table_started = time.time()
            try:
                variables = _variables_from_index(record)
                if updated and updated != str(record.get("updated") or ""):
                    metadata = client.get_json(url, use_cache=False)
                    if isinstance(metadata, dict) and metadata.get("variables"):
                        variables = _variables_from_metadata(metadata)
                parts = []
                for query in chunk_plan(variables):
                    body = {"query": query, "response": {"format": "json-stat2"}}
                    part = client.post_json(url, body, live=True, use_cache=False)
                    if not isinstance(part, dict) or "value" not in part:
                        raise PxWebError(f"not a dataset from {url}", url=url)
                    parts.append(part)
                title = str(record.get("title") or (parts[0].get("label") if parts else "") or record.get("id"))
                snapshot.store_table(
                    url=url,
                    table_id=str(record.get("id") or "").removesuffix(".px"),
                    lang=str(record.get("lang") or ""),
                    title=title,
                    updated=updated,
                    variables=variables,
                    parts=parts,
                )
                fetched += 1
                took = time.time() - table_started
                print(
                    f"fetched {record.get('lang')} {record.get('id')} parts={len(parts)} seconds={took:.1f}",
                    flush=True,
                )
            except (PxWebError, OSError, ValueError, KeyError) as exc:
                failed += 1
                print(f"fail {record.get('lang')} {record.get('id')}: {exc}", flush=True)
                # A 429 that outlasted the retries means the window is still shut.
                # The next table waits a minute instead of extending the burst.
                if getattr(exc, "rate_limited", False) or "rate-limiting" in str(exc):
                    time.sleep(60)
    bytes_total = sum(int(item.get("bytes") or 0) for item in snapshot.manifest.get("tables", {}).values())
    elapsed = time.time() - started
    stored = len(snapshot.manifest.get("tables") or {})
    summary = {
        "snapshot": snapshot.snapshot_id,
        "mirror": str(mirror_dir),
        "considered": len(records),
        "catalogue_editions": catalogue_editions,
        "fetched": fetched,
        "skipped": skipped,
        "failed": failed,
        "tables": stored,
        "bytes": bytes_total,
        "elapsed_s": round(elapsed, 1),
        "seconds_per_fetched": round(elapsed / fetched, 1) if fetched else None,
        "coverage": round(stored / catalogue_editions, 4) if catalogue_editions else None,
    }
    print(json.dumps(summary), flush=True)
    return summary


def _chunks_present(snapshot: Snapshot, entry: dict[str, Any]) -> bool:
    chunks = entry.get("chunks") or []
    if not chunks:
        return False
    return all(snapshot._blob_path(str(chunk.get("sha256") or "")).is_file() for chunk in chunks)


def _listing(client: PxWebClient, parent: str) -> list[Any]:
    if not parent:
        return []
    try:
        payload = client.get_json(parent, use_cache=True)
    except PxWebError as exc:
        print(f"fail listing {parent}: {exc}", flush=True)
        return []
    return payload if isinstance(payload, list) else []


def _read_index(index_dir: Path) -> list[dict[str, Any]]:
    gzip_path = index_dir / "tables.jsonl.gz"
    plain_path = index_dir / "tables.jsonl"
    if gzip_path.is_file():
        import gzip

        handle = gzip.open(gzip_path, "rt", encoding="utf-8")
    elif plain_path.is_file():
        handle = plain_path.open(encoding="utf-8")
    else:
        raise FileNotFoundError(f"no tables.jsonl under {index_dir}")
    records = []
    with handle:
        for line in handle:
            if line.strip():
                records.append(json.loads(line))
    return records


def estimate(index_dir: Path) -> dict[str, Any]:
    """Calls and a rough size, from the variable counts already in the index."""
    records = _read_index(index_dir)
    folders = {str(record.get("url") or "").rsplit("/", 1)[0] for record in records}
    data_calls = 0
    cells = 0
    one_shot = 0
    for record in records:
        variables = _variables_from_index(record)
        lengths = [len(item.get("values") or []) for item in variables]
        product = math.prod(lengths) if lengths else 0
        cells += product
        plans = chunk_plan(variables)
        data_calls += len(plans)
        if len(plans) == 1:
            one_shot += 1
    calls = len(folders) + data_calls
    return {
        "tables": len({str(record.get("id")) for record in records}),
        "editions": len(records),
        "folder_listings": len(folders),
        "data_posts": data_calls,
        "calls": calls,
        "one_request_editions": one_shot,
        "cells": cells,
        "seconds_at_1_per_s": calls,
        "json_stat2_bytes_estimate": int(cells * 8),
        "pxjson_bytes_estimate": int(cells * 56),
    }


def main(argv: list[str] | None = None) -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Build a dated PxWeb snapshot for Grund")
    parser.add_argument("--index", type=Path, default=Path("data/index"))
    parser.add_argument("--mirror", type=Path, default=None)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--id", action="append", default=None, help="table stem to include, repeatable")
    parser.add_argument("--language", action="append", default=None)
    parser.add_argument("--estimate", action="store_true")
    args = parser.parse_args(argv)
    if args.estimate:
        print(json.dumps(estimate(args.index), indent=2))
        return
    mirror = args.mirror or mirror_root()
    if mirror is None:
        raise SystemExit("pass --mirror or set GRUND_MIRROR_DIR")
    sync(
        args.index,
        mirror,
        limit=args.limit,
        ids=set(args.id) if args.id else None,
        languages=set(args.language) if args.language else None,
    )


if __name__ == "__main__":
    main()
