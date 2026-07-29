#!/usr/bin/env python3
"""Launch the downloader and open it in your browser.

    python run.py            # start on http://127.0.0.1:8787
    python run.py --port 9000
"""
import argparse
import threading
import webbrowser

import uvicorn


def main() -> None:
    parser = argparse.ArgumentParser(description="Reel — YouTube downloader")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--no-open", action="store_true", help="don't open a browser tab")
    args = parser.parse_args()

    url = f"http://{args.host}:{args.port}"
    if not args.no_open:
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()

    print(f"\n  Reel is running at {url}\n  Press Ctrl+C to stop.\n")
    uvicorn.run("app.main:app", host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
