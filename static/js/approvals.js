function describeApproval(row) {
  if (row.action_type === 'election.status') {
    return ['Poll status', 'Set the poll to ' + row.payload.status];
  }
  if (row.action_type === 'candidate.set_active') {
    return ['Candidate', (row.payload.active ? 'Restore' : 'Withdraw') + ' candidate #' + row.payload.candidate_id];
  }
  return [row.action_type, JSON.stringify(row.payload)];
}

async function decide(id, verb) {
  try {
    await apiRequest('/approvals/' + id + '/' + verb, { method: 'POST' });
    showAlert(verb === 'approve' ? 'Approved and carried out.' : 'Request closed.', 'success');
  } catch (err) {
    showAlert(err.message, 'danger');
  }
  await loadApprovals();
}

async function loadApprovals() {
  const body = document.getElementById('approval-rows');
  const isDelegate = authUser && authUser.role === 'commissioner_delegate';
  const data = await apiRequest('/approvals');
  const rows = data.approvals || [];
  body.replaceChildren();
  if (!rows.length) {
    body.innerHTML = '<tr><td colspan="8">No requests yet.</td></tr>';
    return;
  }
  rows.forEach((row) => {
    const [kind, text] = describeApproval(row);
    const tr = document.createElement('tr');
    tr.innerHTML = '<td>' + row.id + '</td><td>' + escapeHtml(kind) + '</td><td>' + escapeHtml(text)
      + '</td><td>' + escapeHtml(row.proposer_username || '—') + '</td><td>' + escapeHtml(row.approver_username || '—')
      + '</td><td>' + escapeHtml(row.status)
      + '</td><td>' + escapeHtml(row.decided_by_username || '—') + '</td><td></td>';
    const cell = tr.lastElementChild;
    if (isDelegate && row.status === 'proposed') {
      if (row.approver_id === authUser.id) {
        // this request was sent to me: I can approve or reject it
        const approve = document.createElement('button');
        approve.type = 'button';
        approve.className = 'btn';
        approve.textContent = 'Approve';
        approve.addEventListener('click', () => decide(row.id, 'approve'));
        const reject = document.createElement('button');
        reject.type = 'button';
        reject.className = 'btn secondary';
        reject.textContent = 'Reject';
        reject.addEventListener('click', () => decide(row.id, 'reject'));
        cell.append(approve, ' ', reject);
      } else if (row.proposer_id === authUser.id) {
        cell.append('Waiting for ' + (row.approver_username || 'the other delegate'));
      } else {
        cell.append('Sent to another delegate');
      }
    }
    body.append(tr);
  });
}

document.addEventListener('DOMContentLoaded', async () => {
  if (!authToken) {
    window.location.href = '/login';
    return;
  }
  try {
    await loadApprovals();
  } catch (err) {
    showAlert(err.message, 'danger');
  }
});
