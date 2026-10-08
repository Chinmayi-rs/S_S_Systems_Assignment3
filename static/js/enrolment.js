function voterForm(user) {
  const wrap = document.createElement('div');
  wrap.innerHTML = '<h2>' + escapeHtml(user.full_name) + '</h2>'
    + '<p>Eligible: ' + (user.eligible ? 'yes' : 'not yet')
    + ' · Enrolled: ' + (user.enrolled ? 'yes' : 'no')
    + ' · Division: ' + escapeHtml(user.division || '—') + '</p>';
  const form = document.createElement('form');
  form.className = 'stack';
  form.innerHTML = '<div><label for="address">Residential address</label>'
    + '<input id="address" name="address" required value="' + escapeHtml(user.address || '') + '"></div>'
    + '<div><label for="division">Division</label>'
    + '<input id="division" name="division" required value="' + escapeHtml(user.division || '') + '"></div>'
    + '<button class="btn" type="submit">Save details</button>';
  if (user.has_voted) {
    form.querySelector('button').disabled = true;
    wrap.append(form);
    const note = document.createElement('p');
    note.textContent = 'Details are locked after a ballot is accepted.';
    wrap.append(note);
    return wrap;
  }
  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    try {
      const data = await apiRequest('/enrolment/me', {
        method: 'PATCH',
        body: JSON.stringify({
          address: form.address.value.trim(),
          division: form.division.value.trim(),
        }),
      });
      storeSession(authToken, data.enrolment);
      showAlert('Enrolment details saved.', 'success');
    } catch (err) {
      showAlert(err.message, 'danger');
    }
  });
  wrap.append(form);
  return wrap;
}

function officerTable(voters) {
  const wrap = document.createElement('div');
  wrap.className = 'table-wrap';
  const table = document.createElement('table');
  table.innerHTML = '<thead><tr><th>Name</th><th>Division</th><th>Eligible</th><th></th></tr></thead>';
  const body = document.createElement('tbody');
  voters.forEach((voter) => {
    const tr = document.createElement('tr');
    tr.innerHTML = '<td>' + escapeHtml(voter.full_name) + '<br><span class="party">'
      + escapeHtml(voter.username) + '</span></td><td>' + escapeHtml(voter.division || '—')
      + '</td><td>' + (voter.eligible ? 'Yes' : 'No') + '</td><td></td>';
    if (!voter.eligible) {
      const button = document.createElement('button');
      button.className = 'btn';
      button.type = 'button';
      button.textContent = 'Verify';
      button.addEventListener('click', async () => {
        button.disabled = true;
        try {
          await apiRequest('/enrolment/voters/' + voter.id + '/verify', {
            method: 'POST',
            body: JSON.stringify({
              division: voter.division || 'Melbourne',
              eligible: true,
            }),
          });
          showAlert(voter.full_name + ' is now eligible.', 'success');
          await loadEnrolment();
        } catch (err) {
          showAlert(err.message, 'danger');
          button.disabled = false;
        }
      });
      tr.lastElementChild.append(button);
    }
    body.append(tr);
  });
  table.append(body);
  wrap.append(table);
  return wrap;
}

async function loadEnrolment() {
  const root = document.getElementById('enrolment-body');
  const profile = await apiRequest('/auth/profile');
  storeSession(authToken, profile.user);
  const user = profile.user;
  root.replaceChildren();
  if (user.role === 'enrolment_officer') {
    const listed = await apiRequest('/enrolment/voters');
    const heading = document.createElement('h2');
    heading.textContent = 'Voters on the roll';
    root.append(heading, officerTable(listed.voters || []));
    return;
  }
  if (user.role === 'voter') {
    root.append(voterForm(user));
    return;
  }
  root.innerHTML = '<p>This page is for voters and enrolment officers.</p>';
}

document.addEventListener('DOMContentLoaded', async () => {
  if (!authToken) {
    window.location.href = '/login';
    return;
  }
  try {
    await loadEnrolment();
  } catch (err) {
    document.getElementById('enrolment-body').textContent = err.message;
    if (err.status === 401) window.location.href = '/login';
  }
});
