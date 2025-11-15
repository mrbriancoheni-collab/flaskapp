/**
 * Tutorial Popups - Pendo-style Interactive Onboarding System
 *
 * Usage:
 *   <script src="/static/js/tutorial-popups.js"></script>
 *   <script nonce="{{csp_nonce()}}">
 *     TutorialPopups.init();
 *   </script>
 */

(function(window) {
  'use strict';

  const TutorialPopups = {
    popups: [],
    currentIndex: 0,
    initialized: false,
    activePopup: null,

    /**
     * Initialize the tutorial popup system
     */
    init: function() {
      if (this.initialized) return;
      this.initialized = true;

      // Get current page path
      const pagePath = window.location.pathname;

      // Fetch popups for this page
      fetch(`/admin/api/tutorials/for-page?page_path=${encodeURIComponent(pagePath)}`)
        .then(response => response.json())
        .then(data => {
          if (Array.isArray(data) && data.length > 0) {
            this.popups = data;
            this.showNext();
          }
        })
        .catch(error => {
          console.error('Failed to load tutorial popups:', error);
        });

      // Inject CSS
      this.injectStyles();
    },

    /**
     * Show the next popup in the sequence
     */
    showNext: function() {
      if (this.currentIndex >= this.popups.length) {
        return; // No more popups
      }

      const popup = this.popups[this.currentIndex];

      // Handle trigger type
      if (popup.trigger_type === 'page_load') {
        // Show immediately (or after a small delay for UX)
        setTimeout(() => this.showPopup(popup), 300);
      } else if (popup.trigger_type === 'delay') {
        const delay = parseInt(popup.trigger_value) || 2000;
        setTimeout(() => this.showPopup(popup), delay);
      } else if (popup.trigger_type === 'click') {
        this.attachClickTrigger(popup);
      } else if (popup.trigger_type === 'hover') {
        this.attachHoverTrigger(popup);
      } else if (popup.trigger_type === 'scroll') {
        this.attachScrollTrigger(popup);
      }
    },

    /**
     * Display a popup
     */
    showPopup: function(popup) {
      // Track view
      this.trackView(popup.id);

      // Create popup element
      const popupEl = this.createPopupElement(popup);
      document.body.appendChild(popupEl);

      this.activePopup = { popup, element: popupEl };

      // Position the popup
      this.positionPopup(popupEl, popup);

      // Auto-dismiss if configured
      if (popup.auto_dismiss_seconds) {
        setTimeout(() => {
          this.dismissPopup('auto_dismiss');
        }, popup.auto_dismiss_seconds * 1000);
      }

      // Animate in
      setTimeout(() => {
        popupEl.classList.add('tutorial-popup-visible');
      }, 10);
    },

    /**
     * Create popup DOM element
     */
    createPopupElement: function(popup) {
      const container = document.createElement('div');
      container.className = `tutorial-popup tutorial-popup-${popup.theme}`;
      container.dataset.popupId = popup.id;
      container.style.width = popup.width;

      // Arrow (for positioned popups)
      const arrow = document.createElement('div');
      arrow.className = `tutorial-popup-arrow tutorial-popup-arrow-${popup.position}`;

      // Header
      const header = document.createElement('div');
      header.className = 'tutorial-popup-header';

      const title = document.createElement('h3');
      title.className = 'tutorial-popup-title';
      title.textContent = popup.title;
      header.appendChild(title);

      // Close button (if dismissible)
      if (popup.dismissible) {
        const closeBtn = document.createElement('button');
        closeBtn.className = 'tutorial-popup-close';
        closeBtn.innerHTML = '&times;';
        closeBtn.onclick = () => this.dismissPopup('close_button');
        header.appendChild(closeBtn);
      }

      // Content
      const content = document.createElement('div');
      content.className = 'tutorial-popup-content';
      content.innerHTML = popup.content;

      // CTA button
      let footer = null;
      if (popup.cta_text) {
        footer = document.createElement('div');
        footer.className = 'tutorial-popup-footer';

        const ctaBtn = document.createElement('button');
        ctaBtn.className = 'tutorial-popup-cta';
        ctaBtn.textContent = popup.cta_text;
        ctaBtn.onclick = () => {
          if (popup.cta_link) {
            window.location.href = popup.cta_link;
          }
          this.dismissPopup('cta_click');
        };
        footer.appendChild(ctaBtn);
      }

      // Assemble
      container.appendChild(arrow);
      container.appendChild(header);
      container.appendChild(content);
      if (footer) {
        container.appendChild(footer);
      }

      return container;
    },

    /**
     * Position the popup relative to target or center
     */
    positionPopup: function(popupEl, popup) {
      if (!popup.target_selector || popup.position === 'center') {
        // Center modal
        popupEl.classList.add('tutorial-popup-modal');

        // Add backdrop
        const backdrop = document.createElement('div');
        backdrop.className = 'tutorial-popup-backdrop';
        if (popup.dismissible) {
          backdrop.onclick = () => this.dismissPopup('backdrop_click');
        }
        document.body.appendChild(backdrop);

        setTimeout(() => backdrop.classList.add('tutorial-popup-backdrop-visible'), 10);
      } else {
        // Position relative to target element
        const target = document.querySelector(popup.target_selector);

        if (!target) {
          console.warn(`Target element not found: ${popup.target_selector}`);
          // Fallback to modal
          popupEl.classList.add('tutorial-popup-modal');
          return;
        }

        const targetRect = target.getBoundingClientRect();
        const popupRect = popupEl.getBoundingClientRect();

        let top, left;

        switch (popup.position) {
          case 'top':
            top = targetRect.top - popupRect.height - 12;
            left = targetRect.left + (targetRect.width / 2) - (popupRect.width / 2);
            break;
          case 'bottom':
            top = targetRect.bottom + 12;
            left = targetRect.left + (targetRect.width / 2) - (popupRect.width / 2);
            break;
          case 'left':
            top = targetRect.top + (targetRect.height / 2) - (popupRect.height / 2);
            left = targetRect.left - popupRect.width - 12;
            break;
          case 'right':
            top = targetRect.top + (targetRect.height / 2) - (popupRect.height / 2);
            left = targetRect.right + 12;
            break;
          default:
            // Center as fallback
            popupEl.classList.add('tutorial-popup-modal');
            return;
        }

        // Keep popup within viewport
        const scrollY = window.pageYOffset || document.documentElement.scrollTop;
        const scrollX = window.pageXOffset || document.documentElement.scrollLeft;

        top = Math.max(10, Math.min(top, window.innerHeight - popupRect.height - 10));
        left = Math.max(10, Math.min(left, window.innerWidth - popupRect.width - 10));

        popupEl.style.position = 'absolute';
        popupEl.style.top = (top + scrollY) + 'px';
        popupEl.style.left = (left + scrollX) + 'px';

        // Highlight target
        target.classList.add('tutorial-popup-highlight');
      }
    },

    /**
     * Dismiss the current popup
     */
    dismissPopup: function(action) {
      if (!this.activePopup) return;

      const { popup, element } = this.activePopup;

      // Track dismissal
      this.trackDismiss(popup.id, action);

      // Remove highlight from target
      if (popup.target_selector) {
        const target = document.querySelector(popup.target_selector);
        if (target) {
          target.classList.remove('tutorial-popup-highlight');
        }
      }

      // Animate out
      element.classList.remove('tutorial-popup-visible');

      // Remove backdrop if exists
      const backdrop = document.querySelector('.tutorial-popup-backdrop');
      if (backdrop) {
        backdrop.classList.remove('tutorial-popup-backdrop-visible');
        setTimeout(() => backdrop.remove(), 300);
      }

      // Remove element
      setTimeout(() => {
        element.remove();
        this.activePopup = null;

        // Show next popup in sequence
        this.currentIndex++;
        this.showNext();
      }, 300);
    },

    /**
     * Track popup view
     */
    trackView: function(popupId) {
      fetch(`/admin/api/tutorials/${popupId}/track-view`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        }
      }).catch(error => {
        console.error('Failed to track popup view:', error);
      });
    },

    /**
     * Track popup dismissal
     */
    trackDismiss: function(popupId, action) {
      fetch(`/admin/api/tutorials/${popupId}/track-dismiss`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ action })
      }).catch(error => {
        console.error('Failed to track popup dismiss:', error);
      });
    },

    /**
     * Attach click trigger
     */
    attachClickTrigger: function(popup) {
      if (!popup.trigger_value) return;

      const target = document.querySelector(popup.trigger_value);
      if (target) {
        target.addEventListener('click', () => this.showPopup(popup), { once: true });
      }
    },

    /**
     * Attach hover trigger
     */
    attachHoverTrigger: function(popup) {
      if (!popup.trigger_value) return;

      const target = document.querySelector(popup.trigger_value);
      if (target) {
        target.addEventListener('mouseenter', () => this.showPopup(popup), { once: true });
      }
    },

    /**
     * Attach scroll trigger
     */
    attachScrollTrigger: function(popup) {
      const scrollThreshold = parseInt(popup.trigger_value) || 50; // percentage
      let triggered = false;

      const checkScroll = () => {
        if (triggered) return;

        const scrollPercent = (window.pageYOffset / (document.documentElement.scrollHeight - window.innerHeight)) * 100;

        if (scrollPercent >= scrollThreshold) {
          triggered = true;
          this.showPopup(popup);
          window.removeEventListener('scroll', checkScroll);
        }
      };

      window.addEventListener('scroll', checkScroll);
    },

    /**
     * Inject CSS styles
     */
    injectStyles: function() {
      if (document.getElementById('tutorial-popups-styles')) return;

      const style = document.createElement('style');
      style.id = 'tutorial-popups-styles';
      style.textContent = `
        .tutorial-popup {
          position: fixed;
          background: white;
          border-radius: 12px;
          box-shadow: 0 10px 40px rgba(0, 0, 0, 0.15), 0 0 0 1px rgba(0, 0, 0, 0.05);
          z-index: 10000;
          opacity: 0;
          transform: translateY(-10px) scale(0.95);
          transition: opacity 0.3s ease, transform 0.3s ease;
          max-width: 90vw;
        }

        .tutorial-popup-visible {
          opacity: 1;
          transform: translateY(0) scale(1);
        }

        .tutorial-popup-modal {
          position: fixed !important;
          top: 50% !important;
          left: 50% !important;
          transform: translate(-50%, -50%) scale(0.95);
        }

        .tutorial-popup-modal.tutorial-popup-visible {
          transform: translate(-50%, -50%) scale(1);
        }

        .tutorial-popup-backdrop {
          position: fixed;
          top: 0;
          left: 0;
          right: 0;
          bottom: 0;
          background: rgba(0, 0, 0, 0.5);
          z-index: 9999;
          opacity: 0;
          transition: opacity 0.3s ease;
        }

        .tutorial-popup-backdrop-visible {
          opacity: 1;
        }

        .tutorial-popup-header {
          display: flex;
          align-items: center;
          justify-content: space-between;
          padding: 16px 20px;
          border-bottom: 1px solid #e5e7eb;
        }

        .tutorial-popup-title {
          font-size: 16px;
          font-weight: 600;
          color: #111827;
          margin: 0;
        }

        .tutorial-popup-close {
          background: none;
          border: none;
          font-size: 24px;
          color: #9ca3af;
          cursor: pointer;
          padding: 0;
          width: 28px;
          height: 28px;
          display: flex;
          align-items: center;
          justify-content: center;
          border-radius: 6px;
          transition: background-color 0.2s, color 0.2s;
        }

        .tutorial-popup-close:hover {
          background-color: #f3f4f6;
          color: #111827;
        }

        .tutorial-popup-content {
          padding: 20px;
          color: #374151;
          font-size: 14px;
          line-height: 1.6;
        }

        .tutorial-popup-content p {
          margin: 0 0 12px 0;
        }

        .tutorial-popup-content p:last-child {
          margin-bottom: 0;
        }

        .tutorial-popup-content ul {
          margin: 8px 0;
          padding-left: 20px;
        }

        .tutorial-popup-content strong {
          color: #111827;
          font-weight: 600;
        }

        .tutorial-popup-footer {
          padding: 16px 20px;
          border-top: 1px solid #e5e7eb;
          display: flex;
          justify-content: flex-end;
        }

        .tutorial-popup-cta {
          background: #4f46e5;
          color: white;
          border: none;
          padding: 10px 20px;
          border-radius: 8px;
          font-size: 14px;
          font-weight: 500;
          cursor: pointer;
          transition: background-color 0.2s;
        }

        .tutorial-popup-cta:hover {
          background: #4338ca;
        }

        .tutorial-popup-arrow {
          position: absolute;
          width: 12px;
          height: 12px;
          background: white;
          transform: rotate(45deg);
          box-shadow: -2px -2px 5px rgba(0, 0, 0, 0.05);
        }

        .tutorial-popup-arrow-top {
          bottom: -6px;
          left: 50%;
          margin-left: -6px;
        }

        .tutorial-popup-arrow-bottom {
          top: -6px;
          left: 50%;
          margin-left: -6px;
        }

        .tutorial-popup-arrow-left {
          right: -6px;
          top: 50%;
          margin-top: -6px;
        }

        .tutorial-popup-arrow-right {
          left: -6px;
          top: 50%;
          margin-top: -6px;
        }

        /* Target highlighting */
        .tutorial-popup-highlight {
          position: relative;
          box-shadow: 0 0 0 4px rgba(79, 70, 229, 0.3);
          border-radius: 6px;
          z-index: 9998;
        }

        /* Theme variations */
        .tutorial-popup-success .tutorial-popup-header {
          background: linear-gradient(135deg, #10b981 0%, #059669 100%);
          color: white;
          border-bottom: none;
        }

        .tutorial-popup-success .tutorial-popup-title {
          color: white;
        }

        .tutorial-popup-success .tutorial-popup-close {
          color: rgba(255, 255, 255, 0.7);
        }

        .tutorial-popup-success .tutorial-popup-close:hover {
          color: white;
          background: rgba(255, 255, 255, 0.2);
        }

        .tutorial-popup-success .tutorial-popup-cta {
          background: #10b981;
        }

        .tutorial-popup-success .tutorial-popup-cta:hover {
          background: #059669;
        }

        .tutorial-popup-primary .tutorial-popup-header {
          background: linear-gradient(135deg, #4f46e5 0%, #4338ca 100%);
          color: white;
          border-bottom: none;
        }

        .tutorial-popup-primary .tutorial-popup-title {
          color: white;
        }

        .tutorial-popup-primary .tutorial-popup-close {
          color: rgba(255, 255, 255, 0.7);
        }

        .tutorial-popup-primary .tutorial-popup-close:hover {
          color: white;
          background: rgba(255, 255, 255, 0.2);
        }

        .tutorial-popup-info .tutorial-popup-header {
          background: linear-gradient(135deg, #3b82f6 0%, #2563eb 100%);
          color: white;
          border-bottom: none;
        }

        .tutorial-popup-info .tutorial-popup-title {
          color: white;
        }

        .tutorial-popup-info .tutorial-popup-close {
          color: rgba(255, 255, 255, 0.7);
        }

        .tutorial-popup-info .tutorial-popup-close:hover {
          color: white;
          background: rgba(255, 255, 255, 0.2);
        }

        .tutorial-popup-info .tutorial-popup-cta {
          background: #3b82f6;
        }

        .tutorial-popup-info .tutorial-popup-cta:hover {
          background: #2563eb;
        }

        .tutorial-popup-warning .tutorial-popup-header {
          background: linear-gradient(135deg, #f59e0b 0%, #d97706 100%);
          color: white;
          border-bottom: none;
        }

        .tutorial-popup-warning .tutorial-popup-title {
          color: white;
        }

        .tutorial-popup-warning .tutorial-popup-close {
          color: rgba(255, 255, 255, 0.7);
        }

        .tutorial-popup-warning .tutorial-popup-close:hover {
          color: white;
          background: rgba(255, 255, 255, 0.2);
        }

        .tutorial-popup-warning .tutorial-popup-cta {
          background: #f59e0b;
        }

        .tutorial-popup-warning .tutorial-popup-cta:hover {
          background: #d97706;
        }
      `;

      document.head.appendChild(style);
    }
  };

  // Export to global scope
  window.TutorialPopups = TutorialPopups;

})(window);
