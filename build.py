#!/usr/bin/env python3
"""Render the App Bundle Layout specification from Markdown into HTML.

The Markdown file holds the document text. The HTML template holds the page
shell, styles, and table-of-contents behaviour. This script parses the
Markdown, fills in the template, and writes the finished page.

Run it with:

    python3 build.py

Add ``--preview`` to serve the page at http://127.0.0.1:8000/ as well. The
server rebuilds whenever the Markdown or the template changes, rewrites the
output file, and the open page reloads itself. A broken edit shows the error in
the browser instead of a blank page.

The default input, template, and output paths sit next to this script.
"""

from __future__ import annotations

import argparse
import html
import re
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*$")
LIST_RE = re.compile(r"^(\s*)([-*+]|\d+[.)])\s+(.*)$")
FENCE_RE = re.compile(r"^\s*```\s*([^`]*)$")
DIRECTIVE_RE = re.compile(r"^\s*:::\s*(.*?)\s*$")
ID_SUFFIX_RE = re.compile(r"\s*\{#([\w.:-]+)\}\s*$")
ITEM_ID_RE = re.compile(r"^\{#([\w.:-]+)\}\s*")
NUMBER_PREFIX_RE = re.compile(r"^\d+(?:\.\d+)*\.?\s+")
PLACEHOLDER_RE = re.compile(r"\{\{(\w+)\}\}")

REQUIRED_META = ("title", "short_title", "eyebrow", "version", "description", "lede")


class SpecError(Exception):
    """Raised when the Markdown or template cannot be rendered."""


