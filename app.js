function escapeHtml(str){
  return String(str).replace(/[&<>"']/g, c => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }[c]));
}

function renderDate(){
  const el = document.getElementById('todayDate');
  el.textContent = new Date().toLocaleDateString(undefined, {
    weekday: 'long', year: 'numeric', month: 'long', day: 'numeric'
  });
}

function playIcon(){
  return `<svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
    <path d="M8 5v14l11-7L8 5z" fill="#F3ECE0"/>
  </svg>`;
}

function watchIcon(){
  return `<svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
    <path d="M8 5v14l11-7L8 5z" fill="currentColor"/>
  </svg>`;
}

function render(entry){
  const stage = document.getElementById('stage');
  const v = entry.verse || {};
  const vid = entry.video || {};

  stage.innerHTML = `
    <section class="card verse-card">
      <div class="ref-row">
        <h2>${escapeHtml(v.reference || 'Verse of the Day')}</h2>
        <span class="translation-chip">${escapeHtml(v.translation || 'NLT')}</span>
      </div>
      <blockquote>${escapeHtml(v.text || '')}</blockquote>
    </section>

    <section class="card">
      <p class="section-label">Today's Video</p>
      <a class="video-thumb" href="${escapeHtml(vid.url || '#')}" target="_blank" rel="noopener noreferrer" aria-label="Watch: ${escapeHtml(vid.title || '')}">
        <img src="${escapeHtml(vid.thumbnail || 'https://placehold.co/640x360/2A241D/B7A996?text=Video')}" alt="${escapeHtml(vid.title || 'Video thumbnail')}" loading="lazy">
        <span class="play-badge"><span class="play-circle">${playIcon()}</span></span>
        ${vid.duration ? `<span class="duration-badge mono">${escapeHtml(vid.duration)}</span>` : ''}
      </a>
      <div class="video-meta">
        <h3>${escapeHtml(vid.title || 'Video coming soon')}</h3>
        <p class="channel">${escapeHtml(vid.channel || '')}</p>
        <a class="btn" href="${escapeHtml(vid.url || '#')}" target="_blank" rel="noopener noreferrer">
          Watch video ${watchIcon()}
        </a>
      </div>
    </section>

    ${entry.reflection ? `
    <section class="card reflection-card">
      <p class="section-label">Today's Reflection</p>
      <p>${escapeHtml(entry.reflection)}</p>
    </section>` : ''}
  `;
}

async function init(){
  renderDate();
  try {
    const res = await fetch('data.json', { cache: 'no-store' });
    if(!res.ok) throw new Error('HTTP ' + res.status);
    const entry = await res.json();
    render(entry);
    const gen = document.getElementById('generatedAt');
    if(gen && entry.generatedAt){
      gen.textContent = 'Updated ' + new Date(entry.generatedAt).toLocaleString();
    }
  } catch (err) {
    document.getElementById('stage').innerHTML =
      `<div class="load-error">
        <p>Today's verse couldn't be loaded (${escapeHtml(err.message)}).</p>
        <p>Run the daily pipeline, or check that data.json exists.</p>
      </div>`;
  }
}

document.addEventListener('DOMContentLoaded', init);
