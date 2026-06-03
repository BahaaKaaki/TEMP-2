import { useCallback, useEffect, useRef, useState, lazy, Suspense } from 'react';
import { useWorkflow } from '@/context/WorkflowContext';
import {
  fetchSubmissionWorkflowPreview,
  testSubmissionWorkflow,
} from '@/api/approval';
import { createChatSession, deleteChatSession } from '@/api/client';
import { buildCanvasPayloadFromWorkflow } from '@/utils/hydrateWorkflowCanvas';
import Canvas from '../builder/Canvas';
import NodeConfigPanel from '../builder/NodeConfigPanel';
import AlertModal from '../ui/AlertModal';
import { COLOR, FONT, BACKGROUND } from '../builder/figmaSpec';

const ChatView = lazy(() => import('../chat/ChatView'));

const ROOT_DOT_GRID = `url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='${BACKGROUND.tile}' height='${BACKGROUND.tile}'><circle cx='${BACKGROUND.tile / 2}' cy='${BACKGROUND.tile / 2}' r='${BACKGROUND.dotRadius}' fill='white' fill-opacity='0.18'/></svg>")`;

/**
 * Read-only workflow builder canvas for reviewing a pending publish submission.
 * Inspect nodes on the canvas; run tests against an admin-owned copy.
 */
