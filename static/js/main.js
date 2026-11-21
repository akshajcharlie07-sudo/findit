// FindIt – interactive behaviour
(function () {
  'use strict';

  // Navbar shadow on scroll
  var nav = document.getElementById('mainNav');
  function onScroll() { if (nav) nav.classList.toggle('scrolled', window.scrollY > 10); }
  window.addEventListener('scroll', onScroll, { passive: true }); onScroll();

  // Reveal-on-scroll animation
  function setupReveal(root) {
    var els = (root || document).querySelectorAll('.reveal:not(.visible)');
    if (!('IntersectionObserver' in window)) { els.forEach(function (e) { e.classList.add('visible'); }); return; }
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (en) { if (en.isIntersecting) { en.target.classList.add('visible'); io.unobserve(en.target); } });
    }, { threshold: 0.1 });
    els.forEach(function (e) { io.observe(e); });
  }
  setupReveal();

  // Animated counters (values come from the database; text is the no-JS fallback)
  document.querySelectorAll('[data-count]').forEach(function (el) {
    var target = parseInt(el.dataset.count, 10) || 0, start = null;
    if (target === 0) return;
    function step(ts) {
      if (!start) start = ts;
      var p = Math.min((ts - start) / 900, 1);
      el.textContent = Math.round(target * (1 - Math.pow(1 - p, 3)));
      if (p < 1) requestAnimationFrame(step);
    }
    el.textContent = '0'; requestAnimationFrame(step);
  });

  // Show / hide password
  document.querySelectorAll('.toggle-pass').forEach(function (btn) {
    btn.addEventListener('click', function () {
      var input = btn.parentElement.querySelector('input');
      var show = input.type === 'password';
      input.type = show ? 'text' : 'password';
      btn.innerHTML = '<i class="bi bi-eye' + (show ? '-slash' : '') + '"></i>';
    });
  });

  // Image upload preview + client-side size check
  var fileInput = document.getElementById('imageInput');
  if (fileInput) {
    fileInput.addEventListener('change', function () {
      var f = fileInput.files[0], text = document.getElementById('uploadText'), img = document.getElementById('imagePreview');
      if (!f) { img.hidden = true; return; }
      if (f.size > 4 * 1024 * 1024) { alert('Image must be smaller than 4 MB.'); fileInput.value = ''; img.hidden = true; return; }
      text.textContent = f.name;
      img.src = URL.createObjectURL(f); img.hidden = false;
    });
  }

  // Live search & filtering on Browse page (talks to Flask, no page reload)
  var form = document.getElementById('filterForm'), area = document.getElementById('resultsArea');
  if (form && area) {
    var timer = null, controller = null;
    function load() {
      var params = new URLSearchParams(new FormData(form));
      for (var k of Array.from(params.keys())) { if (!params.get(k)) params.delete(k); }
      var qs = params.toString();
      history.replaceState(null, '', location.pathname + (qs ? '?' + qs : ''));
      params.set('partial', '1');
      if (controller) controller.abort();
      controller = new AbortController();
      area.classList.add('loading');
      fetch(location.pathname + '?' + params.toString(), { signal: controller.signal, headers: { 'X-Requested-With': 'fetch' } })
        .then(function (r) { if (!r.ok) throw new Error(r.status); return r.text(); })
        .then(function (html) { area.innerHTML = html; area.classList.remove('loading'); setupReveal(area); bindPager(); })
        .catch(function (e) { if (e.name !== 'AbortError') { area.classList.remove('loading'); form.submit(); } });
    }
    function bindPager() {
      area.querySelectorAll('.pagination a').forEach(function (a) {
        a.addEventListener('click', function (ev) {
          ev.preventDefault();
          var url = new URL(a.href), page = url.searchParams.get('page') || '1';
          var params = new URLSearchParams(new FormData(form)); params.set('page', page);
          for (var k of Array.from(params.keys())) { if (!params.get(k)) params.delete(k); }
          history.replaceState(null, '', location.pathname + '?' + params.toString());
          params.set('partial', '1');
          area.classList.add('loading');
          fetch(location.pathname + '?' + params.toString()).then(function (r) { return r.text(); })
            .then(function (html) { area.innerHTML = html; area.classList.remove('loading'); setupReveal(area); bindPager(); window.scrollTo({ top: 0, behavior: 'smooth' }); });
        });
      });
    }
    form.addEventListener('submit', function (e) { e.preventDefault(); load(); });
    form.querySelectorAll('input[type=text]').forEach(function (i) { i.addEventListener('input', function () { clearTimeout(timer); timer = setTimeout(load, 300); }); });
    form.querySelectorAll('select').forEach(function (s) { s.addEventListener('change', load); });
    bindPager();
  }

  // Auto-dismiss flash messages
  document.querySelectorAll('.flash-wrap .alert-success, .flash-wrap .alert-info').forEach(function (a) {
    setTimeout(function () { if (window.bootstrap) bootstrap.Alert.getOrCreateInstance(a).close(); }, 5000);
  });
})();
