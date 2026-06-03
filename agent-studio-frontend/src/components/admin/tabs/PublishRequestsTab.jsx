import ApprovalView from '../../workspace/ApprovalView';

/** Marketplace publish approval queue (existing ApprovalView). */
export default function PublishRequestsTab({ isAdmin }) {
  return (
    <div className="h-full overflow-auto p-6" style={{ backgroundColor: '#0a0a0a' }}>
      <ApprovalView isAdmin={isAdmin} />
    </div>
  );
}
