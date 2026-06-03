/**
 * OpenUI component library for Agent Studio.
 *
 * Custom library for runtime deliverable rendering. Components are native
 * OpenUI React components registered with defineComponent; do not wrap legacy
 * Agent Studio chat widgets here. Regenerate system.txt after edits.
 *
 * Registers the components the LLM is allowed to emit. The
 * `createLibrary({ root })` call defines the entry point - the LLM
 * always wraps its response in `root = Stack([...])`.
 *
 * To add a new component:
 *   1. Define it with `defineComponent({...})`.
 *   2. Add it to the `components` array below.
 *   3. Run `npm run generate:openui` to refresh the system prompt files.
 */

import { createLibrary } from '@openuidev/react-lang';
import {
  openuiLibrary as baseOpenuiLibrary,
  openuiComponentGroups,
} from '@openuidev/react-ui/genui-lib';

import { promptOptions as agentStudioPromptOptions } from './prompt-options.mjs';

import {
  TextContent,
  Heading,
  Bullets,
  Code,
  Link,
} from './components/primitives';

import {
  MarkDownRenderer as CitationAwareMarkDownRenderer,
  TextContent as CitationAwareTextContent,
  Col as CitationAwareCol,
  Table as CitationAwareTable,
} from './components/citationAwareText';

import {
  TreeView,
  Slide,
  QueryTrace,
} from './components/widgets';

const baseComponents = Array.isArray(baseOpenuiLibrary.components)
  ? baseOpenuiLibrary.components
  : Object.values(baseOpenuiLibrary.components ?? {});

const citationAwareComponentNames = new Set(['MarkDownRenderer', 'TextContent', 'Col', 'Table']);
const baseComponentsWithoutCitationAwareOverrides = baseComponents.filter(
  (component) => !citationAwareComponentNames.has(component.name),
);

export const agentStudioComponents = [
  Heading,
  TextContent,
  Bullets,
  Code,
  Link,
  Slide,
  TreeView,
  QueryTrace,
];

export const components = [
  ...baseComponentsWithoutCitationAwareOverrides,
  CitationAwareMarkDownRenderer,
  CitationAwareTextContent,
  CitationAwareCol,
  CitationAwareTable,
  ...agentStudioComponents,
];

export const componentGroups = [
  ...openuiComponentGroups,
  {
    name: 'Agent Studio Text',
    components: ['Heading', 'Text', 'Bullets', 'Code', 'Link'],
    notes: [
      '- Prefer Bullets over multiple Text components for lists.',
      '- Use Code for any code snippet, command, or structured payload.',
    ],
  },
  {
    name: 'Agent Studio Data',
    components: ['QueryTrace'],
    notes: [
      '- Use built-in Table and Col for tabular data.',
      '- Use built-in BarChart, LineChart, AreaChart, PieChart, RadarChart, HorizontalBarChart, or ScatterChart for numeric data.',
      '- Use QueryTrace only for structured query/tool provenance that should be visible to the user.',
    ],
  },
  {
    name: 'Agent Studio Domain',
    components: ['Slide', 'TreeView'],
    notes: [
      '- Use built-in Card, CardHeader, TextContent, Callout, Steps, Accordion, Tabs, TagBlock, Table, and chart components for generic business content.',
      '- Use Slide for presentation-style responses (title plus bullets).',
      '- Use TreeView for any parent-child hierarchy, especially org_tree objects with children arrays.',
    ],
  },
];

export const promptOptions = {
  ...agentStudioPromptOptions,
};

export const openuiLibrary = createLibrary({
  root: 'Stack',
  components,
  componentGroups,
});

export default openuiLibrary;
