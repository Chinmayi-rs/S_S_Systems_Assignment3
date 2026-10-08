async function loadCandidates() {
  const data = await apiRequest('/candidates');
  const election = data.election;
  document.getElementById('candidate-election').textContent = election
    ? election.name + ' · ' + election.division + ' · ' + election.status
    : 'No election.';
  const body = document.getElementById('candidate-rows');
  body.replaceChildren();
  const isDelegate = authUser && authUser.role === 'commissioner_delegate';
  (data.candidates || []).forEach((row) => {
    const tr = document.createElement('tr');
    tr.innerHTML = '<td>' + row.ballot_order + '</td><td>' + escapeHtml(row.chamber)
      + '</td><td>' + escapeHtml(row.name) + '</td><td>' + escapeHtml(row.party)
      + '</td><td>' + (row.active ? 'On the paper' : 'Withdrawn') + '</td><td></td>';
    if (isDelegate && row.active) {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'btn secondary';
      button.textContent = 'Withdraw';
      button.addEventListener('click', async () => {
        button.disabled = true;
        try {
          await apiRequest('/candidates/' + row.id, {
            method: 'PATCH',
            body: JSON.stringify({ active: false }),
          });
          await loadCandidates();
        } catch (err) {
          showAlert(err.message, 'danger');
          button.disabled = false;
        }
      });
      tr.lastElementChild.append(button);
    }
    body.append(tr);
  });
}

document.addEventListener('DOMContentLoaded', async () => {
  const formCard = document.getElementById('candidate-form');
  if (authUser && authUser.role === 'commissioner_delegate') {
    formCard.hidden = false;
  }
  try {
    await loadCandidates();
  } catch (err) {
    showAlert(err.message, 'danger');
  }

  const form = document.getElementById('add-candidate');
  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    const button = form.querySelector('button');
    button.disabled = true;
    try {
      await apiRequest('/candidates', {
        method: 'POST',
        body: JSON.stringify({
          chamber: form.chamber.value,
          name: form.name.value.trim(),
          party: form.party.value.trim(),
          ballot_order: Number(form.ballot_order.value),
        }),
      });
      form.reset();
      form.ballot_order.value = '1';
      showAlert('Candidate saved.', 'success');
      await loadCandidates();
    } catch (err) {
      showAlert(err.message, 'danger');
    } finally {
      button.disabled = false;
    }
  });
});