def parse_front_matter(text):
    """Split a Markdown document into front-matter values and body lines.

    Args:
        text: The whole Markdown document.

    Returns:
        A pair ``(meta, body_lines)``. ``meta`` maps keys to plain strings;
        ``body_lines`` is the document after the closing ``---``.
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise SpecError("the document must start with a '---' front-matter block")

    end = None
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            end = index
            break
    if end is None:
        raise SpecError("the front-matter block is never closed with '---'")

    meta = {}
    index = 1
    while index < end:
        line = lines[index]
        if not line.strip():
            index += 1
            continue
        if ":" not in line:
            raise SpecError(f"front-matter line {index + 1} is not 'key: value'")
        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip()
        if key in meta:
            raise SpecError(f"front-matter key {key!r} appears twice")
        if value == ">":
            folded = []
            index += 1
            while index < end and (not lines[index].strip() or lines[index][:1] in " \t"):
                if lines[index].strip():
                    folded.append(lines[index].strip())
                index += 1
            value = " ".join(folded)
        else:
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            index += 1
        meta[key] = value

    for key in REQUIRED_META:
        if not meta.get(key):
            raise SpecError(f"front matter is missing a value for {key!r}")

    return meta, lines[end + 1 :]


def auto_id(text):
    """Return the anchor id implied by a numbered heading, if there is one."""
    match = NUMBER_PREFIX_RE.match(text)
    if match:
        number = match.group(0).strip().rstrip(".")
        return "s" + number
    match = re.match(r"^Appendix\s+([A-Za-z])\b", text)
    if match:
        return "app" + match.group(1).lower()
    return None


def plain_text(text):
    """Strip inline Markdown so a heading can be used as a TOC label."""
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"\\(.)", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    text = text.replace("**", "")
    return text.replace("*", "")


def inline(text):
    """Convert the inline Markdown used by this document into HTML.

    Supported: code spans, bold, italic, links, and backslash escapes. Raw
    HTML in the source is escaped, so angle brackets can be written directly.

    Args:
        text: One line or paragraph of Markdown.

    Returns:
        HTML with inline elements rendered.
    """
    tokens = []

    def protect(fragment):
        tokens.append(fragment)
        return "\x00%d\x00" % (len(tokens) - 1)

    pieces = []
    index = 0
    while index < len(text):
        char = text[index]
        if char == "`":
            close = text.find("`", index + 1)
            if close == -1:
                pieces.append(char)
                index += 1
                continue
            code = text[index + 1 : close]
            pieces.append(protect("<code>" + html.escape(code, quote=False) + "</code>"))
            index = close + 1
        elif char == "\\" and index + 1 < len(text):
            pieces.append(protect(html.escape(text[index + 1], quote=False)))
            index += 2
        else:
            pieces.append(char)
            index += 1

    # Escape HTML only after code spans and escapes have been protected.
    rendered = html.escape("".join(pieces), quote=False)

    def link(match):
        label, href = match.group(1), match.group(2)
        css = ' class="xref"' if plain_text(label).startswith("§") else ""
        return f'<a{css} href="{href}">{label}</a>'

    rendered = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", link, rendered)
    rendered = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", rendered)
    rendered = re.sub(r"\*([^*]+)\*", r"<em>\1</em>", rendered)

    def restore(match):
        return tokens[int(match.group(1))]

    return re.sub("\x00(\\d+)\x00", restore, rendered)


class Renderer:
    """Turn body Markdown lines into article HTML and TOC entries."""

    def __init__(self):
        self.toc = []

    def render(self, lines, indent=4):
        """Render a sequence of Markdown lines as indented HTML blocks."""
        blocks = []
        index = 0
        while index < len(lines):
            line = lines[index]
            if not line.strip():
                index += 1
                continue
            if FENCE_RE.match(line):
                block, index = self.render_code(lines, index, indent)
            elif DIRECTIVE_RE.match(line):
                block, index = self.render_directive(lines, index, indent)
            elif HEADING_RE.match(line):
                block = self.render_heading(line, indent)
                index += 1
            elif line.lstrip().startswith("|"):
                block, index = self.render_table(lines, index, indent, mono=False)
            elif self.is_top_level_list(line):
                block, index = self.render_list(lines, index, 0, indent)
            else:
                block, index = self.render_paragraph(lines, index, indent)
            blocks.append(block)
        return "\n\n".join(blocks)

    def render_heading(self, line, indent):
        """Render one heading, recording level-two headings for the TOC."""
        match = HEADING_RE.match(line)
        level = len(match.group(1))
        if level not in (2, 3):
            raise SpecError(f"only level-two and level-three headings are supported: {line!r}")

        text = match.group(2)
        explicit = None
        suffix = ID_SUFFIX_RE.search(text)
        if suffix:
            explicit = suffix.group(1)
            text = text[: suffix.start()]

        ident = explicit or auto_id(text)
        if level == 2:
            if not ident:
                raise SpecError(f"heading has no usable id: {text!r}")
            label = NUMBER_PREFIX_RE.sub("", plain_text(text), count=1)
            self.toc.append((ident, label, ident.startswith("app")))

        id_attr = f' id="{ident}"' if ident else ""
        return f"{' ' * indent}<h{level}{id_attr}>{inline(text)}</h{level}>"

    @staticmethod
    def is_top_level_list(line):
        """Say whether a line starts a list item with no indentation."""
        match = LIST_RE.match(line)
        return bool(match and len(match.group(1)) == 0)

    def render_paragraph(self, lines, index, indent):
        """Render consecutive plain lines as one paragraph."""
        parts = []
        while index < len(lines):
            line = lines[index]
            if not line.strip():
                break
            if parts and self.starts_block(line):
                break
            parts.append(line.strip())
            index += 1
        return f"{' ' * indent}<p>{inline(' '.join(parts))}</p>", index

    @staticmethod
    def starts_block(line):
        """Say whether a line begins a block that a paragraph must not absorb."""
        if HEADING_RE.match(line) or FENCE_RE.match(line) or DIRECTIVE_RE.match(line):
            return True
        if line.lstrip().startswith("|"):
            return True
        match = LIST_RE.match(line)
        return bool(match and len(match.group(1)) == 0)

    def render_code(self, lines, index, indent):
        """Render a fenced code block, or a directory tree when tagged 'tree'."""
        info = FENCE_RE.match(lines[index]).group(1).strip()
        index += 1
        content = []
        while index < len(lines) and not lines[index].strip().startswith("```"):
            content.append(lines[index])
            index += 1
        if index >= len(lines):
            raise SpecError("a code fence is never closed")
        index += 1

        if info == "tree":
            return self.render_tree(content, indent), index

        language = f' data-lang="{html.escape(info, quote=True)}"' if info else ""
        code = html.escape("\n".join(content), quote=False)
        figure = (
            f"{' ' * indent}<figure class=\"code\"{language}>"
            f"<pre><code>{code}</code></pre></figure>"
        )
        return figure, index

    @staticmethod
    def render_tree(content, indent):
        """Render tree text, marking the root and comment tails."""
        rows = []
        for number, line in enumerate(content):
            if number == 0:
                rows.append(f'<span class="t-root">{html.escape(line, quote=False)}</span>')
                continue
            hash_index = line.find("#")
            if hash_index == -1:
                rows.append(html.escape(line, quote=False))
            else:
                lead = html.escape(line[:hash_index], quote=False)
                comment = html.escape(line[hash_index:], quote=False)
                rows.append(f'{lead}<span class="t-c">{comment}</span>')
        return (
            f"{' ' * indent}<figure class=\"tree-figure\"><pre class=\"tree\">"
            + "\n".join(rows)
            + "</pre></figure>"
        )

    def render_directive(self, lines, index, indent):
        """Render a '::: note' or '::: table [mono]' block."""
        fields = DIRECTIVE_RE.match(lines[index]).group(1).split()
        if not fields:
            raise SpecError("a ':::' block needs a name, such as 'note' or 'table'")
        kind = fields[0]
        index += 1
        body = []
        while index < len(lines) and not DIRECTIVE_RE.match(lines[index]):
            body.append(lines[index])
            index += 1
        if index >= len(lines):
            raise SpecError(f"the '::: {kind}' block is never closed")
        index += 1

        if kind == "note" and len(fields) == 1:
            inner = self.render(body, indent + 2)
            note = f"{' ' * indent}<div class=\"note\">\n{inner}\n{' ' * indent}</div>"
            return note, index
        if kind == "table":
            mono = "mono" in fields[1:]
            table = self.render_table_html(body, indent + 2, mono)
            wrapper = (
                f"{' ' * indent}<div class=\"table-wrap\">\n{table}\n"
                f"{' ' * indent}</div>"
            )
            return wrapper, index
        raise SpecError(f"unknown ':::' block: {' '.join(fields)}")

    def render_table(self, lines, index, indent, mono):
        """Render a bare pipe table that was not wrapped in a ':::' block."""
        body = []
        while index < len(lines) and lines[index].lstrip().startswith("|"):
            body.append(lines[index])
            index += 1
        table = self.render_table_html(body, indent, mono)
        return table, index

    @staticmethod
    def split_row(row):
        """Split one pipe-table row into stripped cells."""
        row = row.strip()
        if row.startswith("|"):
            row = row[1:]
        if row.endswith("|"):
            row = row[:-1]
        return [cell.strip() for cell in row.split("|")]

    def render_table_html(self, body, indent, mono):
        """Render pipe-table rows as a table element."""
        rows = [line for line in body if line.strip()]
        if len(rows) < 2:
            raise SpecError("a table needs a header row and a divider row")
        header = self.split_row(rows[0])
        divider = self.split_row(rows[1])
        if len(divider) != len(header) or not all(
            re.fullmatch(r":?-{3,}:?", cell) for cell in divider
        ):
            raise SpecError("a table divider row must be made of --- cells")
        body_rows = [self.split_row(row) for row in rows[2:]]
        for row in body_rows:
            if len(row) != len(header):
                raise SpecError(
                    f"table row has {len(row)} cells but the header has {len(header)}"
                )

        css = ' class="mono"' if mono else ""
        pad = " " * indent
        out = [f"{pad}<table{css}>"]
        head_cells = "".join(
            f'<th scope="col">{inline(cell)}</th>' for cell in header
        )
        out.append(f"{pad}  <thead><tr>{head_cells}</tr></thead>")
        out.append(f"{pad}  <tbody>")
        for row in body_rows:
            cells = "".join(f"<td>{inline(cell)}</td>" for cell in row)
            out.append(f"{pad}    <tr>{cells}</tr>")
        out.append(f"{pad}  </tbody>")
        out.append(f"{pad}</table>")
        return "\n".join(out)

    def render_list(self, lines, index, source_indent, output_indent):
        """Render a bullet or numbered list, including nested lists.

        Args:
            lines: All body lines.
            index: Line where this list starts.
            source_indent: Indent width of the list markers in the source.
            output_indent: Indent width for the rendered list tag.

        Returns:
            A pair of the rendered HTML and the next unread line index.
        """
        first = LIST_RE.match(lines[index])
        ordered = first.group(2)[0].isdigit()
        tag = "ol" if ordered else "ul"
        out = [f"{' ' * output_indent}<{tag}>"]
        item_indent = output_indent + 2

        while index < len(lines):
            match = LIST_RE.match(lines[index])
            if not match:
                break
            indent = len(match.group(1))
            if indent != source_indent or match.group(2)[0].isdigit() != ordered:
                break

            item_text = match.group(3)
            item_id = None
            id_match = ITEM_ID_RE.match(item_text)
            if id_match:
                item_id = id_match.group(1)
                item_text = item_text[id_match.end() :]
            index += 1

            parts = []
            buffer = item_text
            while index < len(lines):
                line = lines[index]
                if not line.strip():
                    lookahead = index + 1
                    while lookahead < len(lines) and not lines[lookahead].strip():
                        lookahead += 1
                    if lookahead >= len(lines):
                        index = lookahead
                        break
                    next_line = lines[lookahead]
                    next_indent = len(next_line) - len(next_line.lstrip())
                    next_match = LIST_RE.match(next_line)
                    continues_list = bool(
                        next_match and len(next_match.group(1)) == source_indent
                    )
                    if continues_list or next_indent < source_indent:
                        index = lookahead
                        break
                    if buffer:
                        parts.append(("text", buffer))
                        buffer = ""
                    index += 1
                    continue

                line_indent = len(line) - len(line.lstrip())
                nested = LIST_RE.match(line)
                # A new item, or plain text back at the marker's indent, ends
                # this item. The outer loop picks up the next item.
                if line_indent <= source_indent:
                    break
                if nested:
                    if buffer:
                        parts.append(("text", buffer))
                        buffer = ""
                    nested_html, index = self.render_list(
                        lines, index, line_indent, output_indent + 4
                    )
                    parts.append(("list", nested_html))
                else:
                    buffer = (buffer + " " + line.strip()).strip()
                    index += 1
            if buffer:
                parts.append(("text", buffer))

            id_attr = f' id="{item_id}"' if item_id else ""
            opening = f"{' ' * item_indent}<li{id_attr}>"
            if len(parts) == 1 and parts[0][0] == "text":
                out.append(f"{opening}{inline(parts[0][1])}</li>")
                continue

            out.append(opening + (inline(parts[0][1]) if parts and parts[0][0] == "text" else ""))
            for kind, value in parts[1:]:
                if kind == "text":
                    out.append(f"{' ' * (output_indent + 4)}{inline(value)}")
                else:
                    out.append(value)
            out.append(f"{' ' * item_indent}</li>")

        out.append(f"{' ' * output_indent}</{tag}>")
        return "\n".join(out), index


def render_toc(entries):
    """Render the contents navigation from recorded level-two headings."""
    primary = [entry for entry in entries if not entry[2]]
    appendix = [entry for entry in entries if entry[2]]
    pad = " " * 6
    lines = [f'{pad}<p class="toc-title">Contents</p>']
    if primary:
        lines.append(f"{pad}<ol>")
        for ident, label, _ in primary:
            lines.append(
                f'{pad}  <li><a href="#{ident}">{html.escape(label, quote=True)}</a></li>'
            )
        lines.append(f"{pad}</ol>")
    if appendix:
        lines.append(f'{pad}<ul class="appendix">')
        for ident, label, _ in appendix:
            lines.append(
                f'{pad}  <li><a href="#{ident}">{html.escape(label, quote=True)}</a></li>'
            )
        lines.append(f"{pad}</ul>")
    return "\n".join(lines)


def build_html(markdown_text, template_text):
    """Render a complete specification page.

    Args:
        markdown_text: The Markdown document, including front matter.
        template_text: The HTML page template with ``{{name}}`` placeholders.

    Returns:
        The finished HTML document.

    Raises:
        SpecError: If the Markdown or the template is invalid.
    """
    meta, body_lines = parse_front_matter(markdown_text)
    renderer = Renderer()
    content = renderer.render(body_lines, indent=4)
    values = dict(meta)
    values["content"] = content
    values["toc"] = render_toc(renderer.toc)

    missing = sorted(set(PLACEHOLDER_RE.findall(template_text)) - values.keys())
    if missing:
        names = ", ".join("{{" + name + "}}" for name in missing)
        raise SpecError(f"template placeholders with no value: {names}")

    def replace(match):
        key = match.group(1)
        if key in ("content", "toc"):
            return values[key]
        return html.escape(values[key], quote=True)

    return PLACEHOLDER_RE.sub(replace, template_text)


def source_stamp(paths):
    """Return a token that changes whenever one of the files changes.

    Args:
        paths: Files to watch, usually the Markdown source and the template.

    Returns:
        A short string built from each file's size and modification time. A
        missing file yields a token that differs from every readable state, so
        a file that appears or disappears also counts as a change.
    """
    parts = []
    for path in paths:
        try:
            info = path.stat()
        except OSError:
            parts.append("missing")
            continue
        parts.append(f"{info.st_size}:{info.st_mtime_ns}")
    return "|".join(parts)


def with_reload_script(page, version):
    """Add the script that reloads the page when the sources change.

    Args:
        page: A complete HTML document.
        version: Stamp to compare the server's current stamp against.

    Returns:
        The page with a small polling script before ``</body>``. Polling is used
        rather than a socket because it survives sleeps, reloads, and restarts
        of the server without leaving the browser stuck.
    """
    script = (
        "<script>\n"
        "  // Ask the preview server whether the sources changed; reload if so.\n"
        "  (function () {\n"
        f'    var seen = "{version}";\n'
        "    function check() {\n"
        '      fetch("/__version", { cache: "no-store" })\n'
        "        .then(function (response) { return response.text(); })\n"
        "        .then(function (current) {\n"
        "          if (current !== seen) window.location.reload();\n"
        "        })\n"
        '        .catch(function () { /* server restarting; try again next tick */ });\n'
        "    }\n"
        "    window.setInterval(check, 400);\n"
        "  })();\n"
        "</script>\n"
    )
    if "</body>" in page:
        return page.replace("</body>", script + "</body>", 1)
    return page + script


def error_page(message, version):
    """Render a plain page that shows a failed build.

    Args:
        message: The error text to display.
        version: Stamp of the sources this failure came from.

    Returns:
        A small, self-contained HTML document. It keeps auto-reload, so fixing
        the source replaces the error with a fresh build.
    """
    page = (
        "<!doctype html>\n"
        '<meta charset="utf-8">\n'
        "<title>Build failed</title>\n"
        '<body style="font: 1rem/1.6 system-ui; padding: 2rem">'
        "<h1>Build failed</h1>"
        f"<pre>{html.escape(message)}</pre>"
        "<p>Fix the source and the page reloads itself. "
        "The last good build is still on disk.</p>"
        "</body>\n"
    )
    return with_reload_script(page, version)


class Preview:
    """Rebuild the page when its sources change, and remember the last result.

    The build is keyed on a stamp of the source files, so repeated requests for
    an unchanged document reuse the previous render instead of rebuilding it.
    """

    def __init__(self, input_path, template_path, output_path):
        self.input_path = input_path
        self.template_path = template_path
        self.output_path = output_path
        self.stamp = None
        self.status = 200
        self.page = ""

    def refresh(self):
        """Rebuild if a source file changed, writing the output on success.

        Returns:
            A pair ``(status, page)`` where status is 200 for a good build and
            500 for a failed one.
        """
        current = source_stamp((self.input_path, self.template_path))
        if current == self.stamp:
            return self.status, self.page

        self.stamp = current
        try:
            markdown_text = self.input_path.read_text(encoding="utf-8")
            template_text = self.template_path.read_text(encoding="utf-8")
            page = build_html(markdown_text, template_text)
        except (OSError, SpecError) as exc:
            self.status = 500
            self.page = error_page(str(exc), current)
            return self.status, self.page

        self.output_path.write_text(page, encoding="utf-8")
        print(f"rebuilt {self.output_path}", flush=True)
        self.status = 200
        self.page = with_reload_script(page, current)
        return self.status, self.page


def make_handler(state):
    """Build a request handler that serves the previewed page.

    Args:
        state: The :class:`Preview` that owns the build.

    Returns:
        A handler class for ``HTTPServer``. ``/`` serves the page and
        ``/__version`` serves the current source stamp. Nothing else is
        reachable, so the rest of the repository stays private.
    """

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            route = self.path.split("?", 1)[0]
            if route == "/__version":
                state.refresh()
                self.send_body(200, "text/plain; charset=utf-8", state.stamp)
            elif route in ("/", "/index.html"):
                status, page = state.refresh()
                self.send_body(status, "text/html; charset=utf-8", page)
            else:
                self.send_error(404)

        def send_body(self, status, content_type, text):
            """Write one response with no caching."""
            body = text.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            # Never cache, so a reload always shows the current source.
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            """Hide the per-request log line; the rebuild message is enough."""

    return Handler


def serve(state, port):
    """Serve the specification on the local machine until interrupted.

    Args:
        state: The :class:`Preview` that owns the build.
        port: Port on the loopback interface.

    Raises:
        SpecError: If the port cannot be opened.
    """
    try:
        server = HTTPServer(("127.0.0.1", port), make_handler(state))
    except OSError as exc:
        raise SpecError(f"cannot listen on 127.0.0.1:{port}: {exc.strerror}") from exc

    print(
        f"preview at http://127.0.0.1:{server.server_port}/ (ctrl-c to stop)",
        flush=True,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print()
    finally:
        server.server_close()


def main(argv=None):
    """Read the source files, write the HTML page, and report the result."""
    here = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description="Render the specification Markdown into HTML.")
    parser.add_argument(
        "-i", "--input", type=Path, default=here / "spec-1.1.md", help="Markdown source"
    )
    parser.add_argument(
        "-t",
        "--template",
        type=Path,
        default=here / "spec-1.1.template.html",
        help="HTML page template",
    )
    parser.add_argument(
        "-o", "--output", type=Path, default=here / "spec-1.1.html", help="HTML output"
    )
    parser.add_argument(
        "--preview", action="store_true", help="serve the page after writing it, until ctrl-c"
    )
    parser.add_argument(
        "--port", type=int, default=8000, help="port for --preview (default: 8000)"
    )
    args = parser.parse_args(argv)

    if args.preview:
        build_state = Preview(args.input, args.template, args.output)
        status, _ = build_state.refresh()
        if status != 200:
            print("fix the source, then reload the page to try again", file=sys.stderr)
        try:
            serve(build_state, args.port)
        except SpecError as exc:
            print(f"build: {exc}", file=sys.stderr)
            return 1
        return 0

    try:
        markdown_text = args.input.read_text(encoding="utf-8")
        template_text = args.template.read_text(encoding="utf-8")
        page = build_html(markdown_text, template_text)
        args.output.write_text(page, encoding="utf-8")
    except (OSError, SpecError) as exc:
        print(f"build: {exc}", file=sys.stderr)
        return 1

    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
