#!/usr/bin/env python3
"""Launch the FastAPI dive-log DSSG web application with uvicorn.

Examples::

    python serve.py                      # http://127.0.0.1:8000
    python serve.py --host 0.0.0.0 --port 8080 --data ./data
    # or directly: uvicorn dssg.web:app --reload
"""

import argparse
import os

import uvicorn


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve the DSSG web app")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--data", default="data",
                        help="directory for permanently stored uploads/reports")
    parser.add_argument("--reload", action="store_true",
                        help="auto-reload on code changes (development)")
    args = parser.parse_args()

    os.environ["DSSG_DATA_DIR"] = args.data
    print(f"vino DSSG analyzer → http://{args.host}:{args.port}  (data: {args.data})")
    uvicorn.run("dssg.web:app", host=args.host, port=args.port, reload=args.reload)


if __name__ == "__main__":
    main()
