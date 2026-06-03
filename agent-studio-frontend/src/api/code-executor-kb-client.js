/**
 * Code Executor Knowledge Base API client.
 *
 * The Code Editor side-panel and AI code generator call these endpoints to
 * discover which structured tables are available for the KBs configured on
 * the node.  Requests are authenticated with the user's JWT; RLS filters
 * out any KB the user isn't allowed to see.
 */

import { API_BASE_URL, authenticatedFetch } from './client.js';

/**
 * Fetch structured table metadata for one or more knowledge bases.
 *
 * @param {string[]} kbIds  List of KB UUIDs selected on the node.
 * @returns {Promise<{tables: Array<{
 *   kb_id: string,
 *   kb_name: string,
 *   schema_name: string,
 *   table: string,
 *   display_name: string,
 *   description: string,
 *   row_count: number,
 *   columns: Array<{name: string, type: string, description: string, nullable: boolean}>,
 * }>}>}
 */
export async function getKbTables(kbIds = []) {
  const ids = (Array.isArray(kbIds) ? kbIds : []).filter(Boolean);
  if (ids.length === 0) {
    return { tables: [] };
  }

  const params = new URLSearchParams({ kb_ids: ids.join(',') });
  const response = await authenticatedFetch(
    `${API_BASE_URL}/api/code-executor/kb-tables?${params.toString()}`
  );
  if (!response.ok) {
    const err = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(err.detail || `Failed to fetch KB tables (${response.status})`);
  }
  return response.json();
}
