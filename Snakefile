# Reproducible path from a PxWeb crawl to an eval report.
# Pixi tasks (pixi.toml) call the same modules. This file is the Snakemake view.
#
#   snakemake -c1 evaluate
#   snakemake -c1 test

rule all:
    input:
        "evalset/results.json"


rule crawl:
    output:
        "data/catalog/tables.jsonl"
    shell:
        "python -m grund_index.crawl --out {output} --cache data/cache"


rule index:
    input:
        "data/catalog/tables.jsonl"
    output:
        "data/index/manifest.json",
        "data/index/tables.jsonl.gz",
        "data/index/embeddings.npy"
    shell:
        "python -m grund_index.build --catalog {input} --out data/index --embeddings auto"


rule evalset:
    input:
        "data/catalog/tables.jsonl"
    output:
        "evalset/questions.jsonl"
    shell:
        "python -m grund_eval.generate --catalog {input} --out {output}"


rule evaluate:
    input:
        "evalset/questions.jsonl",
        "data/index/manifest.json"
    output:
        "evalset/results.json"
    shell:
        "python -m grund_eval.harness --questions {input[0]} --index data/index --out {output}"


rule test:
    shell:
        "python -m pytest -q"
