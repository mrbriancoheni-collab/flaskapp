/**
 * Metric Tooltips System
 *
 * Provides inline help for Google Ads metrics and terms
 * Usage: Add data-tooltip="explanation" to any element
 */

(function(window) {
  'use strict';

  const MetricTooltips = {
    tooltipElement: null,
    currentTarget: null,
    hideTimeout: null,

    /**
     * Glossary of terms and their explanations
     */
    glossary: {
      'health_score': {
        title: 'Health Score',
        description: 'Overall account performance grade from 0-100. Combines multiple factors including quality score, wasted spend prevention, and optimization coverage.',
        tips: 'Aim for 80+ for excellent performance. Scores below 60 indicate urgent issues.'
      },
      'wasted_spend': {
        title: 'Wasted Spend Prevention',
        description: 'Percentage of your budget protected from waste through negative keywords, poor-performing keyword exclusions, and ad schedule optimizations.',
        tips: 'Higher is better. 80%+ means excellent protection. Below 50% indicates significant waste.'
      },
      'quality_score': {
        title: 'Quality Score',
        description: 'Google\'s rating (1-10) of your ad relevance, landing page quality, and expected click-through rate. Higher scores reduce costs.',
        tips: 'Target 7+. Improving Quality Score can cut costs by 50% or more.'
      },
      'extensions': {
        title: 'Ad Extensions',
        description: 'Additional information shown with your ads (phone numbers, links, location, etc.). Extensions increase click-through rates.',
        tips: 'Use at least 4 extension types per campaign for maximum visibility.'
      },
      'monthly_spend': {
        title: 'Monthly Spend',
        description: 'Total amount spent on Google Ads in the last 30 days.',
        tips: 'Monitor trends - sudden spikes may indicate bid changes or seasonal factors.'
      },
      'impressions': {
        title: 'Impressions',
        description: 'Number of times your ads were shown to users in search results.',
        tips: 'Low impressions? Check your bids and budgets. High impressions but low clicks? Improve ad copy.'
      },
      'clicks': {
        title: 'Clicks',
        description: 'Number of times users clicked on your ads.',
        tips: 'Compare to impressions for CTR. More clicks = more traffic to your site.'
      },
      'ctr': {
        title: 'Click-Through Rate (CTR)',
        description: 'Percentage of impressions that resulted in clicks. Industry average for Search is 3-5%.',
        tips: 'Higher CTR improves Quality Score. Test different ad copy to improve.'
      },
      'conversions': {
        title: 'Conversions',
        description: 'Completed actions you\'re tracking (form submissions, purchases, calls, etc.).',
        tips: 'Set up conversion tracking to measure ROI accurately.'
      },
      'cost_per_conversion': {
        title: 'Cost Per Conversion (CPA)',
        description: 'Average amount spent to get one conversion.',
        tips: 'Compare to your customer lifetime value. If CPA < LTV, you\'re profitable.'
      },
      'impression_share': {
        title: 'Impression Share',
        description: 'Percentage of possible impressions your ads received. Lost impressions = missed opportunities.',
        tips: '80%+ is excellent. Below 50%? Increase budgets or improve Quality Score.'
      },
      'cpc': {
        title: 'Cost Per Click (CPC)',
        description: 'Average amount paid each time someone clicks your ad.',
        tips: 'Lower CPC = more clicks for your budget. Improve Quality Score to reduce CPC.'
      },
      'roas': {
        title: 'Return on Ad Spend (ROAS)',
        description: 'Revenue generated for every dollar spent on ads. Formula: Revenue ÷ Ad Spend.',
        tips: 'Target 3:1 or higher (300% ROAS). Below 1:1 means losing money.'
      },
      'match_type': {
        title: 'Keyword Match Type',
        description: '<strong>Exact:</strong> [keyword] - most restrictive<br><strong>Phrase:</strong> "keyword" - moderate<br><strong>Broad:</strong> keyword - least restrictive',
        tips: 'Start with exact/phrase for control. Use broad with negative keywords to prevent waste.'
      },
      'negative_keywords': {
        title: 'Negative Keywords',
        description: 'Words that prevent your ads from showing. Essential for preventing wasted spend on irrelevant searches.',
        tips: 'Add 20-50+ negative keywords per campaign. Review search terms weekly.'
      },
      'search_terms': {
        title: 'Search Terms',
        description: 'Actual queries users typed that triggered your ads.',
        tips: 'Review weekly to find new keywords and add negative keywords for irrelevant terms.'
      },
      'bidding_strategy': {
        title: 'Bidding Strategy',
        description: 'How Google sets your bids. Manual = you control. Automated = AI optimizes for your goal.',
        tips: 'Start with Maximize Conversions or Target CPA once you have 30+ conversions/month.'
      },
      'daily_budget': {
        title: 'Daily Budget',
        description: 'Average amount you want to spend per day. Google may spend up to 2x on high-traffic days.',
        tips: 'Set at monthly budget ÷ 30.4. Monitor closely the first week.'
      },
      'account_structure': {
        title: 'Account Structure',
        description: 'How well your campaigns, ad groups, and keywords are organized.',
        tips: 'Use tightly themed ad groups (5-15 keywords each) for better Quality Scores.'
      },
      'mobile_optimization': {
        title: 'Mobile Optimization',
        description: 'How well your campaigns perform on mobile devices.',
        tips: 'Use mobile-preferred ads and ensure landing pages load fast on mobile.'
      }
    },

    /**
     * Initialize the tooltip system
     */
    init: function() {
      this.createTooltipElement();
      this.attachEventListeners();
      this.injectStyles();
    },

    /**
     * Create the tooltip DOM element
     */
    createTooltipElement: function() {
      this.tooltipElement = document.createElement('div');
      this.tooltipElement.className = 'metric-tooltip';
      this.tooltipElement.style.display = 'none';
      document.body.appendChild(this.tooltipElement);
    },

    /**
     * Attach event listeners to all tooltip triggers
     */
    attachEventListeners: function() {
      // Use event delegation for better performance
      document.addEventListener('mouseenter', (e) => {
        const target = e.target.closest('[data-tooltip]');
        if (target) {
          this.show(target);
        }
      }, true);

      document.addEventListener('mouseleave', (e) => {
        const target = e.target.closest('[data-tooltip]');
        if (target) {
          this.scheduleHide();
        }
      }, true);

      // Keep tooltip visible when hovering over it
      this.tooltipElement.addEventListener('mouseenter', () => {
        clearTimeout(this.hideTimeout);
      });

      this.tooltipElement.addEventListener('mouseleave', () => {
        this.hide();
      });
    },

    /**
     * Show tooltip for target element
     */
    show: function(target) {
      clearTimeout(this.hideTimeout);
      this.currentTarget = target;

      // Get tooltip content
      const tooltipKey = target.dataset.tooltip;
      const customContent = target.dataset.tooltipContent;

      let content;
      if (customContent) {
        content = `<div class="tooltip-content">${customContent}</div>`;
      } else if (this.glossary[tooltipKey]) {
        const entry = this.glossary[tooltipKey];
        content = `
          <div class="tooltip-header">${entry.title}</div>
          <div class="tooltip-description">${entry.description}</div>
          ${entry.tips ? `<div class="tooltip-tips"><i class="fa-solid fa-lightbulb"></i> ${entry.tips}</div>` : ''}
        `;
      } else {
        content = `<div class="tooltip-content">${tooltipKey}</div>`;
      }

      this.tooltipElement.innerHTML = content;
      this.tooltipElement.style.display = 'block';

      // Position tooltip
      this.position(target);

      // Add visible class for animation
      setTimeout(() => {
        this.tooltipElement.classList.add('visible');
      }, 10);
    },

    /**
     * Position tooltip relative to target
     */
    position: function(target) {
      const targetRect = target.getBoundingClientRect();
      const tooltipRect = this.tooltipElement.getBoundingClientRect();

      let top = targetRect.bottom + window.scrollY + 8;
      let left = targetRect.left + window.scrollX + (targetRect.width / 2) - (tooltipRect.width / 2);

      // Keep tooltip within viewport horizontally
      const viewportWidth = window.innerWidth;
      if (left < 10) {
        left = 10;
      } else if (left + tooltipRect.width > viewportWidth - 10) {
        left = viewportWidth - tooltipRect.width - 10;
      }

      // If tooltip would go below viewport, show above target
      if (top + tooltipRect.height > window.innerHeight + window.scrollY - 10) {
        top = targetRect.top + window.scrollY - tooltipRect.height - 8;
        this.tooltipElement.classList.add('tooltip-top');
      } else {
        this.tooltipElement.classList.remove('tooltip-top');
      }

      this.tooltipElement.style.top = top + 'px';
      this.tooltipElement.style.left = left + 'px';
    },

    /**
     * Schedule tooltip hide with delay
     */
    scheduleHide: function() {
      this.hideTimeout = setTimeout(() => {
        this.hide();
      }, 200);
    },

    /**
     * Hide tooltip
     */
    hide: function() {
      this.tooltipElement.classList.remove('visible');
      setTimeout(() => {
        this.tooltipElement.style.display = 'none';
        this.currentTarget = null;
      }, 200);
    },

    /**
     * Inject CSS styles
     */
    injectStyles: function() {
      if (document.getElementById('metric-tooltips-styles')) return;

      const style = document.createElement('style');
      style.id = 'metric-tooltips-styles';
      style.textContent = `
        /* Tooltip trigger styling */
        [data-tooltip] {
          position: relative;
          cursor: help;
          border-bottom: 1px dotted currentColor;
        }

        [data-tooltip]:hover {
          border-bottom-style: solid;
        }

        /* Tooltip element */
        .metric-tooltip {
          position: absolute;
          z-index: 100000;
          background: linear-gradient(135deg, #1f2937 0%, #111827 100%);
          color: white;
          border-radius: 8px;
          padding: 12px 16px;
          max-width: 320px;
          box-shadow: 0 10px 40px rgba(0, 0, 0, 0.3), 0 0 0 1px rgba(255, 255, 255, 0.1);
          opacity: 0;
          transform: translateY(-4px);
          transition: opacity 0.2s ease, transform 0.2s ease;
          pointer-events: auto;
          font-size: 13px;
          line-height: 1.5;
        }

        .metric-tooltip.visible {
          opacity: 1;
          transform: translateY(0);
        }

        .metric-tooltip::before {
          content: '';
          position: absolute;
          top: -6px;
          left: 50%;
          transform: translateX(-50%);
          width: 12px;
          height: 12px;
          background: #1f2937;
          border-radius: 2px;
          transform: translateX(-50%) rotate(45deg);
        }

        .metric-tooltip.tooltip-top::before {
          top: auto;
          bottom: -6px;
        }

        .tooltip-header {
          font-weight: 700;
          font-size: 14px;
          margin-bottom: 6px;
          color: #fbbf24;
        }

        .tooltip-description {
          font-size: 13px;
          line-height: 1.5;
          color: #e5e7eb;
          margin-bottom: 8px;
        }

        .tooltip-description:last-child {
          margin-bottom: 0;
        }

        .tooltip-tips {
          font-size: 12px;
          padding: 8px 10px;
          background: rgba(59, 130, 246, 0.15);
          border-left: 3px solid #3b82f6;
          border-radius: 4px;
          color: #93c5fd;
          margin-top: 8px;
        }

        .tooltip-tips i {
          margin-right: 6px;
          color: #60a5fa;
        }

        .tooltip-content {
          font-size: 13px;
          color: #e5e7eb;
        }

        /* Tooltip icon styling */
        .tooltip-icon {
          display: inline-flex;
          align-items: center;
          justify-content: center;
          width: 16px;
          height: 16px;
          border-radius: 50%;
          background: #6b7280;
          color: white;
          font-size: 10px;
          font-weight: 700;
          margin-left: 4px;
          cursor: help;
          transition: background-color 0.2s;
        }

        .tooltip-icon:hover {
          background: #4f46e5;
        }
      `;

      document.head.appendChild(style);
    }
  };

  // Export to global scope
  window.MetricTooltips = MetricTooltips;

  // Auto-initialize on DOM ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => MetricTooltips.init());
  } else {
    MetricTooltips.init();
  }

})(window);
