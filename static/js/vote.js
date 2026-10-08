document.addEventListener('DOMContentLoaded', async () => {
  if (!authToken) {
    window.location.href = '/login';
    return;
  }

  const gate = document.getElementById('vote-gate');
  const paper = document.getElementById('ballot-paper');
  const review = document.getElementById('review-panel');
  const done = document.getElementById('done-panel');
  const houseList = document.getElementById('house-list');
  const senateList = document.getElementById('senate-list');

  let house = [];
  let ranking = [];
  let senateParty = null;

  function renderNumbers() {
    houseList.querySelectorAll('.pref-row').forEach((row) => {
      const id = Number(row.dataset.id);
      const place = ranking.indexOf(id);
      row.querySelector('.pref-box').textContent = place === -1 ? '' : String(place + 1);
    });
  }

  try {
    const status = await apiRequest('/ballots/status');
    if (status.has_voted) {
      gate.innerHTML = '<h2>Already accepted</h2><p>A ballot for this voter has already been stored. It cannot be opened again.</p>';
      return;
    }
    if (!status.can_vote) {
      const reason = !status.enrolled || !status.eligible
        ? 'You are not eligible yet. Ask an enrolment officer to verify the roll.'
        : (!status.division_ok
          ? 'Your division does not match this election (' + status.election.division + ').'
          : 'Voting is not open.');
      gate.innerHTML = '<h2>Ballot not available</h2><p>' + escapeHtml(reason) + '</p><p><a href="/enrolment">Enrolment</a></p>';
      return;
    }

    const catalogue = await apiRequest('/candidates');
    house = (catalogue.candidates || []).filter((row) => row.chamber === 'house' && row.active);
    const senate = (catalogue.candidates || []).filter((row) => row.chamber === 'senate' && row.active);

    house.forEach((candidate) => {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'pref-row';
      button.dataset.id = String(candidate.id);
      button.innerHTML = '<span class="pref-box" aria-hidden="true"></span><span><strong>'
        + escapeHtml(candidate.name) + '</strong><br><span class="party">'
        + escapeHtml(candidate.party) + '</span></span>';
      button.addEventListener('click', () => {
        const id = candidate.id;
        const index = ranking.indexOf(id);
        if (index === -1) ranking.push(id);
        else ranking.splice(index, 1);
        renderNumbers();
      });
      houseList.append(button);
    });

    senate.forEach((group) => {
      const label = document.createElement('label');
      label.className = 'senate-option';
      const input = document.createElement('input');
      input.type = 'radio';
      input.name = 'senate';
      input.value = group.party;
      input.addEventListener('change', () => {
        senateParty = group.party;
      });
      const text = document.createElement('span');
      text.textContent = group.name;
      label.append(input, text);
      senateList.append(label);
    });

    gate.hidden = true;
    paper.hidden = false;
  } catch (err) {
    gate.innerHTML = '<p>' + escapeHtml(err.message) + '</p>';
    if (err.status === 401) window.location.href = '/login';
  }

  document.getElementById('clear-ranking').addEventListener('click', () => {
    ranking = [];
    renderNumbers();
  });

  async function ensureToken() {
    let token = sessionStorage.getItem('ballotToken');
    if (token) return token;
    const issued = await apiRequest('/ballots/issue', { method: 'POST' });
    sessionStorage.setItem('ballotToken', issued.token);
    return issued.token;
  }

  document.getElementById('review-button').addEventListener('click', async () => {
    const button = document.getElementById('review-button');
    button.disabled = true;
    try {
      if (ranking.length !== house.length) {
        showAlert('Number every House candidate once.', 'danger');
        return;
      }
      if (!senateParty) {
        showAlert('Choose one Senate group.', 'danger');
        return;
      }
      const token = await ensureToken();
      const staged = await apiRequest('/ballots/stage', {
        method: 'POST',
        body: JSON.stringify({
          token: token,
          house: ranking,
          senate_party: senateParty,
        }),
      });
      const lines = staged.house.map((row) =>
        '<li>' + row.preference + '. ' + escapeHtml(row.name) + ' <span class="party">' + escapeHtml(row.party) + '</span></li>'
      ).join('');
      document.getElementById('review-body').innerHTML =
        '<p>House preferences</p><ol>' + lines + '</ol>'
        + '<p>Senate group: <strong>' + escapeHtml(staged.senate_name) + '</strong></p>';
      paper.hidden = true;
      review.hidden = false;
    } catch (err) {
      if (err.status === 409) sessionStorage.removeItem('ballotToken');
      showAlert(err.message, 'danger');
    } finally {
      button.disabled = false;
    }
  });

  document.getElementById('back-button').addEventListener('click', () => {
    review.hidden = true;
    paper.hidden = false;
  });

  document.getElementById('commit-button').addEventListener('click', async () => {
    const button = document.getElementById('commit-button');
    button.disabled = true;
    try {
      const token = sessionStorage.getItem('ballotToken');
      const result = await apiRequest('/ballots/commit', {
        method: 'POST',
        body: JSON.stringify({ token: token }),
      });
      sessionStorage.removeItem('ballotToken');
      review.hidden = true;
      document.getElementById('reference').textContent = result.reference;
      done.hidden = false;
      if (authUser) {
        authUser.has_voted = true;
        localStorage.setItem('authUser', JSON.stringify(authUser));
      }
    } catch (err) {
      showAlert(err.message, 'danger');
      button.disabled = false;
    }
  });
});
