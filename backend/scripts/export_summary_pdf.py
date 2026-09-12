#!/usr/bin/env python3
"""Export SUMMARY.md to a publication-grade PDF using headless Google Chrome.

Parses Markdown, renders Mermaid diagrams as inline SVGs, applies elegant
academic typography and print styling, and generates SUMMARY.pdf.
"""

from pathlib import Path
import re
import subprocess
import sys
import markdown

ROOT = Path(__file__).resolve().parents[2]
SUMMARY_MD = ROOT / "SUMMARY.md"
OUTPUT_HTML = ROOT / "SUMMARY.html"
OUTPUT_PDF = ROOT / "SUMMARY.pdf"

CHROME_BIN = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"


def convert_markdown_to_html(md_text: str) -> str:
    # Convert ```mermaid ... ``` blocks to <div class="mermaid">...</div>
    def replace_mermaid(match):
        code = match.group(1).strip()
        return f'<div class="mermaid-container"><pre class="mermaid">\n{code}\n</pre></div>'

    processed_md = re.sub(
        r"```mermaid\s*\n(.*?)```", replace_mermaid, md_text, flags=re.DOTALL
    )

    extensions = [
        "tables",
        "fenced_code",
        "codehilite",
        "toc",
        "attr_list",
        "def_list",
        "sane_lists",
    ]

    html_body = markdown.markdown(processed_md, extensions=extensions)

    # Convert GitHub style alerts: > [!NOTE], > [!IMPORTANT], etc.
    def replace_alert(match):
        alert_type = match.group(1).lower()
        content = match.group(2).strip()
        icon = {
            "note": "ℹ️",
            "tip": "💡",
            "important": "⚡",
            "warning": "⚠️",
            "caution": "🛑",
        }.get(alert_type, "📌")
        title = alert_type.upper()
        return (
            f'<div class="alert alert-{alert_type}">'
            f'<div class="alert-title"><span class="alert-icon">{icon}</span> {title}</div>'
            f'<div class="alert-content">{content}</div>'
            f'</div>'
        )

    # Match blockquotes containing [!TYPE]
    html_body = re.sub(
        r"<blockquote>\s*<p>\[!(NOTE|TIP|IMPORTANT|WARNING|CAUTION)\]\s*<br\s*/?>\s*(.*?)</p>\s*</blockquote>",
        replace_alert,
        html_body,
        flags=re.DOTALL | re.IGNORECASE,
    )

    return html_body