export default function SubmissionWorkflowReview({ submission, onClose }) {
  const { state, dispatch, ACTIONS } = useWorkflow();
  const restoreRef = useRef(null);
  const testSessionIdRef = useRef(null);
  const testSessionObjRef = useRef(null);

  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(null);
  const [previewMeta, setPreviewMeta] = useState(null);
  const [processingTest, setProcessingTest] = useState(false);
  const [showTestChat, setShowTestChat] = useState(false);
  const [testWorkflowId, setTestWorkflowId] = useState(null);
  const [alertModal, setAlertModal] = useState({
    isOpen: false,
    title: '',
    message: '',
    variant: 'error',
  });

  const restoreCanvas = useCallback(() => {
    const snap = restoreRef.current;
    if (!snap) return;
    dispatch({
      type: ACTIONS.LOAD_TEMPLATE,
      payload: {
        id: snap.selectedWorkflow?.id,
        name: snap.selectedWorkflow?.name,
        nodes: snap.nodes,
        connections: snap.connections,
      },
    });
    dispatch({
      type: ACTIONS.SELECT_WORKFLOW,
      payload: snap.selectedWorkflow,
    });
    dispatch({ type: ACTIONS.SELECT_NODES, payload: snap.selectedNodeIds || [] });
    restoreRef.current = null;
  }, [dispatch, ACTIONS]);

  const handleClose = useCallback(async () => {
    const sid = testSessionIdRef.current;
    if (sid) {
      try {
        await deleteChatSession(sid, true);
      } catch {
        /* best-effort */
      }
      testSessionIdRef.current = null;
      testSessionObjRef.current = null;
    }
    restoreCanvas();
    onClose();
  }, [onClose, restoreCanvas]);

  useEffect(() => {
    let cancelled = false;

    const nodes = Array.from(state.canvasNodes.values());
    restoreRef.current = {
      nodes,
      connections: [...state.connections],
      selectedWorkflow: state.selectedWorkflow,
      selectedNodeIds: [...state.selectedNodeIds],
    };

    (async () => {
      try {
        setLoading(true);
        setLoadError(null);
        const workflow = await fetchSubmissionWorkflowPreview(submission.id);
        if (cancelled) return;

        const payload = buildCanvasPayloadFromWorkflow(workflow);
        dispatch({ type: ACTIONS.LOAD_TEMPLATE, payload });
        dispatch({
          type: ACTIONS.SELECT_WORKFLOW,
          payload: {
            id: workflow.workflowId,
            name: workflow.name,
            nodes: workflow.nodes,
            connections: workflow.connections,
            permission: 'read',
            shareAccess: 'read',
            isSubmissionPreview: true,
          },
        });
        setPreviewMeta({
          marketplaceName: workflow.marketplaceName || submission.marketplaceName,
          workflowName: workflow.name,
          description: workflow.marketplaceDescription || submission.marketplaceDescription,
        });
      } catch (err) {
        if (!cancelled) {
          setLoadError(err.message || 'Failed to load workflow');
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();

    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [submission.id]);

  const handleTest = async () => {
    try {
      setProcessingTest(true);
      let wfId = testWorkflowId;
      if (!wfId) {
        const result = await testSubmissionWorkflow(submission.id);
        wfId = result.testWorkflowId;
        setTestWorkflowId(wfId);
      }

      if (testSessionIdRef.current && testSessionObjRef.current) {
        dispatch({ type: ACTIONS.SELECT_SESSION, payload: testSessionObjRef.current });
        setShowTestChat(true);
        return;
      }

      const newSession = await createChatSession(wfId, {
        name: `Review test - ${previewMeta?.marketplaceName || submission.marketplaceName}`,
        description: 'Admin review test session',
      });
      testSessionIdRef.current = newSession.id;
      testSessionObjRef.current = newSession;
      dispatch({ type: ACTIONS.SELECT_SESSION, payload: newSession });
      setShowTestChat(true);
    } catch (err) {
      setAlertModal({
        isOpen: true,
        title: 'Test failed',
        message: err.message || 'Could not start test session',
        variant: 'error',
      });
    } finally {
      setProcessingTest(false);
    }
  };

  const handleCloseTestChat = () => {
    setShowTestChat(false);
  };

  return (
    <div
      className="fixed inset-0 z-[100] flex flex-col"
      style={{
        backgroundColor: COLOR.black,
        backgroundImage: ROOT_DOT_GRID,
        backgroundSize: `${BACKGROUND.tile}px ${BACKGROUND.tile}px`,
      }}
    >
      <header
        className="flex items-center gap-4 shrink-0 border-b px-5"
        style={{
          height: 56,
          borderColor: COLOR.darker,
          backgroundColor: COLOR.darkest,
        }}
      >
        <button
          type="button"
          onClick={handleClose}
          className="flex items-center justify-center rounded-lg transition-colors hover:bg-white/10"
          style={{ width: 36, height: 36, color: COLOR.medium }}
          title="Back to publish requests"
        >
          <img src="/icons/back.svg" alt="Back" style={{ width: 20, height: 20 }} draggable={false} />
        </button>

        <div className="flex-1 min-w-0">
          <p
            className="truncate"
            style={{
              color: COLOR.white,
              fontSize: 16,
              fontWeight: 700,
              lineHeight: '20px',
            }}
          >
            {previewMeta?.marketplaceName || submission.marketplaceName}
          </p>
          <p className="truncate text-xs" style={{ color: COLOR.medium }}>
            {previewMeta?.workflowName || submission.workflowName}
            <span className="mx-2">·</span>
            <span
              className="inline-flex items-center rounded px-1.5 py-0.5"
              style={{ backgroundColor: 'rgba(234, 88, 12, 0.25)', color: '#fb923c' }}
            >
              Review only
            </span>
          </p>
        </div>

        <button
          type="button"
          onClick={handleTest}
          disabled={loading || !!loadError || processingTest}
          className="flex items-center gap-2 rounded-full px-4 transition-colors disabled:opacity-50"
          style={{
            height: 40,
            backgroundColor: COLOR.roseDarkBg,
            color: COLOR.rose,
            fontSize: FONT.button?.size || 14,
            fontWeight: 700,
          }}
        >
          <img src="/icons/test-chat.svg" alt="" style={{ width: 22, height: 22 }} draggable={false} />
          {processingTest
            ? 'Starting test…'
            : showTestChat
              ? 'Testing'
              : testWorkflowId
                ? 'Resume test'
                : 'Test workflow'}
        </button>
      </header>

      <div className="flex-1 min-h-0 flex flex-col relative">
        {loading && (
          <div className="absolute inset-0 z-10 flex items-center justify-center" style={{ backgroundColor: 'rgba(0,0,0,0.6)' }}>
            <div className="animate-spin rounded-full h-10 w-10 border-b-2 border-gray-400" />
          </div>
        )}

        {loadError && (
          <div className="flex-1 flex flex-col items-center justify-center gap-4 p-8 text-center">
            <p style={{ color: COLOR.rose }}>{loadError}</p>
            <button
              type="button"
              onClick={handleClose}
              className="text-sm underline"
              style={{ color: COLOR.medium }}
            >
              Back to publish requests
            </button>
          </div>
        )}

        {!loadError && (
          <div className="flex flex-1 min-h-0 overflow-hidden">
            {showTestChat ? (
              <Suspense
                fallback={
                  <div className="flex-1 flex items-center justify-center">
                    <div className="inline-block animate-spin rounded-full h-8 w-8 border-b-2 border-gray-600" />
                  </div>
                }
              >
                <ChatView testMode onClose={handleCloseTestChat} />
              </Suspense>
            ) : (
              <>
                <Canvas readOnly />
                {state.selectedNodeIds?.length > 0 && (
                  <NodeConfigPanel key={state.selectedNodeIds[0]} readOnly />
                )}
              </>
            )}
          </div>
        )}
      </div>

      <AlertModal
        isOpen={alertModal.isOpen}
        title={alertModal.title}
        message={alertModal.message}
        variant={alertModal.variant}
        onClose={() =>
          setAlertModal({ isOpen: false, title: '', message: '', variant: 'error' })
        }
      />
    </div>
  );
}
