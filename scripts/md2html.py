#!/usr/bin/env python3
"""
Lightweight Markdown to HTML converter for multi-model compare cards.
No external dependencies required.

Supports:
- Headings (h1-h6), paragraphs
- Bold, italic, bold+italic
- Inline code, fenced code blocks (with language)
- Unordered and ordered lists
- Tables
- Blockquotes
- Images (inline)
- Links
- Horizontal rules
- Math notation ($...$, $$...$$) - preserved for MathJax rendering

Usage:
    python md2html.py < input.md
    python md2html.py --input file.md
    python md2html.py --text "# Hello\nWorld"
"""

import re
import sys
import html
import argparse


def md_to_html(md: str) -> str:
    """Convert simple Markdown to HTML with multimodal support."""
    lines = md.split("\n")
    result = []
    in_code_block = False
    code_lang = ""
    in_list = False
    list_type = None  # 'ul' or 'ol'
    in_table = False
    table_rows = []

    def flush_table():
        nonlocal in_table, table_rows
        if not table_rows:
            return ""
        out = "<table>\n"
        for i, row in enumerate(table_rows):
            cells = [c.strip() for c in row.strip("|").split("|")]
            # Skip separator row
            if all(re.match(r"^[-:]+$", c.strip()) for c in cells):
                continue
            tag = "th" if i == 0 else "td"
            out += "<tr>" + "".join(f"<{tag}>{inline(c)}</{tag}>" for c in cells) + "</tr>\n"
        out += "</table>\n"
        in_table = False
        table_rows = []
        return out

    def flush_list():
        nonlocal in_list, list_type
        if in_list:
            in_list = False
            return f"</{list_type}>\n"
        return ""

    def inline(text: str) -> str:
        """Process inline Markdown elements."""
        # Code (must come first)
        text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)

        # Images: ![alt](url) - preserve for multimodal output
        text = re.sub(r"!\[([^\]]*)\]\(([^)]+)\)", r'<img src="\2" alt="\1">', text)

        # Bold + Italic
        text = re.sub(r"\*\*\*(.+?)\*\*\*", r"<strong><em>\1</em></strong>", text)
        # Bold
        text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
        # Italic
        text = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"<em>\1</em>", text)

        # Links (but not already matched as images)
        text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2" target="_blank">\1</a>', text)

        # Math inline $...$ - preserve for MathJax
        text = re.sub(r'\$([^$\n]+)\$', r'<span class="math-inline">\($1\)</span>', text)

        return text

    i = 0
    while i < len(lines):
        line = lines[i]

        # Fenced code block
        if line.strip().startswith("```"):
            if in_code_block:
                result.append("</code></pre>\n")
                in_code_block = False
                code_lang = ""
            else:
                result.append(flush_list())
                result.append(flush_table())
                lang = line.strip()[3:].strip()
                code_lang = lang
                if lang == "math":
                    result.append('<pre><code class="language-math">')
                else:
                    result.append(f'<pre><code class="language-{lang}">' if lang else "<pre><code>")
                in_code_block = True
            i += 1
            continue

        if in_code_block:
            result.append(html.escape(line) + "\n")
            i += 1
            continue

        # Table
        if "|" in line and line.strip().startswith("|"):
            result.append(flush_list())
            if not in_table:
                in_table = True
            table_rows.append(line)
            i += 1
            continue
        elif in_table:
            result.append(flush_table())

        # Blank line
        if not line.strip():
            result.append(flush_list())
            i += 1
            continue

        # Math block $$...$$
        math_block_start = re.match(r'^\$\$(.*)\$\$$', line.strip())
        if math_block_start:
            result.append(flush_list())
            content = math_block_start.group(1)
            result.append(f'<div class="math-block">\\[{content}\\]</div>\n')
            i += 1
            continue

        # Headers
        hm = re.match(r"^(#{1,6})\s+(.+)$", line)
        if hm:
            result.append(flush_list())
            level = len(hm.group(1))
            result.append(f"<h{level}>{inline(hm.group(2))}</h{level}>\n")
            i += 1
            continue

        # Horizontal rule
        if re.match(r"^(-{3,}|_{3,}|\*{3,})$", line.strip()):
            result.append(flush_list())
            result.append("<hr>\n")
            i += 1
            continue

        # Blockquote (multi-line support)
        if line.strip().startswith("> "):
            result.append(flush_list())
            quote_content = inline(line.strip()[2:])
            result.append(f"<blockquote>{quote_content}</blockquote>\n")
            i += 1
            continue

        # Image on its own line: ![alt](url)
        img_match = re.match(r"^!\[([^\]]*)\]\(([^)]+)\)\s*$", line.strip())
        if img_match:
            result.append(flush_list())
            alt = img_match.group(1)
            url = img_match.group(2)
            result.append(f'<p><img src="{url}" alt="{alt}" style="max-width:100%;border-radius:8px;"></p>\n')
            i += 1
            continue

        # Unordered list
        um = re.match(r"^(\s*)[-*+]\s+(.+)$", line)
        if um:
            if not in_list or list_type != "ul":
                result.append(flush_list())
                in_list = True
                list_type = "ul"
                result.append("<ul>\n")
            result.append(f"<li>{inline(um.group(2))}</li>\n")
            i += 1
            continue

        # Ordered list
        om = re.match(r"^(\s*)\d+\.\s+(.+)$", line)
        if om:
            if not in_list or list_type != "ol":
                result.append(flush_list())
                in_list = True
                list_type = "ol"
                result.append("<ol>\n")
            result.append(f"<li>{inline(om.group(2))}</li>\n")
            i += 1
            continue

        # Paragraph
        result.append(flush_list())
        result.append(f"<p>{inline(line)}</p>\n")
        i += 1

    # Flush remaining
    result.append(flush_list())
    result.append(flush_table())
    if in_code_block:
        result.append("</code></pre>\n")

    return "".join(result)


def main():
    parser = argparse.ArgumentParser(description="Convert Markdown to HTML (multimodal)")
    parser.add_argument("--input", "-i", help="Input markdown file")
    parser.add_argument("--text", "-t", help="Direct markdown text input")
    args = parser.parse_args()

    if args.text:
        md = args.text
    elif args.input:
        with open(args.input, "r", encoding="utf-8") as f:
            md = f.read()
    else:
        md = sys.stdin.read()

    print(md_to_html(md))


if __name__ == "__main__":
    main()
