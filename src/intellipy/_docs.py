"""Build the documentation: the ``intellipy-docs`` entry point.

A thin wrapper around ``sphinx-build`` that finds ``docs/`` relative to the
source checkout, so the command works from any directory::

    uv run --extra docs intellipy-docs
    uv run --extra docs intellipy-docs --serve
    uv run --extra docs intellipy-docs --clean --strict

Only useful from a source checkout -- an installed wheel ships no ``docs/``.
"""

import argparse
import os
import shutil
import sys

#: Repository root, two levels above this file (``src/intellipy/_docs.py``).
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DOCS_DIR = os.path.join(ROOT, "docs")
BUILD_DIR = os.path.join(DOCS_DIR, "_build", "html")


def main(argv=None):
    """Build the HTML documentation. Returns a process exit code."""
    parser = argparse.ArgumentParser(description="Build the intellipy documentation.")
    parser.add_argument(
        "--clean", action="store_true",
        help="remove previous build output and generated tables first",
    )
    parser.add_argument(
        "--strict", action="store_true",
        help="turn Sphinx warnings into errors (what CI does)",
    )
    parser.add_argument(
        "--serve", action="store_true",
        help="serve the built HTML on http://localhost:8000 afterwards",
    )
    parser.add_argument(
        "--output", default=BUILD_DIR,
        help=f"output directory (default: {os.path.relpath(BUILD_DIR, ROOT)})",
    )
    args = parser.parse_args(argv)

    if not os.path.isdir(DOCS_DIR):
        print(
            f"no docs/ directory at {DOCS_DIR} -- "
            "documentation can only be built from a source checkout",
            file=sys.stderr,
        )
        return 1

    try:
        from sphinx.cmd.build import build_main
    except ImportError:
        print(
            "sphinx is not installed; install the docs extra:\n"
            "    uv sync --extra docs",
            file=sys.stderr,
        )
        return 1

    if args.clean:
        shutil.rmtree(os.path.join(DOCS_DIR, "_build"), ignore_errors=True)
        shutil.rmtree(
            os.path.join(DOCS_DIR, "protocol", "_generated"), ignore_errors=True
        )

    options = ["-b", "html", DOCS_DIR, args.output]
    if args.strict:
        # Keep going after the first warning so one build reports them all.
        options = ["-W", "--keep-going", *options]

    status = build_main(options)
    if status:
        return status

    print(f"\ndocumentation built: {os.path.join(args.output, 'index.html')}")

    if args.serve:
        import http.server
        import socketserver

        os.chdir(args.output)
        handler = http.server.SimpleHTTPRequestHandler
        with socketserver.TCPServer(("", 8000), handler) as httpd:
            print("serving on http://localhost:8000 -- Ctrl-C to stop")
            try:
                httpd.serve_forever()
            except KeyboardInterrupt:
                pass

    return 0


if __name__ == "__main__":
    sys.exit(main())
