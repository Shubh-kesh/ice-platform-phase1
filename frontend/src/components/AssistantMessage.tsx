import { createContext, useContext, type CSSProperties, type ReactNode } from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";

// ICE Copilot — safe, theme-consistent Markdown renderer (UX PATCH 1).
//
// Security model:
// - react-markdown does NOT render raw HTML by default (no rehype-raw is
//   installed), so <script>/HTML from the model or web results is escaped to
//   plain text — never executed.
// - URLs are re-checked in the Link renderer below (allowlisted schemes only);
//   unsafe schemes render as plain text, never as clickable links.
// - Everything is rendered as React elements, never dangerouslySetInnerHTML.

const PreContext = createContext(false);

const ALLOWED_URL_SCHEMES = new Set(["http:", "https:", "mailto:", "tel:"]);

function isSafeUrl(href: string): boolean {
  try {
    const url = new URL(href, "https://ice.local");
    if (url.protocol === "http:" || url.protocol === "https:") return true;
    return ALLOWED_URL_SCHEMES.has(url.protocol);
  } catch {
    return false;
  }
}

function cellAlign(style: CSSProperties | undefined) {
  if (style?.textAlign === "right") return "text-right font-mono tabular text-paper";
  if (style?.textAlign === "center") return "text-center";
  return "text-left";
}

function CodeBlock(props: { className?: string; children?: ReactNode }) {
  const { className, children } = props;
  return <code className={`whitespace-pre ${className ?? ""}`}>{children}</code>;
}

function InlineCode(props: { children?: ReactNode }) {
  const { children } = props;
  return (
    <code className="rounded bg-ink-raised px-1.5 py-0.5 font-mono text-[0.8125rem] text-blueprint-200">
      {children}
    </code>
  );
}

function Code(props: { className?: string; children?: ReactNode }) {
  const inPre = useContext(PreContext);
  if (inPre) return <CodeBlock {...props} />;
  return <InlineCode {...props} />;
}

function Pre(props: { children?: ReactNode }) {
  return (
    <PreContext.Provider value={true}>
      <pre className="my-3 overflow-x-auto rounded-md border border-ink-border bg-ink p-3 font-mono text-xs leading-relaxed text-paper">
        {props.children}
      </pre>
    </PreContext.Provider>
  );
}

function Link(props: { href?: string; children?: ReactNode }) {
  const { href, children } = props;
  if (!href || !isSafeUrl(href)) {
    return <>{children}</>;
  }
  return (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      className="text-blueprint-400 underline underline-offset-2 hover:text-blueprint-200"
    >
      {children}
    </a>
  );
}

function Image(props: { src?: string; alt?: string; title?: string }) {
  const { src, alt, title } = props;
  if (!src || !isSafeUrl(src)) {
    return null;
  }
  return (
    <img
      src={src}
      alt={alt ?? ""}
      title={title}
      className="my-3 max-w-full rounded-md border border-ink-border"
    />
  );
}

function H1(props: { children?: ReactNode }) {
  return <h1 className="mb-2 mt-5 text-lg font-semibold text-paper">{props.children}</h1>;
}

function H2(props: { children?: ReactNode }) {
  return <h2 className="mb-2 mt-4 text-base font-semibold text-paper">{props.children}</h2>;
}

function H3(props: { children?: ReactNode }) {
  return <h3 className="mb-2 mt-3 text-sm font-semibold text-paper">{props.children}</h3>;
}

function H4(props: { children?: ReactNode }) {
  return <h4 className="mb-2 mt-3 text-sm font-medium text-paper">{props.children}</h4>;
}

function H5(props: { children?: ReactNode }) {
  return <h5 className="mb-2 mt-3 text-sm font-medium text-paper-muted">{props.children}</h5>;
}

function H6(props: { children?: ReactNode }) {
  return <h6 className="mb-2 mt-3 text-sm font-medium text-paper-muted">{props.children}</h6>;
}

function P(props: { children?: ReactNode }) {
  return <p className="my-2 text-sm leading-relaxed text-paper">{props.children}</p>;
}

function Ul(props: { children?: ReactNode }) {
  return <ul className="my-2 list-disc space-y-1 pl-5 text-sm text-paper">{props.children}</ul>;
}

function Ol(props: { children?: ReactNode }) {
  return <ol className="my-2 list-decimal space-y-1 pl-5 text-sm text-paper">{props.children}</ol>;
}

function Li(props: { children?: ReactNode }) {
  return <li className="leading-relaxed">{props.children}</li>;
}

function Strong(props: { children?: ReactNode }) {
  return <strong className="font-semibold text-paper">{props.children}</strong>;
}

function Em(props: { children?: ReactNode }) {
  return <em className="italic text-paper">{props.children}</em>;
}

function Blockquote(props: { children?: ReactNode }) {
  return (
    <blockquote className="my-3 border-l-2 border-blueprint-600/50 pl-3 text-sm italic text-paper-muted">
      {props.children}
    </blockquote>
  );
}

function Hr() {
  return <hr className="my-4 border-ink-border" />;
}

function Table(props: { children?: ReactNode }) {
  return (
    <div className="my-3 overflow-x-auto rounded-md border border-ink-border">
      <table className="min-w-full border-collapse text-sm">{props.children}</table>
    </div>
  );
}

function Thead(props: { children?: ReactNode }) {
  return <thead className="bg-ink-raised">{props.children}</thead>;
}

function Th(props: { style?: CSSProperties; children?: ReactNode }) {
  return (
    <th
      className={`whitespace-nowrap border-b border-ink-border px-3 py-2 text-[11px] font-medium uppercase tracking-wide text-paper-muted ${cellAlign(props.style)}`}
    >
      {props.children}
    </th>
  );
}

function Td(props: { style?: CSSProperties; children?: ReactNode }) {
  return (
    <td className={`border-b border-ink-border px-3 py-2 align-top text-paper-muted ${cellAlign(props.style)}`}>
      {props.children}
    </td>
  );
}

function Tr(props: { children?: ReactNode }) {
  return <tr className="odd:bg-ink/30 hover:bg-ink-raised/50">{props.children}</tr>;
}

const components: Components = {
  pre: Pre,
  code: Code,
  a: Link,
  img: Image,
  h1: H1,
  h2: H2,
  h3: H3,
  h4: H4,
  h5: H5,
  h6: H6,
  p: P,
  ul: Ul,
  ol: Ol,
  li: Li,
  strong: Strong,
  em: Em,
  blockquote: Blockquote,
  hr: Hr,
  table: Table,
  thead: Thead,
  th: Th,
  td: Td,
  tr: Tr,
};

export default function AssistantMessage({ text }: { text: string }) {
  return (
    <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
      {text}
    </ReactMarkdown>
  );
}