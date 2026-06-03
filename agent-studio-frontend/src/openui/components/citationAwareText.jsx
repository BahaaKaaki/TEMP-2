import { defineComponent, useIsQueryLoading } from '@openuidev/react-lang';
import { MarkDownRenderer as BaseMarkDownRenderer } from '@openuidev/react-ui';
import { z } from 'zod/v4';

import OpenUICitationReference from './openUICitationReference';
import { useOpenUICitations } from '../citationContext';

function citationMap(citations) {
  return new Map(citations.map((citation) => [Number(citation.citation_number), citation]));
}

function renderTextWithCitationBadges(text, citationsByNumber, keyPrefix = 'openui-citation') {
  const parts = [];
  const regex = /\[(\d+)\]/g;
  let lastIndex = 0;
  let match;

  while ((match = regex.exec(text)) !== null) {
    const number = Number(match[1]);
    const citation = citationsByNumber.get(number);
    if (match.index > lastIndex) parts.push(text.slice(lastIndex, match.index));
    parts.push(citation ? (
      <OpenUICitationReference
        key={`${keyPrefix}-${number}-${match.index}`}
        citationNumber={number}
        citationData={citation}
      />
    ) : (
      <span
        key={`${keyPrefix}-${number}-${match.index}`}
        title={`Citation ${number}`}
        className="mx-0.5 inline-flex h-5 min-w-5 items-center justify-center rounded-md border border-cyan-300/70 bg-cyan-400/20 px-1 text-[11px] font-bold leading-none text-cyan-100 shadow-[0_0_0_1px_rgba(34,211,238,0.12)] align-baseline"
      >
        {number}
      </span>
    ));
    lastIndex = match.index + match[0].length;
  }

  if (lastIndex < text.length) parts.push(text.slice(lastIndex));
  return parts.length > 0 ? parts : text;
}

function processChildren(children, citationsByNumber, keyPrefix) {
  if (typeof children === 'string') {
    return renderTextWithCitationBadges(children, citationsByNumber, keyPrefix);
  }
  if (Array.isArray(children)) {
    return children.map((child, index) => (
      typeof child === 'string'
        ? renderTextWithCitationBadges(child, citationsByNumber, `${keyPrefix}-${index}`)
        : child
    ));
  }
  return children;
}

function CitationAwareMarkdown({ textMarkdown, variant }) {
  const citations = useOpenUICitations();
  const content = textMarkdown ?? '';

  if (citations.length > 0) {
    const citationsByNumber = citationMap(citations);
    const components = {
      p: ({ children, ...props }) => (
        <p {...props}>{processChildren(children, citationsByNumber, 'p')}</p>
      ),
      li: ({ children, ...props }) => (
        <li {...props}>{processChildren(children, citationsByNumber, 'li')}</li>
      ),
      strong: ({ children, ...props }) => (
        <strong {...props}>{processChildren(children, citationsByNumber, 'strong')}</strong>
      ),
      em: ({ children, ...props }) => (
        <em {...props}>{processChildren(children, citationsByNumber, 'em')}</em>
      ),
    };

    return <BaseMarkDownRenderer textMarkdown={content} variant={variant} options={{ components }} />;
  }

  return <BaseMarkDownRenderer textMarkdown={content} variant={variant} />;
}

const MarkDownRenderer = defineComponent({
  name: 'MarkDownRenderer',
  description: 'Renders markdown text with optional container variant',
  props: z.object({
    textMarkdown: z.string(),
    variant: z.enum(['clear', 'card', 'sunk']).optional(),
  }),
  component: ({ props }) => (
    <CitationAwareMarkdown textMarkdown={props.textMarkdown} variant={props.variant} />
  ),
});

const TextContent = defineComponent({
  name: 'TextContent',
  description: 'Text block. Supports markdown. Optional size: "small" | "default" | "large" | "small-heavy" | "large-heavy".',
  props: z.object({
    text: z.string(),
    size: z.enum(['small', 'default', 'large', 'small-heavy', 'large-heavy']).optional(),
  }),
  component: ({ props }) => {
    const size = props.size ?? 'default';
    const sizeVars = {
      small: '--openui-text-body-sm',
      default: '--openui-text-body-default',
      large: '--openui-text-body-lg',
      'small-heavy': '--openui-text-body-sm-heavy',
      'large-heavy': '--openui-text-body-lg-heavy',
    };
    const varName = sizeVars[size] || sizeVars.default;
    const style = size === 'default'
      ? undefined
      : {
        '--openui-text-body-default': `var(${varName})`,
        '--openui-text-body-default-letter-spacing': `var(${varName}-letter-spacing)`,
      };

    return (
      <div style={style}>
        <CitationAwareMarkdown textMarkdown={props.text == null ? '' : String(props.text)} />
      </div>
    );
  },
});

const Col = defineComponent({
  name: 'Col',
  description: 'Column definition — holds label + data array',
  props: z.object({
    label: z.string(),
    data: z.any(),
    type: z.enum(['string', 'number', 'action']).optional(),
  }),
  component: () => null,
});

const Table = defineComponent({
  name: 'Table',
  description: 'Data table — column-oriented. Each Col holds its own data array.',
  props: z.object({
    columns: z.array(Col.ref),
  }),
  component: ({ props, renderNode }) => {
    const isQueryLoading = useIsQueryLoading();
    const columns = props.columns ?? [];
    const colDefs = columns
      .filter((col) => col != null && col.props)
      .map((col) => ({
        label: col.props?.label ?? '',
        data: Array.isArray(col.props?.data) ? col.props.data : [col.props?.data],
      }));
    const rowCount = colDefs.length > 0 ? Math.max(...colDefs.map((col) => col.data.length), 0) : 0;

    if (isQueryLoading && rowCount === 0) {
      return <div className="rounded-xl border border-[#464646] p-4 text-sm text-[#b5b5b5]">Loading table…</div>;
    }
    if (!colDefs.length) return null;

    return (
      <div className="overflow-x-auto rounded-xl border border-[#464646]">
        <table className="w-full min-w-full border-collapse text-sm text-white">
          <thead className="bg-white/5 text-[#dadada]">
            <tr>
              {colDefs.map((col, index) => (
                <th key={index} className="border-b border-[#464646] px-3 py-2 text-left font-semibold">
                  {col.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {Array.from({ length: rowCount }, (_, rowIndex) => (
              <tr key={rowIndex} className="odd:bg-white/[0.02]">
                {colDefs.map((col, colIndex) => {
                  const cell = col.data[rowIndex];
                  return (
                    <td key={colIndex} className="border-b border-[#464646]/70 px-3 py-2 align-top last:border-b-0">
                      {typeof cell === 'object' && cell !== null ? (
                        renderNode(cell)
                      ) : (
                        <CitationAwareMarkdown textMarkdown={String(cell ?? '')} />
                      )}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  },
});

export { MarkDownRenderer, TextContent, Col, Table };
