import argparse
import json
import logging
import sys
from pathlib import Path
from uuid import uuid4

from ingestion.config import Settings
from ingestion.pipeline import Pipeline


def emit(value):
    print(json.dumps(value, ensure_ascii=False, indent=2, default=str))


def parser():
    root = argparse.ArgumentParser(description="KBTU knowledge data preparation")
    commands = root.add_subparsers(dest="command", required=True)
    for name in ("crawl", "crawl-kbtu"):
        cmd = commands.add_parser(name, help="Crawl public KBTU student pages and linked files")
        cmd.add_argument(
            "--dry-run",
            action="store_true",
            help="Read HTML and discover links; do not save or index",
        )
        cmd.add_argument("--max-pages", type=int)
        cmd.add_argument("--depth", type=int)
        cmd.add_argument(
            "--parse-only", action="store_true", help="Save parsed data without embeddings/Qdrant"
        )
    for name in ("ingest-file", "ingest-folder"):
        cmd = commands.add_parser(name)
        cmd.add_argument("path", type=Path)
        cmd.add_argument(
            "--parse-only", action="store_true", help="Save parsed data without embeddings/Qdrant"
        )
        cmd.add_argument("--source-channel", choices=["telegram", "manual_upload", "internal_kbtu"])
        cmd.add_argument(
            "--metadata", type=Path, help="JSON with explicit document metadata (single file only)"
        )
    for name in ("reindex", "inspect"):
        commands.add_parser(name).add_argument("doc_id")
    cmd = commands.add_parser(
        "set-trust", help="Local administrator action; no parsing or embedding"
    )
    cmd.add_argument("doc_id")
    cmd.add_argument("trust", choices=["official", "verified_internal", "unverified"])
    cmd.add_argument("--reason", required=True)
    for name in ("status", "verify", "refresh-current", "reindex-all"):
        commands.add_parser(name)
    return root


def main(argv=None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    args = parser().parse_args(argv)
    try:
        settings = Settings()
        if args.command in {"crawl", "crawl-kbtu"}:
            from ingestion.crawler.kbtu_spider import crawl

            settings = Settings(
                **{
                    **settings.model_dump(),
                    "kbtu_crawler_max_pages": args.max_pages or settings.kbtu_crawler_max_pages,
                    "kbtu_crawler_depth": args.depth or settings.kbtu_crawler_depth,
                }
            )
            if args.dry_run:
                report, results = crawl(settings, dry_run=True)
            else:
                with Pipeline(settings, parse_only=args.parse_only) as pipeline:
                    run_id = str(uuid4())
                    pipeline.registry.start_run(run_id, "kbtu_website")
                    report, results = crawl(settings, pipeline=pipeline)
                    pipeline.registry.finish_run(run_id, results)
                    if not args.parse_only:
                        pipeline.refresh_current()
            emit(report)
            return int(any(r.status == "failed" for r in results))
        with Pipeline(settings, parse_only=getattr(args, "parse_only", False)) as pipeline:
            if args.command.startswith("ingest-"):
                if not args.path.exists():
                    raise ValueError("Input path does not exist")
                if args.command == "ingest-folder":
                    if not args.path.is_dir():
                        raise ValueError("Expected a directory")
                    if args.metadata:
                        raise ValueError("--metadata applies to ingest-file only")
                    paths = sorted(
                        p
                        for p in args.path.rglob("*")
                        if p.is_file()
                        and not p.is_symlink()
                        and p.suffix.lower() in {".pdf", ".docx", ".doc", ".html", ".htm"}
                    )
                else:
                    paths = [args.path]
                overrides = (
                    json.loads(args.metadata.read_text(encoding="utf-8")) if args.metadata else None
                )
                results = pipeline.ingest_files(
                    paths, channel=args.source_channel, overrides=overrides
                )
                emit([r.model_dump() for r in results])
                return int(any(r.status in {"failed", "needs_ocr"} for r in results))
            if args.command == "inspect":
                doc = pipeline.registry.get(args.doc_id)
                emit(
                    {
                        "document": doc.model_dump(mode="json"),
                        "status": pipeline.registry.row(args.doc_id)["status"],
                        "sources": [
                            dict(row)
                            for row in pipeline.registry.db.execute(
                                "SELECT * FROM document_sources WHERE doc_id=?", (args.doc_id,)
                            )
                        ],
                    }
                )
            elif args.command == "status":
                emit(
                    {
                        "documents": [
                            {
                                "doc_id": d.doc_id,
                                "title": d.title,
                                "status": pipeline.registry.row(d.doc_id)["status"],
                                "is_current": d.is_current,
                                "trust_level": d.trust_level,
                            }
                            for d in pipeline.registry.all()
                        ],
                        "runs": pipeline.registry.runs(),
                    }
                )
            elif args.command == "reindex":
                emit(pipeline.reindex(args.doc_id).model_dump())
            elif args.command == "reindex-all":
                emit(
                    [
                        pipeline.reindex(d.doc_id).model_dump()
                        for d in pipeline.registry.all()
                        if pipeline.registry.row(d.doc_id)["status"] != "needs_ocr"
                    ]
                )
            elif args.command == "set-trust":
                emit(
                    pipeline.set_trust(args.doc_id, args.trust, args.reason).model_dump(mode="json")
                )
            elif args.command == "refresh-current":
                pipeline.refresh_current()
                emit({"status": "refreshed"})
            elif args.command == "verify":
                issues = pipeline.verify()
                emit({"ok": not issues, "issues": issues})
                return int(bool(issues))
        return 0
    except (ValueError, KeyError, OSError) as exc:
        emit({"error": str(exc)})
        return 1
    except Exception as exc:
        emit(
            {
                "error": type(exc).__name__,
                "hint": "Check model dependencies, Qdrant and configuration",
            }
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
