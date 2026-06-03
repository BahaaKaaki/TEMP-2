import { defineComponent } from '@openuidev/react-lang';
import { z } from 'zod/v4';

const TextContent = defineComponent({
  name: 'Text',
  description: 'A single block of prose text. Use for paragraphs and short copy.',
  props: z.object({
    text: z.string().describe('Plain text content'),
    emphasis: z
      .enum(['normal', 'subtle', 'strong'])
      .optional()
      .describe('Visual weight; default normal'),
  }),
  component: ({ props }) => {
    const cls =
      props.emphasis === 'subtle'
        ? 'text-white/70'
        : props.emphasis === 'strong'
          ? 'font-semibold text-white'
          : 'text-white';
    return <p className={`${cls} text-sm leading-relaxed`}>{props.text}</p>;
  },
});

const Heading = defineComponent({
  name: 'Heading',
  description: 'A section heading. Pick a level 1-3 based on visual hierarchy.',
  props: z.object({
    text: z.string().describe('Heading text'),
    level: z.number().int().min(1).max(3).optional().describe('1 = largest, 3 = smallest'),
  }),
  component: ({ props }) => {
    const level = props.level ?? 2;
    const cls =
      level === 1
        ? 'text-xl font-bold text-white'
        : level === 2
          ? 'text-lg font-semibold text-white'
          : 'text-base font-medium text-white/90';
    const Tag = level === 1 ? 'h1' : level === 2 ? 'h2' : 'h3';
    return <Tag className={`${cls} mt-2 mb-1`}>{props.text}</Tag>;
  },
});

const Card = defineComponent({
  name: 'Card',
  description: 'A bordered container that groups related child components vertically.',
  props: z.object({
    title: z.string().optional().describe('Optional card title'),
    children: z.array(z.any()).describe('Child components rendered inside the card'),
  }),
  component: ({ props, renderNode }) => (
    <div className="rounded-lg border border-white/10 bg-white/5 p-3 my-2">
      {props.title ? (
        <div className="text-sm font-semibold text-white mb-2">{props.title}</div>
      ) : null}
      <div className="space-y-2">{renderNode(props.children)}</div>
    </div>
  ),
});

const Stack = defineComponent({
  name: 'Stack',
  description:
    'A flexible layout container. Default direction is vertical (column). Use direction "row" for horizontal layouts.',
  props: z.object({
    children: z.array(z.any()).describe('Child components'),
    direction: z.enum(['column', 'row']).optional().describe('Layout direction'),
    gap: z.enum(['s', 'm', 'l']).optional().describe('Spacing between items'),
  }),
  component: ({ props, renderNode }) => {
    const dir = props.direction === 'row' ? 'flex-row' : 'flex-col';
    const gap =
      props.gap === 's' ? 'gap-1' : props.gap === 'l' ? 'gap-4' : 'gap-2';
    return <div className={`flex ${dir} ${gap}`}>{renderNode(props.children)}</div>;
  },
});

const Bullets = defineComponent({
  name: 'Bullets',
  description: 'A simple bulleted list of strings.',
  props: z.object({
    items: z.array(z.string()).describe('List items'),
  }),
  component: ({ props }) => (
    <ul className="list-disc list-inside space-y-1 my-2 text-sm text-white">
      {props.items.map((item, i) => (
        <li key={i}>{item}</li>
      ))}
    </ul>
  ),
});

const Code = defineComponent({
  name: 'Code',
  description: 'A monospaced code block. Use the language prop for syntax hints.',
  props: z.object({
    code: z.string().describe('Code content'),
    language: z.string().optional().describe('Programming language hint, e.g. "python"'),
  }),
  component: ({ props }) => (
    <pre className="my-2 rounded bg-black/40 p-3 overflow-x-auto">
      <code className="text-xs font-mono text-white whitespace-pre-wrap break-all">
        {props.code}
      </code>
    </pre>
  ),
});

const Link = defineComponent({
  name: 'Link',
  description: 'An external hyperlink rendered inline.',
  props: z.object({
    label: z.string().describe('Display label'),
    href: z.string().describe('Absolute URL'),
  }),
  component: ({ props }) => (
    <a
      href={props.href}
      target="_blank"
      rel="noopener noreferrer"
      className="text-[#d93854] hover:underline font-medium"
    >
      {props.label}
    </a>
  ),
});

export { TextContent, Heading, Card, Stack, Bullets, Code, Link };
