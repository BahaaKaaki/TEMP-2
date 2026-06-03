import { useEffect } from 'react';

export default function WorkflowDescriptionViewer({ isOpen, onClose, data }) {
  useEffect(() => {
    const handleEscape = (e) => {
      if (e.key === 'Escape' && isOpen) onClose();
    };
    document.addEventListener('keydown', handleEscape);
    return () => document.removeEventListener('keydown', handleEscape);
  }, [isOpen, onClose]);

  useEffect(() => {
    if (isOpen) {
      document.body.style.overflow = 'hidden';
    } else {
      document.body.style.overflow = 'unset';
    }
    return () => { document.body.style.overflow = 'unset'; };
  }, [isOpen]);

  if (!isOpen) return null;

  const hasData = data && (data.title || data.description || data.steps?.length);

  return (
    <div
      className="fixed inset-0 z-[9999] flex items-center justify-center bg-black/50"
      onClick={onClose}
    >
      <div
        className="bg-white rounded-xl shadow-2xl w-[94%] max-w-2xl max-h-[85vh] flex flex-col overflow-hidden border border-gray-200"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-200 bg-gray-50 shrink-0">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-lg bg-gray-200 flex items-center justify-center">
              <svg className="w-4.5 h-4.5 text-gray-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8.228 9c.549-1.165 2.03-2 3.772-2 2.21 0 4 1.343 4 3 0 1.4-1.278 2.575-3.006 2.907-.542.104-.994.54-.994 1.093m0 3h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
            </div>
            <h3 className="text-lg font-semibold text-gray-900">Guide</h3>
          </div>
          <button
            onClick={onClose}
            className="w-8 h-8 flex items-center justify-center rounded-lg hover:bg-gray-200 transition-colors text-gray-500 hover:text-gray-700"
          >
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto px-6 py-5 min-h-0">
          {!hasData ? (
            <div className="flex flex-col items-center justify-center py-12 text-center">
              <div className="w-14 h-14 rounded-full bg-gray-100 flex items-center justify-center mb-4">
                <svg className="w-7 h-7 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                </svg>
              </div>
              <p className="text-sm font-medium text-gray-500">No description available</p>
              <p className="text-xs text-gray-400 mt-1">This workflow doesn't have a detailed description yet.</p>
            </div>
          ) : (
            <div className="space-y-5">
              {/* Title */}
              {data.title && (
                <h4 className="text-xl font-bold text-gray-900 break-words">{data.title}</h4>
              )}

              {/* Description */}
              {data.description && (
                <p className="text-sm text-gray-600 leading-relaxed whitespace-pre-wrap break-words">{data.description}</p>
              )}

              {/* Divider */}
              {(data.title || data.description) && data.steps?.length > 0 && (
                <div className="border-t border-gray-100" />
              )}

              {/* Steps */}
              {data.steps?.length > 0 && (
                <div>
                  <h5 className="text-sm font-semibold text-gray-700 mb-4 uppercase tracking-wide">Steps</h5>
                  <div className="space-y-0">
                    {data.steps.map((step, index) => (
                      <div key={index} className="flex items-start gap-4 relative">
                        {index < data.steps.length - 1 && (
                          <div className="absolute left-[13px] top-8 bottom-0 w-0.5 bg-red-300" />
                        )}

                        <div className="w-7 h-7 rounded-full bg-red-600 text-white flex items-center justify-center text-sm font-semibold shrink-0 shadow-sm z-10">
                          {index + 1}
                        </div>

                        <p className="text-sm text-gray-700 pt-1 pb-5 leading-relaxed break-words min-w-0">{step}</p>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-end px-6 py-3 border-t border-gray-200 bg-gray-50 shrink-0">
          <button
            onClick={onClose}
            className="h-8 rounded-md px-4 text-sm font-medium text-gray-700 border border-gray-300 bg-white hover:bg-gray-100 transition-colors"
          >
            Close
          </button>
        </div>
      </div>
    </div>
  );
}
