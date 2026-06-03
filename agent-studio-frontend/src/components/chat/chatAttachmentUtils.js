/**
 * Assign session files to user messages by timestamp (files created at or before
 * a user message's timestamp belong to that message).
 */
export function buildMessageAttachmentMap(messages, files) {
  const map = new Map();
  const pending = new Set((files || []).map((f) => f.id));

  const userMsgs = (messages || [])
    .filter((m) => m.type === 'user' && m.message_id && m.timestamp)
    .sort((a, b) => new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime());

  if (userMsgs.length === 0) {
    return { map, pending };
  }

  const sortedFiles = [...(files || [])].sort(
    (a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime(),
  );

  let fileIdx = 0;
  for (const msg of userMsgs) {
    const msgMs = new Date(msg.timestamp).getTime();
    const batch = [];
    while (fileIdx < sortedFiles.length) {
      const fileMs = new Date(sortedFiles[fileIdx].created_at).getTime();
      if (fileMs > msgMs) break;
      batch.push(sortedFiles[fileIdx]);
      pending.delete(sortedFiles[fileIdx].id);
      fileIdx += 1;
    }
    if (batch.length) {
      map.set(msg.message_id, batch);
    }
  }

  return { map, pending };
}

export function getFileEmoji(fileType) {
  if (fileType === 'pdf') return '📄';
  if (fileType === 'txt') return '📝';
  if (fileType === 'xml') return '🔖';
  if (fileType === 'json') return '📊';
  if (fileType === 'csv') return '📈';
  if (fileType === 'md') return '📃';
  if (fileType === 'docx' || fileType === 'doc') return '📘';
  return '📎';
}
