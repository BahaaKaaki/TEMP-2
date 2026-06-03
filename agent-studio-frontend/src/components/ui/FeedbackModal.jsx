import { useState } from 'react';
import { submitFeedback } from '../../api/client';

const CATEGORIES = [
  { value: 'bug', label: 'Bug Report', icon: '⚠' },
  { value: 'feature_request', label: 'Feature Request', icon: '✦' },
  { value: 'improvement', label: 'Improvement', icon: '↑' },
  { value: 'usability', label: 'Usability', icon: '◎' },
  { value: 'performance', label: 'Performance', icon: '⚡' },
  { value: 'other', label: 'Other', icon: '…' },
];

export default function FeedbackModal({ isOpen, onClose }) {
  const [category, setCategory] = useState('');
  const [subject, setSubject] = useState('');
  const [message, setMessage] = useState('');
  const [rating, setRating] = useState(0);
  const [hoveredRating, setHoveredRating] = useState(0);
  const [submitting, setSubmitting] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  const [error, setError] = useState('');

  const resetForm = () => {
    setCategory('');
    setSubject('');
    setMessage('');
    setRating(0);
    setHoveredRating(0);
    setError('');
    setSubmitted(false);
  };

  const handleClose = () => {
    resetForm();
    onClose();
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');

    if (!category) { setError('Please select a category.'); return; }
    if (!subject.trim()) { setError('Please enter a subject.'); return; }
    if (!message.trim()) { setError('Please describe your feedback.'); return; }

    setSubmitting(true);
    try {
      await submitFeedback({
        category,
        subject: subject.trim(),
        message: message.trim(),
        rating: rating || null,
        pageUrl: window.location.href,
      });
      setSubmitted(true);
    } catch (err) {
      setError(err.message || 'Something went wrong. Please try again.');
    } finally {
      setSubmitting(false);
    }
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-[2000] flex items-center justify-center">
      {/* Backdrop */}
      <div className="absolute inset-0 bg-black/40 backdrop-blur-sm" onClick={handleClose} />

      {/* Modal */}
      <div className="relative bg-white rounded-xl shadow-2xl w-full max-w-lg mx-4 overflow-hidden animate-in fade-in zoom-in duration-200">
        {/* Header */}
        <div className="px-6 py-4 border-b border-gray-200" style={{ background: 'linear-gradient(135deg, #A32020 0%, #82141E 100%)' }}>
          <div className="flex items-center justify-between">
            <div>
              <h2 className="text-lg font-semibold text-white">Share Your Feedback</h2>
              <p className="text-sm text-white/80 mt-0.5">
                We value your input — help us improve your experience.
              </p>
            </div>
            <button
              onClick={handleClose}
              className="text-white/70 hover:text-white transition-colors p-1 rounded-lg hover:bg-white/10"
            >
              <svg width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
                <path d="M5 5l10 10M15 5L5 15" />
              </svg>
            </button>
          </div>
        </div>

        {submitted ? (
          <div className="px-6 py-10 text-center">
            <div className="w-14 h-14 rounded-full bg-green-50 flex items-center justify-center mx-auto mb-4">
              <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="#1AAB40" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                <polyline points="20 6 9 17 4 12" />
              </svg>
            </div>
            <h3 className="text-lg font-semibold text-gray-900 mb-1">Thank you for your feedback!</h3>
            <p className="text-sm text-gray-500 mb-6">Your input helps us build a better platform for everyone.</p>
            <button
              onClick={handleClose}
              className="px-5 py-2 text-sm font-medium text-white rounded-lg transition-colors"
              style={{ backgroundColor: '#A32020' }}
              onMouseEnter={(e) => e.target.style.backgroundColor = '#7A1818'}
              onMouseLeave={(e) => e.target.style.backgroundColor = '#A32020'}
            >
              Close
            </button>
          </div>
        ) : (
          <form onSubmit={handleSubmit} className="px-6 py-5 space-y-4 max-h-[65vh] overflow-y-auto">
            {/* Category Selection */}
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">Category</label>
              <div className="grid grid-cols-3 gap-2">
                {CATEGORIES.map((cat) => (
                  <button
                    key={cat.value}
                    type="button"
                    onClick={() => setCategory(cat.value)}
                    className={`flex flex-col items-center gap-1 px-3 py-2.5 rounded-lg border text-xs font-medium transition-all ${
                      category === cat.value
                        ? 'border-[#A32020] bg-[#A32020]/5 text-[#A32020] shadow-sm'
                        : 'border-gray-200 text-gray-600 hover:border-gray-300 hover:bg-gray-50'
                    }`}
                  >
                    <span className="text-base leading-none">{cat.icon}</span>
                    <span>{cat.label}</span>
                  </button>
                ))}
              </div>
            </div>

            {/* Subject */}
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1.5">Subject</label>
              <input
                type="text"
                value={subject}
                onChange={(e) => setSubject(e.target.value)}
                placeholder="Brief summary of your feedback"
                maxLength={255}
                className="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-[#A32020]/20 focus:border-[#A32020] transition-colors placeholder:text-gray-400"
              />
            </div>

            {/* Message */}
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1.5">Details</label>
              <textarea
                value={message}
                onChange={(e) => setMessage(e.target.value)}
                placeholder="Please provide as much detail as possible..."
                rows={4}
                className="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-[#A32020]/20 focus:border-[#A32020] transition-colors resize-none placeholder:text-gray-400"
              />
            </div>

            {/* Rating */}
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1.5">
                Overall Experience <span className="text-gray-400 font-normal">(optional)</span>
              </label>
              <div className="flex items-center gap-1">
                {[1, 2, 3, 4, 5].map((star) => (
                  <button
                    key={star}
                    type="button"
                    onClick={() => setRating(star === rating ? 0 : star)}
                    onMouseEnter={() => setHoveredRating(star)}
                    onMouseLeave={() => setHoveredRating(0)}
                    className="p-0.5 transition-transform hover:scale-110"
                  >
                    <svg
                      width="24"
                      height="24"
                      viewBox="0 0 24 24"
                      fill={(hoveredRating || rating) >= star ? '#A32020' : 'none'}
                      stroke={(hoveredRating || rating) >= star ? '#A32020' : '#CBD5E1'}
                      strokeWidth="1.5"
                    >
                      <polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2" />
                    </svg>
                  </button>
                ))}
                {rating > 0 && (
                  <span className="text-xs text-gray-400 ml-2">
                    {['', 'Poor', 'Fair', 'Good', 'Very Good', 'Excellent'][rating]}
                  </span>
                )}
              </div>
            </div>

            {/* Error */}
            {error && (
              <div className="flex items-center gap-2 px-3 py-2 text-sm text-red-700 bg-red-50 rounded-lg border border-red-100">
                <svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor">
                  <path d="M8 1a7 7 0 100 14A7 7 0 008 1zm-.75 4a.75.75 0 011.5 0v3a.75.75 0 01-1.5 0V5zM8 11.5a.75.75 0 100-1.5.75.75 0 000 1.5z" />
                </svg>
                {error}
              </div>
            )}

            {/* Footer */}
            <div className="flex items-center justify-end gap-3 pt-2">
              <button
                type="button"
                onClick={handleClose}
                className="px-4 py-2 text-sm font-medium text-gray-600 hover:text-gray-800 hover:bg-gray-100 rounded-lg transition-colors"
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={submitting}
                className="px-5 py-2 text-sm font-medium text-white rounded-lg transition-all disabled:opacity-60 disabled:cursor-not-allowed"
                style={{ backgroundColor: '#A32020' }}
                onMouseEnter={(e) => { if (!submitting) e.target.style.backgroundColor = '#7A1818'; }}
                onMouseLeave={(e) => e.target.style.backgroundColor = '#A32020'}
              >
                {submitting ? (
                  <span className="flex items-center gap-2">
                    <svg className="animate-spin h-4 w-4" viewBox="0 0 24 24" fill="none">
                      <circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3" strokeDasharray="31.4 31.4" strokeLinecap="round" />
                    </svg>
                    Submitting…
                  </span>
                ) : 'Submit Feedback'}
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  );
}
