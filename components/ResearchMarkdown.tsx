"use client";

import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";

type Node = { type: string; value?: string; url?: string; children?: Node[] };

// Convert citation markers into links before rendering. Raw HTML stays disabled.
function remarkCitations() {
  return (tree: Node) => {
    function visit(parent: Node) {
      if (!parent.children || ["link", "code", "inlineCode"].includes(parent.type)) return;
      parent.children = parent.children.flatMap((node) => {
        if (node.type !== "text") { visit(node); return [node]; }
        const parts: Node[] = [];
        const text = node.value ?? "";
        let cursor = 0;
        for (const match of text.matchAll(/\[(E\d+(?:,\s*E\d+)*)\]/g)) {
          parts.push({ type: "text", value: text.slice(cursor, match.index) });
          for (const id of match[1].match(/E\d+/g) ?? []) {
            parts.push({ type: "link", url: `#evidence-${id}`, children: [{ type: "text", value: id }] });
          }
          cursor = match.index! + match[0].length;
        }
        parts.push({ type: "text", value: text.slice(cursor) });
        return parts;
      });
    }
    visit(tree);
  };
}

export default function ResearchMarkdown({ text, known, onFocus }: {
  text: string; known: Set<string>; onFocus: (id: string) => void;
}) {
  return <div className="w-full min-w-0 space-y-4 break-words font-reading text-base leading-8 text-primary">
    <Markdown remarkPlugins={[remarkGfm, remarkCitations]} skipHtml components={{
      h1: ({ children }) => <h2 className="pt-3 font-ui text-xl font-semibold">{children}</h2>,
      h2: ({ children }) => <h3 className="pt-3 font-ui text-lg font-semibold">{children}</h3>,
      h3: ({ children }) => <h4 className="pt-2 font-ui text-base font-semibold">{children}</h4>,
      p: ({ children }) => <p className="leading-8">{children}</p>,
      strong: ({ children }) => <strong className="font-semibold text-primary">{children}</strong>,
      em: ({ children }) => <em className="italic text-secondary">{children}</em>,
      ul: ({ children }) => <ul className="list-disc space-y-2 pl-6">{children}</ul>,
      ol: ({ children }) => <ol className="list-decimal space-y-2 pl-6">{children}</ol>,
      blockquote: ({ children }) => <blockquote className="border-l-2 border-brass pl-4 italic text-secondary">{children}</blockquote>,
      table: ({ children }) => <div className="w-full overflow-x-auto rounded border border-hairline"><table className="w-full border-collapse text-left font-ui text-sm">{children}</table></div>,
      th: ({ children }) => <th className="border-b border-hairline bg-surface-raised px-4 py-3 font-semibold">{children}</th>,
      td: ({ children }) => <td className="border-b border-hairline-subtle px-4 py-3 align-top">{children}</td>,
      pre: ({ children }) => <pre className="overflow-x-auto rounded bg-surface-raised p-4 text-sm">{children}</pre>,
      img: () => null,
      a: ({ href, children }) => {
        if (href?.startsWith("#evidence-")) {
          const id = href.slice(10);
          return <button type="button" aria-label={`Show evidence ${id}`} disabled={!known.has(id)} onClick={() => onFocus(id)} className="mx-1 rounded border border-brass px-1 py-px align-baseline font-mono text-[10px] leading-5 text-brass hover:bg-brass hover:text-base disabled:opacity-40">{children}</button>;
        }
        return <span>{children}</span>; // Only backend-resolved sources are clickable.
      },
    }}>{text}</Markdown>
  </div>;
}
