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

// ─── CARD GLOW (mouse-follow spotlight) ────────────
// Applies to pricing cards (.pkg) and the Review Axis /
// Standardized Testing cards (.rev-card). Sets --mx/--my to the
// cursor's position inside the card, and toggles --glow-alpha so
// the spotlight only shows while hovering. See style.css for the
// actual radial-gradient rule these variables feed.
(function () {
  const cards = document.querySelectorAll('.pkg, .rev-card');
  cards.forEach(card => {
    card.addEventListener('mousemove', e => {
      const rect = card.getBoundingClientRect();
      const x = e.clientX - rect.left;
      const y = e.clientY - rect.top;
      card.style.setProperty('--mx', `${x}px`);
      card.style.setProperty('--my', `${y}px`);
    });
    card.addEventListener('mouseenter', () => {
      card.style.setProperty('--glow-alpha', '0.16');
    });
    card.addEventListener('mouseleave', () => {
      card.style.setProperty('--glow-alpha', '0');
    });
  });
})();
