const io = new IntersectionObserver(
  entries => entries.forEach(e => { if (e.isIntersecting) e.target.classList.add('in') }),
  { threshold: 0.08, rootMargin: '0px 0px -36px 0px' }
);
document.querySelectorAll('.reveal').forEach(el => io.observe(el));