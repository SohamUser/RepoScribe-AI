from __future__ import annotations

import argparse
import json
import sys

from app.workers.processor import process_repository_job


def emit(payload: dict[str, object]) -> None:
    print(json.dumps(payload), flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Process a repository analysis job.")
    parser.add_argument("--repository-url", required=True)
    parser.add_argument("--branch", default="main")
    parser.add_argument("--doc-type", action="append", dest="doc_types", default=[])
    parser.add_argument("--trigger-event")
    parser.add_argument("--trigger-action")
    parser.add_argument("--requested-commit-sha")
    args = parser.parse_args()

    try:
        result = process_repository_job(
            repository_url=args.repository_url,
            branch=args.branch,
            regenerate_doc_types=args.doc_types,
            trigger_event=args.trigger_event,
            trigger_action=args.trigger_action,
            requested_commit_sha=args.requested_commit_sha,
            progress_callback=lambda progress, stage, message: emit(
                {
                    "type": "progress",
                    "progress": progress,
                    "stage": stage,
                    "message": message,
                }
            ),
        )
    except Exception as exc:  # pragma: no cover - CLI boundary
        emit(
            {
                "type": "error",
                "message": str(exc),
            }
        )
        return 1

    emit({"type": "result", "result": result})
    return 0


if __name__ == "__main__":
    sys.exit(main())
