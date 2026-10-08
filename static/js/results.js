function resultBlock(title, rows) {
  const max = Math.max(1, ...rows.map((row) => row.votes || 0));
  const section = document.createElement('section');
  const heading = document.createElement('h2');
  heading.textContent = title;
  section.append(heading);
  if (!rows.length) {
    const empty = document.createElement('p');
    empty.textContent = 'Nothing on this paper.';
    section.append(empty);
    return section;
  }
  rows
    .slice()
    .sort((a, b) => b.votes - a.votes || a.ballot_order - b.ballot_order)
    .forEach((row) => {
      const item = document.createElement('div');
      item.style.marginBottom = '0.8rem';
      const pct = Math.round((row.votes / max) * 100);
      item.innerHTML = '<strong>' + escapeHtml(row.name) + '</strong>'
        + ' <span class="party">' + escapeHtml(row.party) + ' · ' + row.votes + '</span>'
        + '<div class="bar"><span style="width:' + pct + '%"></span></div>';
      section.append(item);
    });
  return section;
}

document.addEventListener('DOMContentLoaded', async () => {
  const root = document.getElementById('results-body');
  try {
    const data = await apiRequest('/results');
    root.replaceChildren();
    const note = document.createElement('p');
    note.textContent = data.preview
      ? 'Preview only. Polls are still open, so this page is not public.'
      : 'Published count. Ballots accepted: ' + data.total_ballots + '.';
    root.append(note, resultBlock('House, first preference', data.house || []), resultBlock('Senate, above the line', data.senate || []));
  } catch (err) {
    root.textContent = err.message;
  }
});
