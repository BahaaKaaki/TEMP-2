import { useState, useEffect, useRef } from 'react';
import Button from '../ui/Button';

export default function WorkflowDescriptionModal({ isOpen, onClose, onSave, initialData }) {
  const [title, setTitle] = useState('');
  const [description, setDescription] = useState('');
  const [steps, setSteps] = useState(['']);
  const stepsEndRef = useRef(null);

  useEffect(() => {
    if (isOpen && initialData) {
      setTitle(initialData.title || '');
      setDescription(initialData.description || '');
      setSteps(initialData.steps?.length ? [...initialData.steps] : ['']);
    } else if (isOpen) {
      setTitle('');
      setDescription('');
      setSteps(['']);
    }
  }, [isOpen, initialData]);

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

  const handleAddStep = () => {
    setSteps([...steps, '']);
    setTimeout(() => stepsEndRef.current?.scrollIntoView({ behavior: 'smooth' }), 50);
  };

  const handleRemoveStep = (index) => {
    if (steps.length <= 1) return;
    setSteps(steps.filter((_, i) => i !== index));
  };

  const handleStepChange = (index, value) => {
    const updated = [...steps];
    updated[index] = value;
    setSteps(updated);
  };

  const handleSave = () => {
    const trimmedSteps = steps.map(s => s.trim()).filter(Boolean);
    onSave({
      title: title.trim(),
      description: description.trim(),
      steps: trimmedSteps,
    });
    onClose();
  };

  const handleClear = () => {
    onSave(null);
    onClose();
  };

  const hasContent = title.trim() || description.trim() || steps.some(s => s.trim());

  return (
    <div
      data-theme="apex-dark"
      className="fixed inset-0 z-[9999] flex items-center justify-center"
      style={{ backgroundColor: 'rgba(0, 0, 0, 0.7)' }}
      onClick={onClose}
    >
      <div
        className="rounded-2xl shadow-2xl w-[94%] max-w-2xl max-h-[85vh] flex flex-col overflow-hidden"
        style={{
          background: 'linear-gradient(135deg, #1a1a1a 0%, #0d0d0d 100%)',
          border: '1px solid #464646',
          color: '#ffffff',
        }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-200 bg-gray-50">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-lg bg-gray-200 flex items-center justify-center">
              <svg className="w-4.5 h-4.5 text-gray-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
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
        <div className="flex-1 overflow-y-auto px-6 py-5 space-y-5">
          {/* Title */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1.5">Title</label>
            <input
              type="text"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="e.g. How to use this workflow"
              className="w-full px-4 py-2.5 bg-white border border-gray-300 rounded-lg text-gray-900 placeholder:text-gray-400 focus:outline-none focus:ring-2 focus:ring-red-600/20 focus:border-red-600 transition-colors"
            />
          </div>

          {/* Description */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1.5">Description</label>
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="What this workflow does and how to use it..."
              rows={3}
              className="w-full px-4 py-2.5 bg-white border border-gray-300 rounded-lg text-gray-900 placeholder:text-gray-400 focus:outline-none focus:ring-2 focus:ring-red-600/20 focus:border-red-600 transition-colors resize-none"
            />
          </div>

          {/* Steps */}
          <div>
            <div className="flex items-center justify-between mb-3">
              <label className="block text-sm font-medium text-gray-700">Steps</label>
              <span className="text-xs text-gray-400">{steps.length} step{steps.length !== 1 ? 's' : ''}</span>
            </div>

            <div className="space-y-3">
              {steps.map((step, index) => (
                <div key={index} className="flex items-start gap-3 group">
                  {/* Red circle number */}
                  <div className="w-7 h-7 rounded-full bg-red-600 text-white flex items-center justify-center text-sm font-semibold shrink-0 mt-1.5 shadow-sm">
                    {index + 1}
                  </div>

                  {/* Step input */}
                  <input
                    type="text"
                    value={step}
                    onChange={(e) => handleStepChange(index, e.target.value)}
                    placeholder={`Step ${index + 1}...`}
                    className="flex-1 px-4 py-2 bg-white border border-gray-300 rounded-lg text-gray-900 placeholder:text-gray-400 focus:outline-none focus:ring-2 focus:ring-red-600/20 focus:border-red-600 transition-colors text-sm"
                  />

                  {/* Remove button */}
                  <button
                    onClick={() => handleRemoveStep(index)}
                    disabled={steps.length <= 1}
                    className="w-8 h-8 mt-0.5 flex items-center justify-center rounded-lg text-gray-400 hover:text-red-500 hover:bg-red-50 transition-colors opacity-0 group-hover:opacity-100 disabled:opacity-0 disabled:cursor-not-allowed"
                    title="Remove step"
                  >
                    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                    </svg>
                  </button>
                </div>
              ))}
              <div ref={stepsEndRef} />
            </div>

            {/* Add step button */}
            <button
              onClick={handleAddStep}
              className="mt-3 flex items-center gap-2 px-4 py-2 text-sm font-medium text-red-700 hover:text-red-800 hover:bg-red-50 rounded-lg transition-colors"
            >
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
              </svg>
              Add Step
            </button>
          </div>
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between px-6 py-4 border-t border-gray-200 bg-gray-50">
          <div>
            {hasContent && (
              <button
                onClick={handleClear}
                className="text-sm text-gray-500 hover:text-red-600 transition-colors"
              >
                Clear All
              </button>
            )}
          </div>
          <div className="flex items-center gap-3">
            <Button variant="outline" size="sm" onClick={onClose}>
              Cancel
            </Button>
            <button
              onClick={handleSave}
              className="h-8 rounded-md px-4 text-sm font-medium text-white bg-red-600 hover:bg-red-700 transition-colors shadow-sm"
            >
              Save Description
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
