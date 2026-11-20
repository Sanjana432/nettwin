import argparse
import json
from pathlib import Path

from .engine import compare
from .examples import scenario


def main():
    parser = argparse.ArgumentParser(description="Compare IPv4 network snapshots.")
    sub = parser.add_subparsers(dest="command", required=True)
    serve = sub.add_parser("serve")
    serve.add_argument("--port", type=int, default=8131)
    demo = sub.add_parser("demo")
    demo.add_argument("scenario", choices=("withdraw", "cost", "isolation", "unchanged"), nargs="?", default="withdraw")
    check = sub.add_parser("check")
    check.add_argument("file", type=Path)
    for command in (demo, check):
        command.add_argument("--drill", action="store_true")
    args = parser.parse_args()
    if args.command == "serve":
        import uvicorn
        uvicorn.run("nettwin.web:app", host="127.0.0.1", port=args.port)
        return 0
    try:
        inputs = scenario(args.scenario) if args.command == "demo" else json.loads(args.file.read_text(encoding="utf-8"))
        result = compare(inputs["baseline"], inputs["candidate"], inputs["policies"], args.drill)
    except (ValueError, TypeError, KeyError, OSError, RecursionError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
