(() => {
  'use strict';
  const root = document.documentElement;
  const messageNode = document.getElementById('site-messages');
  const text = messageNode ? JSON.parse(messageNode.textContent) : {};
  const localeLinks = [...document.querySelectorAll('[data-language]')];
  const preferenceKey = 'ultralight-py.showcase.language';
  function remember(locale) { try { localStorage.setItem(preferenceKey, locale); } catch (_) {} }
  if (root.dataset.entry === 'true') {
    let preferred;
    try { preferred = localStorage.getItem(preferenceKey); } catch (_) {}
    if (!['zh-CN', 'en'].includes(preferred)) preferred = navigator.language.toLowerCase().startsWith('zh') ? 'zh-CN' : 'en';
    const target = localeLinks.find(link => link.dataset.language === preferred);
    if (target) { const url = new URL(target.href); url.hash = location.hash; url.search = location.search; location.replace(url.href); return; }
  }
  localeLinks.forEach(link => link.addEventListener('click', () => {
    remember(link.dataset.language);
    const url = new URL(link.href); url.hash = location.hash; url.search = location.search; link.href = url.href;
  }));

  const reduced = matchMedia('(prefers-reduced-motion: reduce)');
  let allWanted = !reduced.matches;
  const states = [...document.querySelectorAll('[data-animation]')].map(figure => ({
    figure, image: figure.querySelector('.animated-image'), button: figure.querySelector('.motion-toggle'),
    label: figure.querySelector('.motion-label'), symbol: figure.querySelector('.motion-symbol'),
    status: figure.querySelector('.motion-state'), visible: false, manualPause: false, playing: false, generation: 0
  }));
  function stop(state) {
    state.generation++;
    state.image.onload = state.image.onerror = null;
    state.image.src = state.figure.dataset.poster;
    state.playing = false;
    state.button.setAttribute('aria-pressed', 'false');
    state.label.textContent = text.play; state.symbol.textContent = '▶'; state.status.textContent = text.paused;
    state.button.setAttribute('aria-label', `${text.play} — ${state.figure.dataset.title}`);
  }
  function apply(state) {
    const wanted = allWanted && !state.manualPause && state.visible && !document.hidden;
    if (!wanted) { if (state.playing) stop(state); return; }
    if (state.playing) return;
    state.playing = true;
    const generation = ++state.generation;
    state.button.setAttribute('aria-pressed', 'true');
    state.label.textContent = text.pause; state.symbol.textContent = 'Ⅱ'; state.status.textContent = text.loading;
    state.button.setAttribute('aria-label', `${text.pause} — ${state.figure.dataset.title}`);
    state.image.onload = () => { if (generation === state.generation) state.status.textContent = text.playing; };
    state.image.onerror = () => {
      if (generation !== state.generation) return;
      stop(state); state.manualPause = true; state.status.textContent = text.media_error;
    };
    state.image.src = state.figure.dataset.animation;
  }
  const allButton = document.querySelector('.all-motion');
  function updateAll() { if (allButton) allButton.textContent = allWanted ? text.all_pause : text.all_play; }
  states.forEach(state => {
    state.button.hidden = false;
    state.button.addEventListener('click', () => {
      if (state.playing) state.manualPause = true;
      else { if (!allWanted) states.forEach(other => { other.manualPause = true; }); state.manualPause = false; allWanted = true; }
      updateAll(); apply(state);
    });
    stop(state);
  });
  if (states.length && allButton) {
    allButton.hidden = false; updateAll();
    allButton.addEventListener('click', () => {
      allWanted = !allWanted;
      states.forEach(state => { state.manualPause = false; apply(state); }); updateAll();
    });
  }
  if ('IntersectionObserver' in window) {
    const observer = new IntersectionObserver(entries => entries.forEach(entry => {
      const state = states.find(item => item.figure === entry.target);
      state.visible = entry.isIntersecting; apply(state);
    }), { rootMargin: '0px' });
    states.forEach(state => observer.observe(state.figure));
  } else { states.forEach(state => { state.visible = true; apply(state); }); }
  document.addEventListener('visibilitychange', () => states.forEach(apply));
  const motionChanged = () => { allWanted = !reduced.matches; states.forEach(apply); updateAll(); };
  if (reduced.addEventListener) reduced.addEventListener('change', motionChanged);
  else if (reduced.addListener) reduced.addListener(motionChanged);

  const dialog = document.querySelector('.lightbox');
  let opener = null;
  if (dialog && typeof dialog.showModal === 'function') {
    const largeImage = dialog.querySelector('.lightbox-image');
    const close = () => dialog.close();
    document.querySelectorAll('[data-lightbox]').forEach(link => link.addEventListener('click', event => {
      if (event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
      event.preventDefault(); opener = link;
      largeImage.src = link.href; largeImage.alt = link.dataset.alt;
      dialog.querySelector('h2').textContent = link.dataset.title;
      dialog.querySelector('.original-image').href = link.href;
      dialog.showModal(); dialog.querySelector('.lightbox-close').focus();
    }));
    dialog.querySelector('.lightbox-close').addEventListener('click', close);
    dialog.addEventListener('click', event => {
      if (event.target !== dialog) return;
      const box = dialog.getBoundingClientRect();
      if (event.clientX < box.left || event.clientX > box.right || event.clientY < box.top || event.clientY > box.bottom) close();
    });
    dialog.addEventListener('close', () => { largeImage.removeAttribute('src'); if (opener) opener.focus(); });
  }
  const copyButton = document.querySelector('.copy-command');
  if (copyButton && navigator.clipboard && window.isSecureContext) {
    copyButton.hidden = false;
    copyButton.addEventListener('click', async () => {
      const status = document.querySelector('.copy-status');
      try { await navigator.clipboard.writeText(document.querySelector('.command code').textContent); status.textContent = text.copied; }
      catch (_) { status.textContent = text.copy_failed; }
    });
  }
})();
