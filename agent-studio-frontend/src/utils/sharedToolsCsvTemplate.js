/**
 * CSV template for bulk shared external tools upload.
 * Matches backend parser in shared_tool_service.parse_and_import_csv
 */

export const SHARED_TOOLS_CSV_HEADER =
  'tool_name,description,url,is_public,ad_group_csv,email_csv';

export const SHARED_TOOLS_CSV_EXAMPLE_ROW = [
  'Example Analytics Tool',
  'A short description of what this tool does',
  'https://example.com/app',
  'false',
  '"Finance Team, Marketing"',
  '"colleague@company.com"',
].join(',');

export function downloadSharedToolsCsvTemplate(filename = 'shared_tools_template.csv') {
  // Example row is optional — delete it and add your tools before upload.
  const lines = [SHARED_TOOLS_CSV_HEADER, SHARED_TOOLS_CSV_EXAMPLE_ROW];
  const blob = new Blob([lines.join('\n') + '\n'], { type: 'text/csv;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}
