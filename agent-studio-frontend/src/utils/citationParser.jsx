import CitationReference from '../components/chat/CitationReference';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { safeLog } from './safeLogger';

/**
 * Parse message text with BOTH markdown AND citation markers.
 * 
 * This function renders markdown (bold, lists, etc.) while also
 * replacing [N] citation markers with interactive CitationReference components.
 * 
 * @param {string} text - Message text with markdown and citation markers
 * @param {Array} citations - Array of citation data objects
 * @param {Object} markdownComponents - Custom ReactMarkdown components for styling
 * @returns {JSX.Element} Rendered markdown with citation components
 */
export function parseCitations(text, citations = [], markdownComponents = {}) {
  safeLog('🔍 parseCitations called');
  safeLog('   Text:', text?.substring(0, 100));
  safeLog('   Citations count:', citations?.length);
  
  if (!text) {
    safeLog('   ❌ No text, returning original');
    return text;
  }

  if (!citations || citations.length === 0) {
    safeLog('   ⚠️ No citations, but still processing markdown');
    return <ReactMarkdown remarkPlugins={[remarkGfm]} components={markdownComponents}>{text}</ReactMarkdown>;
  }

  // Create citation lookup map
  const citationMap = {};
  citations.forEach(citation => {
    citationMap[citation.citation_number] = citation;
  });
  safeLog('   ✅ Citation map created:', Object.keys(citationMap));

  // Create a custom text renderer that replaces [N] with citation components
  const customMarkdownComponents = {
    ...markdownComponents,
    // Override text node rendering to inject citation components
    p: ({ node, children, ...props }) => {
      const processedChildren = processTextWithCitations(children, citationMap);
      const ParagraphComponent = markdownComponents.p || 'p';
      return <ParagraphComponent {...props}>{processedChildren}</ParagraphComponent>;
    },
    li: ({ node, children, ...props }) => {
      const processedChildren = processTextWithCitations(children, citationMap);
      const ListItemComponent = markdownComponents.li || 'li';
      return <ListItemComponent {...props}>{processedChildren}</ListItemComponent>;
    },
    strong: ({ node, children, ...props }) => {
      const processedChildren = processTextWithCitations(children, citationMap);
      const StrongComponent = markdownComponents.strong || 'strong';
      return <StrongComponent {...props}>{processedChildren}</StrongComponent>;
    },
    em: ({ node, children, ...props }) => {
      const processedChildren = processTextWithCitations(children, citationMap);
      const EmComponent = markdownComponents.em || 'em';
      return <EmComponent {...props}>{processedChildren}</EmComponent>;
    },
    td: ({ node, children, ...props }) => {
      const processedChildren = processTextWithCitations(children, citationMap);
      const TdComponent = markdownComponents.td || 'td';
      return <TdComponent {...props}>{processedChildren}</TdComponent>;
    },
    th: ({ node, children, ...props }) => {
      const processedChildren = processTextWithCitations(children, citationMap);
      const ThComponent = markdownComponents.th || 'th';
      return <ThComponent {...props}>{processedChildren}</ThComponent>;
    },
  };

  safeLog('   ✅ Rendering markdown with citation support');
  return <ReactMarkdown remarkPlugins={[remarkGfm]} components={customMarkdownComponents}>{text}</ReactMarkdown>;
}

/**
 * Process children nodes and replace citation markers with components
 */
function processTextWithCitations(children, citationMap) {
  if (!children) return children;

  const citationRegex = /\[(\d+)\]/g;
  
  return processNodeChildren(children, citationRegex, citationMap);
}

/**
 * Recursively process React children to find and replace citation markers
 */
function processNodeChildren(children, citationRegex, citationMap) {
  if (typeof children === 'string') {
    // Process string directly
    return replaceCitationsInString(children, citationRegex, citationMap);
  }

  if (Array.isArray(children)) {
    // Process each child in array
    return children.map((child, index) => {
      if (typeof child === 'string') {
        return replaceCitationsInString(child, citationRegex, citationMap, index);
      }
      return child;
    });
  }

  // Return as-is if not string or array
  return children;
}

/**
 * Replace [N] citation markers in a string with CitationReference components
 */
function replaceCitationsInString(text, citationRegex, citationMap, baseKey = 0) {
  const parts = [];
  let lastIndex = 0;
  let match;
  let key = baseKey * 1000; // Ensure unique keys

  // Reset regex index
  citationRegex.lastIndex = 0;

  // Find all [N] patterns
  while ((match = citationRegex.exec(text)) !== null) {
    const fullMatch = match[0];  // "[1]"
    const citationNumber = parseInt(match[1], 10);  // 1
    const matchIndex = match.index;

    // Add text before this citation
    if (matchIndex > lastIndex) {
      const textBefore = text.substring(lastIndex, matchIndex);
      parts.push(textBefore);
    }

    // Add citation component
    const citationData = citationMap[citationNumber];
    parts.push(
      <CitationReference
        key={`citation-${citationNumber}-${key++}`}
        citationNumber={citationNumber}
        citationData={citationData}
      />
    );

    lastIndex = matchIndex + fullMatch.length;
  }

  // Add remaining text after last citation
  if (lastIndex < text.length) {
    const remainingText = text.substring(lastIndex);
    parts.push(remainingText);
  }

  // If no citations were found, return original text
  if (parts.length === 0) {
    return text;
  }

  return parts;
}

/**
 * Check if a message contains citation markers
 */
export function hasCitations(text) {
  if (!text) return false;
  return /\[\d+\]/.test(text);
}

/**
 * Extract all citation numbers from text
 */
export function extractCitationNumbers(text) {
  if (!text) return [];
  
  const numbers = [];
  const regex = /\[(\d+)\]/g;
  let match;
  
  while ((match = regex.exec(text)) !== null) {
    numbers.push(parseInt(match[1], 10));
  }
  
  return numbers;
}

