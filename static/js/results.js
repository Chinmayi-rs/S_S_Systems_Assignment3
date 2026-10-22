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

function downloadText(filename, text) {
  const url = URL.createObjectURL(new Blob([text], { type: 'application/json' }));
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  document.body.append(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

// GR-13: the files a third party needs to check the result with scripts/verify_results.py
function signatureBox(data) {
  const sig = data.signature;
  const box = document.getElementById('signature-box');
  box.className = 'card sigbox';
  box.hidden = false;
  box.innerHTML = '<h2>Signed result</h2>'
    + '<p>Signed by key <span class="mono">' + escapeHtml(sig.key_fingerprint.slice(0, 16)) + '…</span> (' + escapeHtml(sig.algorithm) + '). '
    + 'Published ' + escapeHtml(data.publication.published_at) + '. Proposed by ' + escapeHtml(data.publication.proposed_by)
    + ', approved by ' + escapeHtml(data.publication.approved_by) + '.</p>'
    + '<p>SHA-256 of the result: <span class="mono">' + escapeHtml(sig.sha256) + '</span></p>'
    + '<p>Anyone can check this without trusting this server: download the three files and run '
    + '<code>python scripts/verify_results.py results.json results.sig.json results.pub.json</code>. '
    + 'Compare the key fingerprint with a copy you trust (the report, or the <code>results.key.registered</code> audit entry).</p>';

  const row = document.createElement('div');
  row.className = 'row';
  const mk = (label, secondary, handler) => {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = secondary ? 'btn secondary' : 'btn';
    button.textContent = label;
    button.addEventListener('click', handler);
    row.append(button);
    return button;
  };
  mk('Download result (JSON)', false, () => downloadText('results.json', data.signed_document));
  mk('Download signature', true, () => downloadText('results.sig.json', JSON.stringify({
    algorithm: sig.algorithm,
    signed_message_prefix: sig.signed_message_prefix,
    sha256: sig.sha256,
    signature: sig.value,
    key_fingerprint: sig.key_fingerprint,
  }, null, 2)));
  mk('Download public key', true, async () => {
    try {
      downloadText('results.pub.json', JSON.stringify(await apiRequest('/results/public-key'), null, 2));
    } catch (err) {
      showAlert(err.message, 'danger');
    }
  });

  const out = document.createElement('p');
  out.style.marginTop = '0.8rem';
  mk('Check signature on the server', true, async () => {
    out.textContent = 'Checking…';
    out.className = '';
    try {
      const result = await apiRequest('/results/verify');
      out.textContent = result.valid
        ? 'Signature is valid and the key matches the one recorded in the audit log.'
        : 'PROBLEM: ' + result.problems.join('; ');
      out.className = result.valid ? 'sig-ok' : 'sig-bad';
    } catch (err) {
      out.textContent = err.message;
      out.className = 'sig-bad';
    }
  });
  box.append(row, out);
}

document.addEventListener('DOMContentLoaded', async () => {
  const root = document.getElementById('results-body');
  try {
    const data = await apiRequest('/results');
    root.replaceChildren();
    const note = document.createElement('p');
    note.textContent = data.preview
      ? 'Preview only. These results are not published yet (two delegates must publish them), so this page is not public.'
      : 'Published count. Ballots accepted: ' + data.total_ballots + '.';
    root.append(note, resultBlock('House, first preference', data.house || []), resultBlock('Senate, above the line', data.senate || []));
    if (data.published && data.signature) signatureBox(data);
  } catch (err) {
    root.textContent = err.message;
  }
});
