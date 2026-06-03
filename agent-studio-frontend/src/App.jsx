import { Component, lazy, Suspense } from 'react';
import { ThemeProvider } from './context/ThemeContext';
import { AuthProvider, useAuth } from './context/AuthContext';
import { WorkflowProvider, useWorkflow } from './context/WorkflowContext';
import ApexTopBar from './components/shell/ApexTopBar';
import LoginForm from './components/auth/LoginForm';

const BuilderView = lazy(() => import('./components/builder/BuilderView'));
const ChatView = lazy(() => import('./components/chat/ChatView'));
const ApexShell = lazy(() => import('./components/shell/ApexShell'));
const KBDetailView = lazy(() => import('./components/knowledgebases/KBDetailView'));
const AIChartTest = lazy(() => import('./components/test/AIChartTest'));

class ErrorBoundary extends Component {
  state = { hasError: false, error: null };

  static getDerivedStateFromError(error) {
    return { hasError: true, error };
  }

  componentDidCatch(error, info) {
    console.error('Unhandled React error:', error, info.componentStack);
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="h-screen w-screen flex items-center justify-center bg-gray-50">
          <div className="text-center max-w-md px-6">
            <h2 className="text-xl font-semibold text-gray-800 mb-2">Something went wrong</h2>
            <p className="text-sm text-gray-500 mb-4">
              {this.state.error?.message || 'An unexpected error occurred.'}
            </p>
            <button
              onClick={() => window.location.reload()}
              className="px-4 py-2 bg-blue-600 text-white rounded-lg text-sm hover:bg-blue-700 transition-colors"
            >
              Reload
            </button>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}

function AppContent() {
  const { state, dispatch, ACTIONS } = useWorkflow();
  const { isAuthenticated, loading } = useAuth();

  // Check URL for test mode
  const urlParams = new URLSearchParams(window.location.search);
  const isTestMode = urlParams.has('test') && urlParams.get('test') === 'chart';

  // Show loading state while checking auth
  if (loading) {
    return (
      <div className="h-screen w-screen flex items-center justify-center bg-gray-50">
        <div className="text-center">
          <div className="inline-block animate-spin rounded-full h-8 w-8 border-b-2 border-gray-600"></div>
          <p className="mt-2 text-sm text-gray-600">Loading...</p>
        </div>
      </div>
    );
  }

  // Not authenticated: show branded spinner that auto-redirects to Microsoft SSO
  if (!isAuthenticated) {
    return <LoginForm />;
  }

  if (isTestMode) {
    return (
      <div className="w-full h-auto">
        <Suspense fallback={<div className="h-screen flex items-center justify-center"><div className="inline-block animate-spin rounded-full h-8 w-8 border-b-2 border-gray-600" /></div>}>
          <AIChartTest />
        </Suspense>
      </div>
    );
  }

  // Tabs in the dark Apex OS top bar always navigate back to the
  // workspace shell (Storefront / My Sessions / My Tools). When a user
  // is in chat or kb-detail, clicking a tab should return them home.
  const handleTopBarTab = (tab) => {
    dispatch({
      type: ACTIONS.NAVIGATE,
      payload: {
        view: 'workspace',
        activeTab: tab,
      },
    });
  };

  const showSharedChrome = state.currentView === 'kb-detail';

  return (
    <div className="min-h-[100dvh] h-[100dvh] w-screen overflow-hidden bg-canvas flex flex-col">
      {showSharedChrome && (
        <ApexTopBar
          activeTab={state.activeTab || 'storefront'}
          onTabChange={handleTopBarTab}
        />
      )}
      <div className="flex-1 min-h-0 overflow-hidden">
        <Suspense fallback={
          <div className="h-full w-full flex items-center justify-center">
            <div className="inline-block animate-spin rounded-full h-8 w-8 border-b-2 border-[#d93854]" />
          </div>
        }>
          {state.currentView === 'workspace' && <ApexShell />}
          {state.currentView === 'builder' && <BuilderView />}
          {state.currentView === 'chat' && <ChatView />}
          {state.currentView === 'kb-detail' && state.selectedKB && (
            <KBDetailView
              kbId={state.selectedKB.kb_id}
              isShared={state.selectedKB.is_shared || false}
              shareAccess={state.selectedKB.share_access || null}
            />
          )}
        </Suspense>
      </div>
    </div>
  );
}

function App() {
  return (
    <ErrorBoundary>
      <ThemeProvider>
        <AuthProvider>
          <WorkflowProvider>
            <AppContent />
          </WorkflowProvider>
        </AuthProvider>
      </ThemeProvider>
    </ErrorBoundary>
  );
}

export default App;
