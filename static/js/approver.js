// Shared by the dashboard and the candidates page (GR-14).
// A delegate must say WHICH other delegate has to approve the request.

async function loadApproverChoices(select) {
  const data = await apiRequest('/approvals/delegates');
  const delegates = data.delegates || [];
  select.replaceChildren();
  delegates.forEach((delegate) => {
    const option = document.createElement('option');
    option.value = delegate.id;
    option.textContent = delegate.full_name + ' (' + delegate.username + ')';
    select.append(option);
  });
  return delegates.length;
}

async function loadWaitingRequests() {
  const data = await apiRequest('/approvals?status=proposed');
  return data.approvals || [];
}
