document.addEventListener('DOMContentLoaded', async () => {
  if (!authToken) {
    window.location.href = '/login';
    return;
  }
  const welcome = document.getElementById('welcome');
  const statusLine = document.getElementById('status-line');
  const desk = document.getElementById('desk');
  try {
    const profile = await apiRequest('/auth/profile');
    storeSession(authToken, profile.user);
    const user = profile.user;
    welcome.textContent = 'Hello, ' + user.full_name;
    const label = ROLE_LABELS[user.role] || user.role;
    statusLine.textContent = label + (user.division ? ' · ' + user.division : '');

    const actions = document.createElement('div');
    actions.className = 'card stack';
    const aside = document.createElement('div');
    aside.className = 'card';

    if (user.role === 'voter') {
      const state = user.has_voted
        ? 'A ballot has already been accepted for you.'
        : (user.eligible && user.enrolled
          ? 'You are eligible. The ballot is ready.'
          : 'An enrolment officer still needs to verify you.');
      actions.innerHTML = '<h2>Voter</h2><p>' + state + '</p>';
      const vote = document.createElement('a');
      vote.className = 'btn';
      vote.href = '/vote';
      vote.textContent = user.has_voted ? 'View ballot status' : 'Mark ballot';
      const enrol = document.createElement('a');
      enrol.className = 'btn secondary';
      enrol.href = '/enrolment';
      enrol.textContent = 'Enrolment details';
      actions.append(vote, enrol);
    } else if (user.role === 'enrolment_officer') {
      actions.innerHTML = '<h2>Enrolment</h2><p>Verify citizens before they can be issued a ballot.</p>';
      const link = document.createElement('a');
      link.className = 'btn';
      link.href = '/enrolment';
      link.textContent = 'Open the roll';
      actions.append(link);
    } else if (user.role === 'commissioner_delegate') {
      actions.innerHTML = '<h2>Election control</h2><p id="poll-line">Loading election…</p>';
      const toggle = document.createElement('button');
      toggle.className = 'btn';
      toggle.type = 'button';
      toggle.textContent = 'Propose: close polls';
      const candidates = document.createElement('a');
      candidates.className = 'btn secondary';
      candidates.href = '/candidates';
      candidates.textContent = 'Edit candidates';
      actions.append(toggle, candidates);
      const pollLine = actions.querySelector('#poll-line');
      const electionData = await apiRequest('/elections/current');
      const election = electionData.election;
      pollLine.textContent =
        election.name + ' is ' + election.status + ' in ' + election.division + '.';
      toggle.textContent = election.status === 'open' ? 'Propose: close polls' : 'Propose: reopen polls';
      const approvals = document.createElement('a');
      approvals.className = 'btn secondary';
      approvals.href = '/approvals';
      approvals.textContent = 'Approvals';
      actions.append(approvals);

      // GR-14: the proposer chooses which delegate must approve
      const choice = document.createElement('div');
      const choiceLabel = document.createElement('label');
      choiceLabel.setAttribute('for', 'poll-approver');
      choiceLabel.textContent = 'Send the request to';
      const approver = document.createElement('select');
      approver.id = 'poll-approver';
      choice.append(choiceLabel, approver);
      actions.insertBefore(choice, toggle);
      const others = await loadApproverChoices(approver);
      const waiting = (await loadWaitingRequests()).find((request) => request.action_type === 'election.status');
      if (waiting) {
        toggle.disabled = true;
        approver.disabled = true;
        const waitingFor = waiting.approver_id === user.id ? 'you (open Approvals to decide)' : waiting.approver_username;
        pollLine.textContent += ' Request #' + waiting.id + ' is waiting for ' + waitingFor
          + '. No new request can be sent until it is decided.';
      } else if (!others) {
        toggle.disabled = true;
        pollLine.textContent += ' There is no other delegate to approve a request.';
      }
      toggle.addEventListener('click', async () => {
        toggle.disabled = true;
        try {
          const next = election.status === 'open' ? 'closed' : 'open';
          const result = await apiRequest('/approvals', {
            method: 'POST',
            body: JSON.stringify({ action_type: 'election.status', status: next, approver_id: Number(approver.value) }),
          });
          approver.disabled = true;
          showAlert('Request #' + result.approval.id + ' sent to ' + result.approval.approver_username + '. Only that delegate can approve or reject it.', 'success');
        } catch (err) {
          showAlert(err.message, 'danger');
          toggle.disabled = false;
        }
      });
    } else if (user.role === 'auditor') {
      actions.innerHTML = '<h2>Audit</h2><p>Read the record of administrative actions. Vote content is not stored here.</p>';
      const link = document.createElement('a');
      link.className = 'btn';
      link.href = '/audit';
      link.textContent = 'Open the log';
      actions.append(link);
    }

    aside.innerHTML = '<h2>Also on this desk</h2>';
    const links = document.createElement('div');
    links.className = 'stack';
    [['/candidates', 'Candidate list'], ['/results', 'Results']].forEach(([href, text]) => {
      const anchor = document.createElement('a');
      anchor.href = href;
      anchor.textContent = text;
      links.append(anchor);
    });
    aside.append(links);
    desk.append(actions, aside);
  } catch (err) {
    welcome.textContent = 'Desk unavailable';
    showAlert(err.message, 'danger');
    if (err.status === 401) window.location.href = '/login';
  }
});