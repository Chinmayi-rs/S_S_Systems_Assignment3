document.addEventListener('DOMContentLoaded', async () => {
  const lede = document.getElementById('election-lede');
  const preview = document.getElementById('candidate-preview');
  try {
    const electionData = await apiRequest('/elections/current');
    const election = electionData.election;
    lede.textContent = election.name + ' ' + election.year
      + ' · division of ' + election.division
      + ' · ' + (election.status === 'open' ? 'polls are open' : 'polls are closed') + '.';
  } catch (err) {
    lede.textContent = 'No election is loaded.';
  }

  try {
    const data = await apiRequest('/candidates');
    const rows = (data.candidates || []).filter((row) => row.active);
    if (!rows.length) {
      preview.textContent = 'No candidates yet.';
      return;
    }
    const house = rows.filter((row) => row.chamber === 'house');
    const senate = rows.filter((row) => row.chamber === 'senate');
    const list = document.createElement('div');
    list.className = 'grid grid-2';
    list.innerHTML =
      '<div><h3>House</h3><ol>' + house.map((row) =>
        '<li>' + escapeHtml(row.name) + ' <span class="party">' + escapeHtml(row.party) + '</span></li>'
      ).join('') + '</ol></div>' +
      '<div><h3>Senate groups</h3><ol>' + senate.map((row) =>
        '<li>' + escapeHtml(row.name) + '</li>'
      ).join('') + '</ol></div>';
    preview.replaceChildren(list);
  } catch (err) {
    preview.textContent = 'Could not load candidates.';
  }
});

