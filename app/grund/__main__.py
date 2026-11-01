"""Ask one question from the shell: python -m grund "..." """

from __future__ import annotations

import json
import sys
from pathlib import Path

from grund.engine import Engine, IndexOffline
from grund_index.catalogue import Catalogue
from grund_index.client import PxWebClient
from grund_rails.vangrail_client import RailOffline, require_checker


def main(argv: list[str] | None = None) -> None:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        print('usage: python -m grund "What was the consumer price index in June 2024?"', file=sys.stderr)
        raise SystemExit(2)
    try:
        require_checker()
    except RailOffline as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from exc
    question = " ".join(args)
    index = Path("data/index")
    try:
        engine = Engine(Catalogue.load(index), client=PxWebClient(cache_dir=Path("data/cache"), rate=4.0))
    except IndexOffline as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from exc
    result = engine.ask(question)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
