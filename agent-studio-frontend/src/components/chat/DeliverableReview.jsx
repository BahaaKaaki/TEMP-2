/**
 * DeliverableReview Component
 *
 * Displays a deliverable for HITL review and full-screen expansion. Agent
 * deliverables render through the deterministic OpenUI tab bar
 * (DeliverableOpenUIView); code-executor outputs use CodeExecutorOutput.
 */

import { useState, useMemo } from 'react';
import Button from '../ui/Button';
import { respondToWidget, createDeliverableEdwinHandoff, getOpenUITranslationPrompt } from '@/api/client';
import { safeError } from '../../utils/safeLogger';
import { fillTemplate } from '@/api/template-client';
import CodeExecutorOutput from './CodeExecutorOutput';
import DeliverableOpenUIView from '@/openui/DeliverableOpenUIView';
import { getDeliverableOpenUISections } from '@/openui/resolveOpenUILang';
import { downloadInteractiveDeliverableHtml } from '@/openui/exportOpenUIHtml';
import { CHAT_SECONDARY_BTN } from './chatButtonStyles';
import { renderTextWithCitations } from '@/openui/citationText';

const DeliverableReview = ({
  deliverable,
  executionId,
  onApprove,
  onReject,
  onWidgetRespond: onWidgetRespondProp,
  isProcessing,
  templateId = null,
  initialSectionIndex = 0,
}) => {
  const [inlineEditedData, setInlineEditedData] = useState(null);
  const [rejectionNotes, setRejectionNotes] = useState('');
  const [showRejectModal, setShowRejectModal] = useState(false);

  const [isExporting, setIsExporting] = useState(false);
  const [isExportingTemplate, setIsExportingTemplate] = useState(false);
  const [isHandingOff, setIsHandingOff] = useState(false);
  const [exportError, setExportError] = useState(null);

  // HTML export ships the interactive standalone viewer (see exportOpenUIHtml).
  const [htmlExportPending, setHtmlExportPending] = useState(false);

  // Temporary debug panel: generated JSON, OpenUI Lang, and translation prompt.
  const [showDebug, setShowDebug] = useState(false);
  const [promptData, setPromptData] = useState(null);
  const [promptLoading, setPromptLoading] = useState(false);
  const [promptError, setPromptError] = useState(null);

  const deliverableExportInfo = useMemo(() => ({
    agentLabel: deliverable.agentLabel || deliverable.agentType || 'Deliverable',
    createdAt: deliverable.createdAt || deliverable.reviewedAt,
  }), [deliverable]);

  const openUiExportSections = useMemo(
    () => getDeliverableOpenUISections(deliverable),
    [deliverable],
  );

  const debugJson = useMemo(() => {
    try {
      return JSON.stringify(deliverable.deliverable ?? deliverable, null, 2);
    } catch {
      return String(deliverable.deliverable ?? '');
    }
  }, [deliverable]);

  const openDebug = async () => {
    setShowDebug(true);
    if (promptData || promptLoading) return;
    setPromptLoading(true);
    setPromptError(null);
    try {
      setPromptData(await getOpenUITranslationPrompt());
    } catch (err) {
      safeError('Load OpenUI prompt failed:', err);
      setPromptError(err.message || 'Could not load the translation prompt.');
    } finally {
      setPromptLoading(false);
    }
  };

  const copyText = (text) => {
    try {
      navigator.clipboard?.writeText(text ?? '');
    } catch (err) {
      safeError('Copy failed:', err);
    }
  };

  const handleExportPDF = async () => {
    setIsExporting(true);
    try {
      const { downloadDeliverablePDF } = await import('@/utils/pdfGenerator');
      downloadDeliverablePDF(deliverable.deliverable, deliverableExportInfo);
    } catch (err) {
      safeError('PDF export failed:', err);
    } finally {
      setIsExporting(false);
    }
  };

  const handleExportDOCX = async () => {
    setIsExporting(true);
    try {
      const { downloadDeliverableDOCX } = await import('@/utils/docxGenerator');
      await downloadDeliverableDOCX(deliverable.deliverable, deliverableExportInfo);
    } catch (err) {
      safeError('DOCX export failed:', err);
    } finally {
      setIsExporting(false);
    }
  };

  // Ships the interactive standalone OpenUI viewer with this deliverable's
  // sections embedded, so the downloaded file renders live (tabs, tooltips,
  // sub-toggles, org-chart pan/zoom), identical to the in-app view.
  const handleExportHTML = async () => {
    setExportError(null);
    setHtmlExportPending(true);
    try {
      await downloadInteractiveDeliverableHtml({
        title: deliverableExportInfo.agentLabel || 'Deliverable',
        summary: deliverable.deliverable?.summary || deliverable.summary || '',
        sections: openUiExportSections,
      });
    } catch (err) {
      safeError('OpenUI HTML export failed:', err);
      setExportError(err.message || 'HTML export failed.');
    } finally {
      setHtmlExportPending(false);
    }
  };

  const handleEdwinHandoff = async () => {
    setExportError(null);
    setIsHandingOff(true);
    try {
      const { url } = await createDeliverableEdwinHandoff(deliverable.id);
      if (url) {
        window.open(url, '_blank', 'noopener,noreferrer');
      } else {
        setExportError('Edwin did not return a presentation link.');
      }
    } catch (err) {
      safeError('Edwin handoff failed:', err);
      setExportError(err.message || 'Could not reach Edwin.');
    } finally {
      setIsHandingOff(false);
    }
  };

  const handleExportWithTemplate = async () => {
    if (!templateId || !deliverable?.deliverable) return;
    setIsExportingTemplate(true);
    try {
      const blob = await fillTemplate(templateId, deliverable.deliverable);
      const blobUrl = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = blobUrl;
      const label = (deliverable.agentLabel || 'Deliverable').replace(/[^\w\s]/g, '_');
      a.download = `${label.replace(/\s+/g, '_')}.pptx`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(blobUrl);
    } catch (err) {
      safeError('Template export failed:', err);
    } finally {
      setIsExportingTemplate(false);
    }
  };

  const handleApprove = () => {
    if (inlineEditedData) {
      onApprove(deliverable.id, inlineEditedData);
    } else {
      onApprove(deliverable.id, null);
    }
    setInlineEditedData(null);
  };

  const handleReject = () => {
    setShowRejectModal(true);
  };

  const confirmReject = () => {
    onReject(deliverable.id, rejectionNotes);
    setShowRejectModal(false);
    setRejectionNotes('');
  };

  const cancelReject = () => {
    setShowRejectModal(false);
    setRejectionNotes('');
  };

  return (
    <div className="h-full flex flex-col">
      {/* Deliverable Content */}
      <div className="flex-1 overflow-y-auto mb-4">
        <div className="space-y-4">
          {/* Controls row */}
          <div>
            {(() => {
              const busy = isExporting || isExportingTemplate || isHandingOff || htmlExportPending;
              const btn = `text-xs px-3 py-1.5 rounded-[10px] flex items-center gap-1.5 bg-[#262626] border border-[#464646] text-[#e5e5e5] hover:bg-[#2e2024] hover:border-[rgba(217,56,84,0.5)] hover:text-white transition-colors disabled:opacity-40 disabled:cursor-not-allowed`;
              const spinner = (
                <svg className="animate-spin w-3.5 h-3.5" fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                </svg>
              );
              return (
                <div className="flex items-center justify-end gap-2 mb-2 flex-wrap">
                      <button onClick={handleExportPDF} disabled={busy} className={btn}>
                        <svg className="w-4 h-4 text-[#d93854]" fill="currentColor" viewBox="0 0 24 24">
                          <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8l-6-6zM6 20V4h7v5h5v11H6z" />
                          <text x="7" y="17" fontSize="6" fontWeight="bold" fill="currentColor">PDF</text>
                        </svg>
                        Export PDF
                      </button>
                      <button onClick={handleExportDOCX} disabled={busy} className={btn}>
                        <svg className="w-4 h-4 text-blue-400" fill="currentColor" viewBox="0 0 24 24">
                          <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8l-6-6zM6 20V4h7v5h5v11H6z" />
                          <text x="6" y="17" fontSize="5.5" fontWeight="bold" fill="currentColor">DOC</text>
                        </svg>
                        Export Word
                      </button>
                      <button onClick={handleExportHTML} disabled={busy} className={btn}>
                        {htmlExportPending ? spinner : (
                          <svg className="w-4 h-4 text-emerald-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 20l4-16m4 4l4 4-4 4M6 16l-4-4 4-4" />
                          </svg>
                        )}
                        {htmlExportPending ? 'Building...' : 'Export HTML'}
                      </button>
                      <button onClick={handleEdwinHandoff} disabled={busy} className={btn}>
                        {isHandingOff ? spinner : (
                          <svg className="w-4 h-4 text-violet-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 5a1 1 0 011-1h14a1 1 0 011 1v9a1 1 0 01-1 1h-5l3 4m-7-4l-3 4m1-4H5a1 1 0 01-1-1V5z" />
                          </svg>
                        )}
                        {isHandingOff ? 'Opening Edwin...' : 'Create Presentation in Edwin'}
                      </button>
                      {templateId && (
                        <button onClick={handleExportWithTemplate} disabled={busy} className={btn}>
                          {isExportingTemplate ? spinner : (
                            <svg className="w-4 h-4 text-orange-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                            </svg>
                          )}
                          {isExportingTemplate ? 'Exporting...' : 'Fill PowerPoint Template'}
                        </button>
                      )}
                      {/* TEMP: debug panel (JSON / OpenUI Lang / prompt). Remove when done. */}
                      <button onClick={openDebug} className={btn} title="Inspect generated JSON, OpenUI Lang, and the translation prompt">
                        <svg className="w-4 h-4 text-amber-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
                        </svg>
                        Debug
                      </button>
                </div>
              );
            })()}

            {exportError && (
              <div className="mb-2 flex items-center justify-end gap-2 text-xs text-[#f1a3b0]">
                <span>{exportError}</span>
                <button
                  onClick={() => setExportError(null)}
                  className="text-[#b5b5b5] hover:text-white"
                  aria-label="Dismiss"
                >
                  <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" /></svg>
                </button>
              </div>
            )}

            {/* Typed output rendering for code-executor deliverables */}
            {deliverable.outputType && deliverable.outputType !== 'sections' && (
              <CodeExecutorOutput
                // Force a full remount whenever a genuinely new ask
                // arrives (pause_index changes) or the deliverable
                // swaps out.  This guarantees the AskWidget always
                // renders fresh for chained output.ask() sequences,
                // even if internal useEffect deps somehow miss an
                // update during Fast Refresh.
                key={`${deliverable.id}:${deliverable.deliverable?.pause_index ?? 0}:${deliverable.updatedAt || ''}`}
                deliverable={deliverable}
                executionId={executionId}
                onDataChange={(updatedData) => setInlineEditedData(updatedData)}
                onWidgetRespond={async (response) => {
                  try {
                    // The POST /respond response embeds a post-resume
                    // snapshot (updated_deliverables + execution_status)
                    // — forward it to the parent so ChatView can
                    // refresh the pane synchronously without a
                    // follow-up GET, which is what chained
                    // output.ask() sequences need to avoid "blank
                    // until refresh" behavior.
                    const respondResult = await respondToWidget(deliverable.id, response);
                    if (onWidgetRespondProp) {
                      await onWidgetRespondProp(respondResult);
                    }
                  } catch (err) {
                    safeError('Widget response failed:', err);
                  }
                }}
              />
            )}

            {/* Agent deliverables: deterministic OpenUI tab bar (same component
                used inline), so the expanded view is identical, just larger. */}
            {(!deliverable.outputType || deliverable.outputType === 'sections') && (
              <div className="flex flex-col flex-1 min-h-0">
                {(deliverable.deliverable?.summary || deliverable.summary) && (
                  <p className="mb-4 text-sm text-white/80 leading-relaxed">
                    {renderTextWithCitations(
                      deliverable.deliverable?.summary || deliverable.summary,
                      deliverable.deliverable?._citations,
                    )}
                  </p>
                )}
                <DeliverableOpenUIView
                  deliverable={deliverable}
                  className="flex-1 min-h-[50vh]"
                  initialSectionIndex={initialSectionIndex}
                />
              </div>
            )}
          </div>

          {/* Review Notes (if rejected) */}
          {deliverable.status === 'rejected' && deliverable.reviewNotes && (
            <div className="p-3 bg-red-50 border border-red-200 rounded-lg">
              <div className="flex items-center gap-2 text-sm text-red-800 font-medium mb-2">
                <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 20 20">
                  <path fillRule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7 4a1 1 0 11-2 0 1 1 0 012 0zm-1-9a1 1 0 00-1 1v4a1 1 0 102 0V6a1 1 0 00-1-1z" clipRule="evenodd" />
                </svg>
                Rejection Notes
              </div>
              <p className="text-sm text-red-700">{deliverable.reviewNotes}</p>
            </div>
          )}

          {/* Timestamp */}
          {deliverable.reviewedAt && (
            <div className="text-xs text-muted-foreground">
              Reviewed on {new Date(deliverable.reviewedAt).toLocaleString()}
            </div>
          )}
        </div>
      </div>

      {/* Completed indicator for auto-approved code executor outputs */}
      {deliverable.agentType === 'code-executor' && deliverable.status === 'approved' && deliverable.outputType !== 'ask' && (
        <div className="flex items-center gap-2 pt-3 border-t border-border text-xs text-emerald-600">
          <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
          </svg>
          <span>Output processed — workflow continuing</span>
        </div>
      )}

      {/* Action Buttons — code-executor deliverables never show
          approve/reject; their widgets handle interaction directly
          and non-interactive outputs are auto-approved. */}
      {deliverable.status === 'pending' && deliverable.agentType !== 'code-executor' && (
        <div className="sticky bottom-0 z-20 mt-4 rounded-2xl border border-[#d93854]/35 bg-[#171717]/95 p-3 shadow-[0_-10px_30px_rgba(0,0,0,0.28)] backdrop-blur">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div className="min-w-0 text-xs text-[#b5b5b5]">
              Approve to continue, or request changes for the agent to revise.
            </div>
            <div className="flex flex-wrap items-center justify-end gap-2">
              <button
                onClick={handleReject}
                disabled={isProcessing}
                className={`flex h-10 items-center gap-1.5 rounded-[10px] px-4 text-xs ${CHAT_SECONDARY_BTN}`}
              >
                <svg className="w-3.5 h-3.5 text-[#ff8ba0]" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" /></svg>
                Request changes
              </button>
              <button
                onClick={handleApprove}
                disabled={isProcessing}
                className="flex h-10 items-center gap-1.5 rounded-[10px] border border-emerald-400/45 bg-emerald-500/15 px-4 text-xs font-bold text-emerald-100 shadow-[inset_0_1px_0_rgba(16,185,129,0.18)] transition-colors hover:border-emerald-300/70 hover:bg-emerald-500/25 disabled:cursor-not-allowed disabled:opacity-40"
              >
                <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" /></svg>
                {isProcessing ? 'Approving...' : inlineEditedData ? 'Approve with edits' : 'Approve'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* TEMP debug overlay: generated JSON | OpenUI Lang | translation prompt.
          Read-only inspection aid; remove this block when debugging is done. */}
      {showDebug && (
        <div className="fixed inset-0 z-[60] flex flex-col bg-[#0d0d0d]/95 backdrop-blur-sm">
          <div className="flex items-center justify-between px-5 py-3 border-b border-[#2a2a2a] flex-shrink-0">
            <div className="flex items-center gap-2 text-sm font-semibold text-amber-300">
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
              </svg>
              Deliverable Debug — JSON / OpenUI Lang / Prompt
            </div>
            <button onClick={() => setShowDebug(false)} className="text-[#b5b5b5] hover:text-white" aria-label="Close">
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" /></svg>
            </button>
          </div>

          {/* Top: generated JSON and OpenUI Lang, side by side */}
          <div className="flex-1 min-h-0 grid grid-cols-1 lg:grid-cols-2 gap-px bg-[#2a2a2a] overflow-hidden">
            <div className="flex flex-col min-h-0 bg-[#0d0d0d]">
              <div className="flex items-center justify-between px-4 py-2 border-b border-[#2a2a2a] flex-shrink-0">
                <span className="text-xs font-semibold text-[#e5e5e5]">Generated JSON</span>
                <button onClick={() => copyText(debugJson)} className="text-[11px] text-[#b5b5b5] hover:text-white">Copy</button>
              </div>
              <pre className="flex-1 min-h-0 overflow-auto px-4 py-3 text-[11px] leading-relaxed text-[#cdd6e0] font-mono whitespace-pre">{debugJson}</pre>
            </div>
            <div className="flex flex-col min-h-0 bg-[#0d0d0d]">
              <div className="flex items-center justify-between px-4 py-2 border-b border-[#2a2a2a] flex-shrink-0">
                <span className="text-xs font-semibold text-[#e5e5e5]">Generated OpenUI Lang</span>
                <button
                  onClick={() => copyText(openUiExportSections.map((s) => s.lang).join('\n\n'))}
                  className="text-[11px] text-[#b5b5b5] hover:text-white"
                >
                  Copy
                </button>
              </div>
              <div className="flex-1 min-h-0 overflow-auto px-4 py-3 space-y-4">
                {openUiExportSections.length === 0 ? (
                  <p className="text-xs text-[#8a8a8a] italic">OpenUI Lang not generated yet.</p>
                ) : (
                  openUiExportSections.map((s, i) => (
                    <div key={i}>
                      <div className="text-[11px] font-semibold text-amber-300/80 mb-1">{`[${i}] ${s.title}`}</div>
                      <pre className="text-[11px] leading-relaxed text-[#cdd6e0] font-mono whitespace-pre-wrap break-words">{s.lang || '(not generated)'}</pre>
                    </div>
                  ))
                )}
              </div>
            </div>
          </div>

          {/* Bottom: the prompt used to convert JSON -> OpenUI Lang */}
          <div className="h-[32%] min-h-0 flex flex-col border-t border-[#2a2a2a] bg-[#0d0d0d] flex-shrink-0">
            <div className="flex items-center justify-between px-4 py-2 border-b border-[#2a2a2a] flex-shrink-0">
              <span className="text-xs font-semibold text-[#e5e5e5]">
                Translation Prompt (system + task)
                {promptData?.model && <span className="ml-2 text-[#8a8a8a] font-normal">model: {promptData.model}</span>}
              </span>
              {promptData?.combined && (
                <button onClick={() => copyText(promptData.combined)} className="text-[11px] text-[#b5b5b5] hover:text-white">Copy</button>
              )}
            </div>
            <div className="flex-1 min-h-0 overflow-auto px-4 py-3">
              {promptLoading ? (
                <p className="text-xs text-[#8a8a8a]">Loading prompt...</p>
              ) : promptError ? (
                <p className="text-xs text-[#f1a3b0]">{promptError}</p>
              ) : (
                <pre className="text-[11px] leading-relaxed text-[#cdd6e0] font-mono whitespace-pre-wrap break-words">
                  {promptData?.combined || ''}
                  {promptData?.human_prefix ? `\n\n--- per-section human message ---\n${promptData.human_prefix}<section JSON shown on the left>` : ''}
                </pre>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Rejection Modal */}
      {showRejectModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
          <div className="max-w-md w-full mx-4 rounded-2xl border border-[#464646] bg-[#1a1a1a] p-6 shadow-2xl">
            <h3 className="text-lg font-semibold text-white mb-2">Request changes</h3>
            <p className="text-sm text-[#b5b5b5] mb-4">
              Tell the agent exactly what to improve before it retries this deliverable.
            </p>
            <textarea
              value={rejectionNotes}
              onChange={(e) => setRejectionNotes(e.target.value)}
              placeholder="Explain what needs to be changed..."
              className="w-full h-32 resize-none rounded-xl border border-[#464646] bg-[#111111] px-4 py-3 text-sm text-white placeholder:text-[#6b6b6b] focus:border-[#d93854]/70 focus:outline-none mb-4"
              autoFocus
            />
            <div className="flex justify-end gap-3">
              <Button variant="outline" onClick={cancelReject} disabled={isProcessing}>
                Cancel
              </Button>
              <button
                onClick={confirmReject}
                disabled={!rejectionNotes.trim() || isProcessing}
                className={`h-9 rounded-[10px] px-4 text-sm ${CHAT_SECONDARY_BTN}`}
              >
                {isProcessing ? 'Sending...' : 'Send feedback'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default DeliverableReview;
