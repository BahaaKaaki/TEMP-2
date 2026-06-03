/**
 * Centralized safe logger that strips CRLF characters from all arguments
 * before writing to console, preventing log-injection (CWE-117) attacks.
 */

function sanitize(value) {
  if (typeof value === 'string') {
    return value.replace(/[\r\n]+/g, ' ');
  }
  return value;
}

export function safeLog(...args) {
  console.log(...args.map(sanitize));
}

export function safeError(...args) {
  console.error(...args.map(sanitize));
}

export function safeWarn(...args) {
  console.warn(...args.map(sanitize));
}
