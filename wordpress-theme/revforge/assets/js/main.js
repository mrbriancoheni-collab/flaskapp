(function() {
  'use strict';

  // Nav scroll effect
  const header = document.getElementById('site-header');
  if (header) {
    window.addEventListener('scroll', function() {
      header.classList.toggle('scrolled', window.scrollY > 10);
    }, { passive: true });
  }

  // Mobile hamburger
  const hamburger = document.getElementById('hamburger');
  const mobileNav = document.getElementById('mobile-nav');
  if (hamburger && mobileNav) {
    hamburger.addEventListener('click', function() {
      const open = mobileNav.classList.toggle('open');
      hamburger.classList.toggle('active', open);
      hamburger.setAttribute('aria-expanded', open);
      mobileNav.setAttribute('aria-hidden', !open);
      document.body.style.overflow = open ? 'hidden' : '';
    });
  }

  // Pricing toggle
  const monthlyBtn = document.getElementById('pricing-monthly');
  const annualBtn  = document.getElementById('pricing-annual');
  const saveBadges = document.querySelectorAll('.save-badge');
  const prices     = document.querySelectorAll('[data-monthly]');

  function setPricing(mode) {
    prices.forEach(function(el) {
      el.textContent = mode === 'annual' ? el.dataset.annual : el.dataset.monthly;
    });
    saveBadges.forEach(function(b) { b.classList.toggle('visible', mode === 'annual'); });
    if (monthlyBtn) monthlyBtn.classList.toggle('active', mode === 'monthly');
    if (annualBtn)  annualBtn.classList.toggle('active', mode === 'annual');
  }

  if (monthlyBtn) monthlyBtn.addEventListener('click', function() { setPricing('monthly'); });
  if (annualBtn)  annualBtn.addEventListener('click', function() { setPricing('annual'); });

  // Smooth scroll
  document.querySelectorAll('a[href^="#"]').forEach(function(a) {
    a.addEventListener('click', function(e) {
      const id = a.getAttribute('href').slice(1);
      const el = document.getElementById(id);
      if (el) {
        e.preventDefault();
        el.scrollIntoView({ behavior: 'smooth', block: 'start' });
      }
    });
  });

})();
