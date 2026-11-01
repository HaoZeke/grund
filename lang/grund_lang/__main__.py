"""Build the retrieval index, or measure recall of the gold table."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from grund_lang import build_saved_index, load_index
from grund_lang.bundle import pack_bundle
from grund_lang.eval_recall import score_file, score_root
from grund_lang.pair import score_hard_pairs


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Language layer and catalogue retrieval")
    sub = parser.add_subparsers(dest="command", required=True)

    build = sub.add_parser("build", help="lemmatize the catalogue and embed every label")
    build.add_argument("--source", type=Path, default=Path("data/index"))
    build.add_argument("--catalogue", type=Path, default=None)
    build.add_argument("--out", type=Path, default=Path("data/index-lang"))
    build.add_argument("--embeddings", choices=("auto", "e5", "chargram"), default="auto")
    build.add_argument("--label-embeddings", action="store_true")

    recall = sub.add_parser("recall", help="top-1, top-5 and top-10 table recall")
    recall.add_argument("--index", type=Path, required=True)
    recall.add_argument("--source", type=Path, default=None)
    recall.add_argument("--root", type=Path, default=Path("."))
    recall.add_argument("--questions", type=Path, default=None)
    recall.add_argument("--out", type=Path, default=None)

    pairs = sub.add_parser("pair", help="both-table hit rate on hard questions")
    pairs.add_argument("--index", type=Path, required=True)
    pairs.add_argument("--source", type=Path, default=None)
    pairs.add_argument("--questions", type=Path, required=True)
    pairs.add_argument("--out", type=Path, default=None)

    pack = sub.add_parser("pack", help="tar the index, BM25 postings, and ONNX weights")
    pack.add_argument("--index", type=Path, required=True)
    pack.add_argument("--cache", type=Path, required=True)
    pack.add_argument("--out", type=Path, required=True)

    args = parser.parse_args(argv)
    if args.command == "pack":
        print(json.dumps(pack_bundle(args.index, args.cache, args.out), indent=2))
        return
    if args.command == "pair":
        index = load_index(args.index, source=args.source)
        report = score_hard_pairs(index, args.questions)
        text = json.dumps(report, indent=2)
        if args.out:
            args.out.write_text(text + "\n", encoding="utf-8")
        print(text)
        return
    if args.command == "build":
        manifest = build_saved_index(
            args.source.resolve(),
            args.out.resolve(),
            embed=args.embeddings,
            catalogue=args.catalogue.resolve() if args.catalogue else None,
            embed_labels=args.label_embeddings,
        )
        print(json.dumps(manifest, indent=2))
        return
    index = load_index(args.index, source=args.source)
    if args.questions:
        report = {"dev": score_file(index, args.questions)}
    else:
        report = score_root(index, args.root)
    text = json.dumps(report, indent=2, ensure_ascii=False)
    if args.out:
        args.out.write_text(text + "\n", encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