def build_full_html(body: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Aletheia: Comprehensive Architectural & Technical Summary</title>
<!-- Google Fonts -->
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,600;9..144,700&family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600&family=Source+Serif+4:ital,opsz,wght@0,8..60,400;0,8..60,600;1,8..60,400&display=swap" rel="stylesheet">
<!-- Mermaid.js -->
<script src="https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js"></script>
<script>
  mermaid.initialize({{
    startOnLoad: true,
    theme: 'base',
    themeVariables: {{
      primaryColor: '#e0e7ff',
      primaryTextColor: '#1e293b',
      primaryBorderColor: '#6366f1',
      lineColor: '#475569',
      secondaryColor: '#f1f5f9',
      tertiaryColor: '#f8fafc',
      fontFamily: 'Inter, -apple-system, sans-serif',
      fontSize: '13px'
    }},
    flowchart: {{
      useMaxWidth: true,
      htmlLabels: true,
      curve: 'basis',
      padding: 12
    }}
  }});
</script>
<style>
  :root {{
    --font-sans: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    --font-serif: 'Source Serif 4', Georgia, serif;
    --font-display: 'Fraunces', Georgia, serif;
    --font-mono: 'JetBrains Mono', monospace;
    --color-primary: #0f172a;
    --color-secondary: #334155;
    --color-muted: #64748b;
    --color-brass: #b38b3f;
    --color-brass-light: #fdfaf3;
    --color-border: #e2e8f0;
    --color-surface: #ffffff;
    --color-surface-subtle: #f8fafc;
    --color-code-bg: #1e293b;
  }}

  @page {{
    size: A4 portrait;
    margin: 18mm 16mm 18mm 16mm;
    @top-left {{
      content: "Aletheia — Technical & Architectural Summary";
      font-family: var(--font-sans);
      font-size: 8pt;
      font-weight: 500;
      color: #94a3b8;
    }}
    @top-right {{
      content: "Confidential / Internal Report";
      font-family: var(--font-sans);
      font-size: 8pt;
      color: #94a3b8;
    }}
    @bottom-left {{
      content: "Project Aletheia";
      font-family: var(--font-sans);
      font-size: 8pt;
      color: #94a3b8;
    }}
    @bottom-right {{
      content: "Page " counter(page);
      font-family: var(--font-mono);
      font-size: 8pt;
      font-weight: 600;
      color: #64748b;
    }}
  }}

  * {{
    box-sizing: border-box;
    -webkit-print-color-adjust: exact !important;
    print-color-adjust: exact !important;
  }}

  body {{
    font-family: var(--font-sans);
    font-size: 10.5pt;
    line-height: 1.6;
    color: var(--color-primary);
    background-color: var(--color-surface);
    margin: 0;
    padding: 0;
  }}

  /* Typography */
  h1, h2, h3, h4, h5, h6 {{
    color: #090d16;
    font-weight: 700;
    line-height: 1.25;
    margin-top: 1.6em;
    margin-bottom: 0.6em;
    page-break-after: avoid;
    break-after: avoid;
  }}

  h1 {{
    font-family: var(--font-display);
    font-size: 24pt;
    font-weight: 700;
    letter-spacing: -0.02em;
    border-bottom: 2px solid #b38b3f;
    padding-bottom: 8px;
    margin-top: 0;
  }}

  h2 {{
    font-family: var(--font-display);
    font-size: 16pt;
    font-weight: 600;
    border-bottom: 1px solid var(--color-border);
    padding-bottom: 6px;
    margin-top: 2em;
    page-break-before: auto;
  }}

  h3 {{
    font-size: 12.5pt;
    font-weight: 600;
    color: #1e293b;
    margin-top: 1.4em;
  }}

  h4 {{
    font-size: 11pt;
    font-weight: 600;
    color: #334155;
    margin-top: 1.1em;
  }}

  p, li {{
    color: #273444;
    font-size: 10pt;
    line-height: 1.65;
  }}

  strong {{
    font-weight: 600;
    color: #0f172a;
  }}

  /* Blockquote / Intro callout */
  blockquote {{
    margin: 1.2em 0;
    padding: 12px 18px;
    background: var(--color-brass-light);
    border-left: 4px solid var(--color-brass);
    border-radius: 0 6px 6px 0;
    font-family: var(--font-serif);
    font-size: 10.5pt;
    font-style: italic;
    color: #453415;
    page-break-inside: avoid;
    break-inside: avoid;
  }}

  blockquote p {{
    margin: 0;
    color: #453415;
    font-size: 10pt;
    line-height: 1.6;
  }}

  /* Tables */
  table {{
    width: 100%;
    border-collapse: collapse;
    margin: 1.4em 0;
    font-size: 8.8pt;
    page-break-inside: avoid;
    break-inside: avoid;
    box-shadow: 0 1px 3px rgba(0,0,0,0.04);
    border-radius: 6px;
    overflow: hidden;
    border: 1px solid #cbd5e1;
  }}

  th, td {{
    padding: 8px 11px;
    text-align: left;
    vertical-align: top;
    border-bottom: 1px solid #e2e8f0;
  }}

  th {{
    background-color: #0f172a;
    color: #ffffff;
    font-weight: 600;
    font-size: 8.5pt;
    letter-spacing: 0.03em;
    text-transform: uppercase;
  }}

  tr:nth-child(even) {{
    background-color: #f8fafc;
  }}

  tr:hover {{
    background-color: #f1f5f9;
  }}

  td strong {{
    color: #0f172a;
  }}

  /* Code blocks & inline code */
  code {{
    font-family: var(--font-mono);
    font-size: 8.8pt;
    background-color: #f1f5f9;
    color: #0f172a;
    padding: 2px 5px;
    border-radius: 4px;
    border: 1px solid #e2e8f0;
  }}

  pre {{
    background-color: #0f172a;
    color: #f8fafc;
    padding: 14px 16px;
    border-radius: 6px;
    overflow-x: auto;
    font-family: var(--font-mono);
    font-size: 8.2pt;
    line-height: 1.5;
    margin: 1.2em 0;
    page-break-inside: avoid;
    break-inside: avoid;
    border: 1px solid #1e293b;
  }}

  pre code {{
    background-color: transparent;
    color: inherit;
    padding: 0;
    border: none;
    font-size: 8.2pt;
  }}

  /* Mermaid diagrams */
  .mermaid-container {{
    margin: 1.6em 0;
    padding: 16px;
    background: #ffffff;
    border: 1px solid #cbd5e1;
    border-radius: 8px;
    page-break-inside: avoid;
    break-inside: avoid;
    display: flex;
    justify-content: center;
    box-shadow: 0 1px 4px rgba(0,0,0,0.03);
  }}

  .mermaid {{
    text-align: center;
    font-family: var(--font-sans);
  }}

  .mermaid svg {{
    max-width: 100% !important;
    height: auto !important;
  }}

  /* Custom Alert Banners */
  .alert {{
    margin: 1.2em 0;
    padding: 12px 16px;
    border-radius: 6px;
    border-left: 4px solid #6366f1;
    background-color: #eef2ff;
    page-break-inside: avoid;
    break-inside: avoid;
  }}

  .alert-title {{
    font-weight: 700;
    font-size: 9.5pt;
    margin-bottom: 4px;
    color: #312e81;
    display: flex;
    align-items: center;
    gap: 6px;
  }}

  .alert-content {{
    font-size: 9.2pt;
    color: #3730a3;
  }}

  .alert-warning {{
    border-left-color: #f59e0b;
    background-color: #fffbeb;
  }}
  .alert-warning .alert-title {{ color: #92400e; }}
  .alert-warning .alert-content {{ color: #78350f; }}

  .alert-important {{
    border-left-color: #dc2626;
    background-color: #fef2f2;
  }}
  .alert-important .alert-title {{ color: #991b1b; }}
  .alert-important .alert-content {{ color: #7f1d1d; }}

  /* Lists */
  ul, ol {{
    padding-left: 1.4em;
    margin: 0.8em 0;
  }}

  li {{
    margin-bottom: 0.35em;
  }}

  li::marker {{
    color: var(--color-brass);
    font-weight: bold;
  }}

  hr {{
    border: none;
    border-top: 1px solid #cbd5e1;
    margin: 2.2em 0;
    page-break-after: avoid;
  }}

  /* Badges & Meta */
  .badge {{
    display: inline-block;
    padding: 2px 7px;
    font-size: 7.5pt;
    font-weight: 600;
    font-family: var(--font-mono);
    border-radius: 4px;
    background: #e2e8f0;
    color: #1e293b;
    vertical-align: middle;
  }}

  /* Header banner for document cover feel */
  .doc-header {{
    background: linear-gradient(135deg, #0f172a 0%, #1e293b 100%);
    color: #ffffff;
    padding: 26px 30px;
    border-radius: 8px;
    margin-bottom: 2em;
    border-left: 6px solid #b38b3f;
    box-shadow: 0 4px 6px -1px rgba(0,0,0,0.1);
  }}

  .doc-header h1 {{
    color: #ffffff;
    border-bottom: none;
    padding-bottom: 0;
    margin: 0 0 6px 0;
    font-size: 26pt;
  }}

  .doc-header .subtitle {{
    font-family: var(--font-serif);
    font-size: 11pt;
    color: #cbd5e1;
    font-style: italic;
    margin-bottom: 14px;
  }}

  .doc-header .meta-bar {{
    display: flex;
    flex-wrap: wrap;
    gap: 16px;
    font-size: 8.5pt;
    color: #94a3b8;
    border-top: 1px solid rgba(255,255,255,0.15);
    padding-top: 10px;
    margin-top: 8px;
  }}

  .meta-item {{
    display: flex;
    align-items: center;
    gap: 5px;
  }}

  .meta-label {{
    color: #e2e8f0;
    font-weight: 600;
  }}
</style>
</head>
<body>

<div class="doc-header">
  <h1>Aletheia</h1>
  <div class="subtitle">High-Assurance Scientific Research Intelligence & Grounded Synthesis Platform</div>
  <div class="meta-bar">
    <div class="meta-item"><span class="meta-label">System Architecture:</span> Next.js 16 + FastAPI + PostgreSQL 17 (pgvector)</div>
    <div class="meta-item"><span class="meta-label">Research Lab:</span> 3 Google Colab Notebooks + NumPy/PyTorch MLPs</div>
    <div class="meta-item"><span class="meta-label">Date:</span> September 2026</div>
    <div class="meta-item"><span class="meta-label">Status:</span> Phase 1 Complete · Fully Wired</div>
  </div>
</div>

{body}

</body>
</html>
"""


def main():
    print(f"Reading Markdown: {SUMMARY_MD}")
    md_content = SUMMARY_MD.read_text(encoding="utf-8")

    print("Converting Markdown to HTML with Mermaid and Academic CSS...")
    html_body = convert_markdown_to_html(md_content)
    full_html = build_full_html(html_body)

    OUTPUT_HTML.write_text(full_html, encoding="utf-8")
    print(f"Saved intermediate HTML: {OUTPUT_HTML}")

    print(f"Launching Headless Chrome: {CHROME_BIN}")
    cmd = [
        CHROME_BIN,
        "--headless",
        "--disable-gpu",
        "--no-pdf-header-footer",
        "--run-all-compositor-stages-before-draw",
        "--virtual-time-budget=6000",
        f"--print-to-pdf={OUTPUT_PDF}",
        str(OUTPUT_HTML),
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"Chrome error: {result.stderr}", file=sys.stderr)
        sys.exit(1)

    if not OUTPUT_PDF.exists():
        print(f"PDF was not created at {OUTPUT_PDF}", file=sys.stderr)
        sys.exit(1)

    pdf_size_kb = OUTPUT_PDF.stat().st_size / 1024
    print(f"✓ PDF successfully exported: {OUTPUT_PDF} ({pdf_size_kb:.1f} KB)")


if __name__ == "__main__":
    main()
