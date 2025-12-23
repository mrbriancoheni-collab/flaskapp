/**
 * Google Ads Onboarding Wizard
 *
 * A 5-step interactive onboarding flow for first-time Google Ads users
 * - Shows only on first visit (tracked via localStorage)
 * - Can be skipped at any time
 * - Covers basic concepts and navigation
 */

(function(window) {
  'use strict';

  const GoogleAdsOnboarding = {
    currentStep: 0,
    totalSteps: 5,
    wizardElement: null,
    backdropElement: null,

    steps: [
      {
        title: "Welcome to Google Ads Management! 👋",
        icon: "fa-rocket",
        content: `
          <p class="text-lg mb-4">Your AI-powered Google Ads optimization tool is ready to help you maximize your advertising ROI.</p>
          <div class="bg-blue-50 border border-blue-200 rounded-lg p-4 mb-4">
            <h4 class="font-bold text-blue-900 mb-2">What This Tool Does:</h4>
            <ul class="text-sm text-blue-800 space-y-2">
              <li><i class="fa-solid fa-check-circle text-blue-600 mr-2"></i>Analyzes your Google Ads account 24/7</li>
              <li><i class="fa-solid fa-check-circle text-blue-600 mr-2"></i>Identifies optimization opportunities</li>
              <li><i class="fa-solid fa-check-circle text-blue-600 mr-2"></i>Auto-executes low-risk improvements</li>
              <li><i class="fa-solid fa-check-circle text-blue-600 mr-2"></i>Provides recommendations for high-impact changes</li>
            </ul>
          </div>
          <p class="text-sm text-gray-600">This quick tour will show you the key features. <strong>You can skip at any time.</strong></p>
        `,
        duration: "30 seconds"
      },
      {
        title: "Understanding Your Metrics 📊",
        icon: "fa-chart-bar",
        content: `
          <p class="mb-4">Let's look at the key metrics you'll see on your dashboard:</p>
          <div class="space-y-3">
            <div class="bg-gray-50 border border-gray-200 rounded-lg p-3">
              <div class="flex items-start gap-3">
                <div class="w-10 h-10 bg-green-100 rounded-full flex items-center justify-center flex-shrink-0">
                  <i class="fa-solid fa-heart-pulse text-green-600"></i>
                </div>
                <div class="flex-1">
                  <h5 class="font-bold text-gray-900 mb-1">Health Score (0-100)</h5>
                  <p class="text-sm text-gray-700">Overall account performance grade. Higher is better. Aim for 80+.</p>
                </div>
              </div>
            </div>
            <div class="bg-gray-50 border border-gray-200 rounded-lg p-3">
              <div class="flex items-start gap-3">
                <div class="w-10 h-10 bg-red-100 rounded-full flex items-center justify-center flex-shrink-0">
                  <i class="fa-solid fa-piggy-bank text-red-600"></i>
                </div>
                <div class="flex-1">
                  <h5 class="font-bold text-gray-900 mb-1">Wasted Spend (%)</h5>
                  <p class="text-sm text-gray-700">Percentage of budget protected from waste. Higher means better protection.</p>
                </div>
              </div>
            </div>
            <div class="bg-gray-50 border border-gray-200 rounded-lg p-3">
              <div class="flex items-start gap-3">
                <div class="w-10 h-10 bg-yellow-100 rounded-full flex items-center justify-center flex-shrink-0">
                  <i class="fa-solid fa-star text-yellow-600"></i>
                </div>
                <div class="flex-1">
                  <h5 class="font-bold text-gray-900 mb-1">Quality Score</h5>
                  <p class="text-sm text-gray-700">How relevant your ads are. Better scores = lower costs & better positions.</p>
                </div>
              </div>
            </div>
          </div>
          <div class="mt-4 bg-blue-50 border border-blue-200 rounded-lg p-3">
            <p class="text-sm text-blue-800"><i class="fa-solid fa-lightbulb text-blue-600 mr-2"></i><strong>Tip:</strong> Hover over any metric to see what it means and how to improve it.</p>
          </div>
        `,
        duration: "60 seconds"
      },
      {
        title: "Reviewing Opportunities 🎯",
        icon: "fa-list-check",
        content: `
          <p class="mb-4">AI agents identify specific optimizations to improve your account:</p>
          <div class="bg-gradient-to-br from-red-50 to-orange-50 border-2 border-red-200 rounded-lg p-4 mb-3">
            <div class="flex items-start gap-3">
              <div class="text-2xl">🔥</div>
              <div>
                <h5 class="font-bold text-red-900 mb-1">High Priority</h5>
                <p class="text-sm text-red-800">Critical issues that need immediate attention. Fix these first.</p>
              </div>
            </div>
          </div>
          <div class="bg-gradient-to-br from-yellow-50 to-amber-50 border-2 border-yellow-200 rounded-lg p-4 mb-3">
            <div class="flex items-start gap-3">
              <div class="text-2xl">⚡</div>
              <div>
                <h5 class="font-bold text-yellow-900 mb-1">Medium Priority</h5>
                <p class="text-sm text-yellow-800">Important improvements that will boost performance.</p>
              </div>
            </div>
          </div>
          <div class="bg-gradient-to-br from-gray-50 to-slate-50 border-2 border-gray-200 rounded-lg p-4 mb-4">
            <div class="flex items-start gap-3">
              <div class="text-2xl">📈</div>
              <div>
                <h5 class="font-bold text-gray-900 mb-1">Low Priority</h5>
                <p class="text-sm text-gray-700">Optional enhancements for fine-tuning.</p>
              </div>
            </div>
          </div>
          <div class="bg-green-50 border border-green-200 rounded-lg p-3">
            <p class="text-sm text-green-800"><i class="fa-solid fa-check-double text-green-600 mr-2"></i><strong>Select &amp; Approve:</strong> Check the boxes next to optimizations you want, then click "Review &amp; Approve Selected"</p>
          </div>
        `,
        duration: "90 seconds"
      },
      {
        title: "Monitoring & Tracking 📈",
        icon: "fa-chart-line",
        content: `
          <p class="mb-4">Keep tabs on your account performance and agent activity:</p>
          <div class="grid grid-cols-2 gap-3 mb-4">
            <div class="bg-indigo-50 border border-indigo-200 rounded-lg p-4 text-center">
              <i class="fa-solid fa-chart-line text-3xl text-indigo-600 mb-2"></i>
              <h5 class="font-bold text-indigo-900 text-sm">Dashboard</h5>
              <p class="text-xs text-indigo-700 mt-1">View agent performance &amp; history</p>
            </div>
            <div class="bg-purple-50 border border-purple-200 rounded-lg p-4 text-center">
              <i class="fa-solid fa-clipboard-check text-3xl text-purple-600 mb-2"></i>
              <h5 class="font-bold text-purple-900 text-sm">Approval Queue</h5>
              <p class="text-xs text-purple-700 mt-1">Review pending high-risk changes</p>
            </div>
          </div>
          <div class="bg-blue-50 border border-blue-200 rounded-lg p-4 mb-3">
            <h5 class="font-bold text-blue-900 mb-2">What Gets Auto-Applied?</h5>
            <ul class="text-sm text-blue-800 space-y-1">
              <li><i class="fa-solid fa-check text-blue-600 mr-2"></i>Adding negative keywords (prevents wasted spend)</li>
              <li><i class="fa-solid fa-check text-blue-600 mr-2"></i>Pausing low-performing keywords</li>
              <li><i class="fa-solid fa-check text-blue-600 mr-2"></i>Improving ad extensions</li>
              <li><i class="fa-solid fa-check text-blue-600 mr-2"></i>Adjusting bids based on performance</li>
            </ul>
          </div>
          <div class="bg-amber-50 border border-amber-200 rounded-lg p-3">
            <h5 class="font-bold text-amber-900 mb-2">What Needs Your Approval?</h5>
            <ul class="text-sm text-amber-800 space-y-1">
              <li><i class="fa-solid fa-exclamation-triangle text-amber-600 mr-2"></i>Large budget changes</li>
              <li><i class="fa-solid fa-exclamation-triangle text-amber-600 mr-2"></i>Pausing entire campaigns</li>
              <li><i class="fa-solid fa-exclamation-triangle text-amber-600 mr-2"></i>Major bid strategy shifts</li>
            </ul>
          </div>
        `,
        duration: "60 seconds"
      },
      {
        title: "Getting Help & Resources 🆘",
        icon: "fa-life-ring",
        content: `
          <p class="mb-4">Here's how to get the most out of this tool:</p>
          <div class="space-y-3 mb-4">
            <div class="bg-gray-50 border border-gray-200 rounded-lg p-3">
              <div class="flex items-start gap-3">
                <i class="fa-solid fa-question-circle text-2xl text-indigo-600"></i>
                <div>
                  <h5 class="font-bold text-gray-900 mb-1">Tooltips on Metrics</h5>
                  <p class="text-sm text-gray-700">Hover over any metric or term to see an explanation.</p>
                </div>
              </div>
            </div>
            <div class="bg-gray-50 border border-gray-200 rounded-lg p-3">
              <div class="flex items-start gap-3">
                <i class="fa-solid fa-book text-2xl text-purple-600"></i>
                <div>
                  <h5 class="font-bold text-gray-900 mb-1">Glossary</h5>
                  <p class="text-sm text-gray-700">Click the "?" icon in the navigation for definitions of common terms.</p>
                </div>
              </div>
            </div>
            <div class="bg-gray-50 border border-gray-200 rounded-lg p-3">
              <div class="flex items-start gap-3">
                <i class="fa-solid fa-graduation-cap text-2xl text-green-600"></i>
                <div>
                  <h5 class="font-bold text-gray-900 mb-1">Learning Center</h5>
                  <p class="text-sm text-gray-700">Access Google Ads best practices and guides.</p>
                </div>
              </div>
            </div>
          </div>
          <div class="bg-gradient-to-r from-green-50 to-emerald-50 border-2 border-green-300 rounded-lg p-4">
            <h5 class="font-bold text-green-900 mb-2 text-center">🎉 You're All Set!</h5>
            <p class="text-sm text-green-800 text-center mb-3">Your account is being analyzed right now. Check your opportunities below!</p>
            <p class="text-xs text-green-700 text-center"><strong>Pro Tip:</strong> Review optimizations weekly for best results.</p>
          </div>
        `,
        duration: "30 seconds"
      }
    ],

    /**
     * Initialize the onboarding wizard
     */
    init: function() {
      // Check if user has already completed onboarding
      if (this.hasCompletedOnboarding()) {
        return;
      }

      // Check if user has explicitly skipped for this session
      if (sessionStorage.getItem('google_ads_onboarding_skipped') === 'true') {
        return;
      }

      // Show wizard after a short delay
      setTimeout(() => this.show(), 800);
    },

    /**
     * Check if user has completed onboarding
     */
    hasCompletedOnboarding: function() {
      return localStorage.getItem('google_ads_onboarding_completed') === 'true';
    },

    /**
     * Mark onboarding as completed
     */
    markCompleted: function() {
      localStorage.setItem('google_ads_onboarding_completed', 'true');
    },

    /**
     * Mark onboarding as skipped for this session
     */
    markSkipped: function() {
      sessionStorage.setItem('google_ads_onboarding_skipped', 'true');
    },

    /**
     * Show the wizard
     */
    show: function() {
      this.createBackdrop();
      this.createWizard();
      this.renderStep();

      // Animate in
      setTimeout(() => {
        this.backdropElement.classList.add('active');
        this.wizardElement.classList.add('active');
      }, 10);
    },

    /**
     * Create backdrop
     */
    createBackdrop: function() {
      this.backdropElement = document.createElement('div');
      this.backdropElement.id = 'google-ads-onboarding-backdrop';
      this.backdropElement.className = 'google-ads-onboarding-backdrop';
      document.body.appendChild(this.backdropElement);
    },

    /**
     * Create wizard container
     */
    createWizard: function() {
      this.wizardElement = document.createElement('div');
      this.wizardElement.id = 'google-ads-onboarding-wizard';
      this.wizardElement.className = 'google-ads-onboarding-wizard';
      document.body.appendChild(this.wizardElement);
    },

    /**
     * Render current step
     */
    renderStep: function() {
      const step = this.steps[this.currentStep];
      const isLastStep = this.currentStep === this.totalSteps - 1;

      this.wizardElement.innerHTML = `
        <!-- Progress Bar -->
        <div class="onboarding-progress">
          <div class="onboarding-progress-bar" style="width: ${((this.currentStep + 1) / this.totalSteps) * 100}%"></div>
        </div>

        <!-- Header -->
        <div class="onboarding-header">
          <div class="onboarding-icon">
            <i class="fa-solid ${step.icon}"></i>
          </div>
          <h2 class="onboarding-title">${step.title}</h2>
          <div class="onboarding-step-indicator">Step ${this.currentStep + 1} of ${this.totalSteps}</div>
        </div>

        <!-- Content -->
        <div class="onboarding-content">
          ${step.content}
        </div>

        <!-- Footer -->
        <div class="onboarding-footer">
          <div class="onboarding-footer-left">
            <button class="onboarding-btn-skip" onclick="GoogleAdsOnboarding.skip()">
              <i class="fa-solid fa-times mr-2"></i>Skip Tutorial
            </button>
          </div>
          <div class="onboarding-footer-right">
            ${this.currentStep > 0 ? `
              <button class="onboarding-btn-secondary" onclick="GoogleAdsOnboarding.previous()">
                <i class="fa-solid fa-arrow-left mr-2"></i>Back
              </button>
            ` : ''}
            ${!isLastStep ? `
              <button class="onboarding-btn-primary" onclick="GoogleAdsOnboarding.next()">
                Next<i class="fa-solid fa-arrow-right ml-2"></i>
              </button>
            ` : `
              <button class="onboarding-btn-primary" onclick="GoogleAdsOnboarding.complete()">
                <i class="fa-solid fa-check mr-2"></i>Get Started!
              </button>
            `}
          </div>
        </div>
      `;
    },

    /**
     * Go to next step
     */
    next: function() {
      if (this.currentStep < this.totalSteps - 1) {
        this.currentStep++;
        this.renderStep();
      }
    },

    /**
     * Go to previous step
     */
    previous: function() {
      if (this.currentStep > 0) {
        this.currentStep--;
        this.renderStep();
      }
    },

    /**
     * Skip onboarding
     */
    skip: function() {
      if (confirm('Are you sure you want to skip the tutorial?\n\nYou can always restart it from the Help menu.')) {
        this.markSkipped();
        this.hide();
      }
    },

    /**
     * Complete onboarding
     */
    complete: function() {
      this.markCompleted();
      this.hide();

      // Show success message
      this.showSuccessMessage();
    },

    /**
     * Hide wizard
     */
    hide: function() {
      this.wizardElement.classList.remove('active');
      this.backdropElement.classList.remove('active');

      setTimeout(() => {
        if (this.wizardElement) this.wizardElement.remove();
        if (this.backdropElement) this.backdropElement.remove();
        this.wizardElement = null;
        this.backdropElement = null;
      }, 300);
    },

    /**
     * Show success message after completion
     */
    showSuccessMessage: function() {
      const message = document.createElement('div');
      message.className = 'google-ads-onboarding-success';
      message.innerHTML = `
        <div class="success-content">
          <i class="fa-solid fa-check-circle text-5xl text-green-500 mb-3"></i>
          <h3 class="text-xl font-bold text-gray-900 mb-2">Tutorial Complete!</h3>
          <p class="text-sm text-gray-600">You're ready to optimize your Google Ads account.</p>
        </div>
      `;
      document.body.appendChild(message);

      setTimeout(() => message.classList.add('active'), 10);
      setTimeout(() => {
        message.classList.remove('active');
        setTimeout(() => message.remove(), 300);
      }, 3000);
    },

    /**
     * Restart onboarding (for help menu)
     */
    restart: function() {
      localStorage.removeItem('google_ads_onboarding_completed');
      sessionStorage.removeItem('google_ads_onboarding_skipped');
      this.currentStep = 0;
      this.show();
    }
  };

  // Inject CSS styles
  const style = document.createElement('style');
  style.textContent = `
    .google-ads-onboarding-backdrop {
      position: fixed;
      top: 0;
      left: 0;
      right: 0;
      bottom: 0;
      background: rgba(0, 0, 0, 0.6);
      backdrop-filter: blur(4px);
      z-index: 99998;
      opacity: 0;
      transition: opacity 0.3s ease;
    }

    .google-ads-onboarding-backdrop.active {
      opacity: 1;
    }

    .google-ads-onboarding-wizard {
      position: fixed;
      top: 50%;
      left: 50%;
      transform: translate(-50%, -50%) scale(0.9);
      width: 90%;
      max-width: 700px;
      max-height: 85vh;
      background: white;
      border-radius: 16px;
      box-shadow: 0 20px 60px rgba(0, 0, 0, 0.3);
      z-index: 99999;
      opacity: 0;
      transition: all 0.3s ease;
      display: flex;
      flex-direction: column;
      overflow: hidden;
    }

    .google-ads-onboarding-wizard.active {
      opacity: 1;
      transform: translate(-50%, -50%) scale(1);
    }

    .onboarding-progress {
      height: 4px;
      background: #e5e7eb;
      position: relative;
    }

    .onboarding-progress-bar {
      height: 100%;
      background: linear-gradient(90deg, #4f46e5 0%, #7c3aed 100%);
      transition: width 0.3s ease;
    }

    .onboarding-header {
      padding: 32px 32px 24px;
      text-align: center;
      border-bottom: 1px solid #e5e7eb;
    }

    .onboarding-icon {
      width: 64px;
      height: 64px;
      margin: 0 auto 16px;
      background: linear-gradient(135deg, #4f46e5 0%, #7c3aed 100%);
      border-radius: 16px;
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 28px;
      color: white;
    }

    .onboarding-title {
      font-size: 24px;
      font-weight: 700;
      color: #111827;
      margin: 0 0 8px 0;
    }

    .onboarding-step-indicator {
      font-size: 13px;
      color: #6b7280;
      font-weight: 500;
    }

    .onboarding-content {
      flex: 1;
      overflow-y: auto;
      padding: 24px 32px;
      line-height: 1.6;
    }

    .onboarding-content::-webkit-scrollbar {
      width: 8px;
    }

    .onboarding-content::-webkit-scrollbar-track {
      background: #f3f4f6;
      border-radius: 4px;
    }

    .onboarding-content::-webkit-scrollbar-thumb {
      background: #d1d5db;
      border-radius: 4px;
    }

    .onboarding-content::-webkit-scrollbar-thumb:hover {
      background: #9ca3af;
    }

    .onboarding-footer {
      padding: 20px 32px;
      border-top: 1px solid #e5e7eb;
      display: flex;
      align-items: center;
      justify-content: space-between;
      background: #f9fafb;
    }

    .onboarding-footer-left {
      flex: 0 0 auto;
    }

    .onboarding-footer-right {
      flex: 0 0 auto;
      display: flex;
      gap: 12px;
    }

    .onboarding-btn-skip {
      background: none;
      border: none;
      color: #6b7280;
      font-size: 14px;
      font-weight: 500;
      cursor: pointer;
      padding: 8px 16px;
      border-radius: 8px;
      transition: all 0.2s;
    }

    .onboarding-btn-skip:hover {
      background: #e5e7eb;
      color: #111827;
    }

    .onboarding-btn-secondary {
      background: white;
      border: 1px solid #d1d5db;
      color: #374151;
      font-size: 14px;
      font-weight: 500;
      cursor: pointer;
      padding: 10px 20px;
      border-radius: 8px;
      transition: all 0.2s;
    }

    .onboarding-btn-secondary:hover {
      background: #f3f4f6;
      border-color: #9ca3af;
    }

    .onboarding-btn-primary {
      background: linear-gradient(135deg, #4f46e5 0%, #7c3aed 100%);
      border: none;
      color: white;
      font-size: 14px;
      font-weight: 600;
      cursor: pointer;
      padding: 10px 24px;
      border-radius: 8px;
      transition: all 0.2s;
      box-shadow: 0 2px 8px rgba(79, 70, 229, 0.3);
    }

    .onboarding-btn-primary:hover {
      transform: translateY(-1px);
      box-shadow: 0 4px 12px rgba(79, 70, 229, 0.4);
    }

    .google-ads-onboarding-success {
      position: fixed;
      top: 24px;
      right: 24px;
      background: white;
      border-radius: 12px;
      box-shadow: 0 10px 40px rgba(0, 0, 0, 0.15);
      padding: 24px;
      z-index: 100000;
      opacity: 0;
      transform: translateY(-20px);
      transition: all 0.3s ease;
    }

    .google-ads-onboarding-success.active {
      opacity: 1;
      transform: translateY(0);
    }

    .success-content {
      text-align: center;
    }

    /* Utility classes */
    .mr-2 { margin-right: 0.5rem; }
    .ml-2 { margin-left: 0.5rem; }
  `;
  document.head.appendChild(style);

  // Export to global scope
  window.GoogleAdsOnboarding = GoogleAdsOnboarding;

  // Auto-initialize on DOM ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => GoogleAdsOnboarding.init());
  } else {
    GoogleAdsOnboarding.init();
  }

})(window);
