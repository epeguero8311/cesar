const io = new IntersectionObserver(
  entries => entries.forEach(e => { if (e.isIntersecting) e.target.classList.add('in') }),
  { threshold: 0.08, rootMargin: '0px 0px -36px 0px' }
);
document.querySelectorAll('.reveal').forEach(el => io.observe(el));
// ─── NAV BURGER (mobile) ───────────────────────────
(function () {
  const burger = document.getElementById('navBurger');
  const links = document.getElementById('navLinks');
  const overlay = document.getElementById('navOverlay');
  if (!burger || !links) return;
  function closeMenu() {
    burger.classList.remove('active');
    links.classList.remove('active');
    if (overlay) overlay.classList.remove('active');
    burger.setAttribute('aria-expanded', 'false');
  }
  function toggleMenu() {
    const isOpen = links.classList.toggle('active');
    burger.classList.toggle('active', isOpen);
    if (overlay) overlay.classList.toggle('active', isOpen);
    burger.setAttribute('aria-expanded', String(isOpen));
  }
  burger.addEventListener('click', toggleMenu);
  if (overlay) overlay.addEventListener('click', closeMenu);
  links.querySelectorAll('a').forEach(a => a.addEventListener('click', closeMenu));
  document.addEventListener('keydown', e => { if (e.key === 'Escape') closeMenu(); });
})();
