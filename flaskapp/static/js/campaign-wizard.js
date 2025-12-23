/**
 * Google Ads Campaign Creation Wizard
 * Multi-step form for creating campaigns with validation and dynamic content
 */

(function() {
  'use strict';

  let currentStep = 1;
  const totalSteps = 6;
  let adGroupCount = 1;

  // Initialize wizard
  document.addEventListener('DOMContentLoaded', function() {
    initializeWizard();
    setupEventListeners();
    updateKeywordsSection();
    updateAdsSection();
  });

  function initializeWizard() {
    showStep(1);
    updateNavigationButtons();
  }

  function setupEventListeners() {
    // Navigation buttons
    document.getElementById('next_button').addEventListener('click', nextStep);
    document.getElementById('prev_button').addEventListener('click', prevStep);

    // Add ad group button
    document.getElementById('add_ad_group').addEventListener('click', addAdGroup);

    // Form submission
    document.getElementById('campaignWizardForm').addEventListener('submit', handleSubmit);

    // Bidding strategy change
    document.querySelector('[name="bidding_strategy"]').addEventListener('change', handleBiddingStrategyChange);
  }

  function showStep(step) {
    // Hide all steps
    document.querySelectorAll('.wizard-content').forEach(content => {
      content.classList.remove('active');
    });

    // Show current step
    const currentContent = document.querySelector(`.wizard-content[data-step="${step}"]`);
    if (currentContent) {
      currentContent.classList.add('active');
    }

    // Update step indicators
    document.querySelectorAll('.wizard-step').forEach((stepEl, index) => {
      const stepNum = index + 1;
      stepEl.classList.remove('active', 'completed');

      if (stepNum < step) {
        stepEl.classList.add('completed');
      } else if (stepNum === step) {
        stepEl.classList.add('active');
      }
    });

    currentStep = step;
    updateNavigationButtons();

    // Special handling for specific steps
    if (step === 4) {
      updateKeywordsSection();
    } else if (step === 5) {
      updateAdsSection();
    } else if (step === 6) {
      populateReviewStep();
    }
  }

  function updateNavigationButtons() {
    const prevBtn = document.getElementById('prev_button');
    const nextBtn = document.getElementById('next_button');
    const submitBtn = document.getElementById('submit_button');

    // Show/hide previous button
    if (currentStep === 1) {
      prevBtn.classList.add('hidden');
    } else {
      prevBtn.classList.remove('hidden');
    }

    // Show/hide next vs submit button
    if (currentStep === totalSteps) {
      nextBtn.classList.add('hidden');
      submitBtn.classList.remove('hidden');
    } else {
      nextBtn.classList.remove('hidden');
      submitBtn.classList.add('hidden');
    }
  }

  function nextStep() {
    if (validateCurrentStep()) {
      if (currentStep < totalSteps) {
        showStep(currentStep + 1);
      }
    }
  }

  function prevStep() {
    if (currentStep > 1) {
      showStep(currentStep - 1);
    }
  }

  function validateCurrentStep() {
    const currentContent = document.querySelector(`.wizard-content[data-step="${currentStep}"]`);
    const requiredInputs = currentContent.querySelectorAll('[required]');

    let isValid = true;
    requiredInputs.forEach(input => {
      if (!input.value.trim()) {
        isValid = false;
        input.classList.add('border-red-500');

        // Show error message
        let errorMsg = input.parentElement.querySelector('.error-message');
        if (!errorMsg) {
          errorMsg = document.createElement('p');
          errorMsg.className = 'error-message text-xs text-red-600 mt-1';
          errorMsg.textContent = 'This field is required';
          input.parentElement.appendChild(errorMsg);
        }
      } else {
        input.classList.remove('border-red-500');
        const errorMsg = input.parentElement.querySelector('.error-message');
        if (errorMsg) {
          errorMsg.remove();
        }
      }
    });

    if (!isValid) {
      alert('Please fill in all required fields before continuing.');
    }

    return isValid;
  }

  function addAdGroup() {
    adGroupCount++;
    const container = document.getElementById('ad_groups_container');

    const adGroupHTML = `
      <div class="ad-group-item bg-gray-50 border border-gray-200 rounded-lg p-4">
        <div class="flex items-center justify-between mb-4">
          <h3 class="font-bold text-gray-900">Ad Group ${adGroupCount}</h3>
          <button type="button" class="remove-ad-group text-red-600 hover:text-red-800">
            <i class="fa-solid fa-times"></i>
          </button>
        </div>
        <input
          type="text"
          name="ad_groups[${adGroupCount - 1}][name]"
          class="w-full px-4 py-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
          placeholder="e.g., General Plumbing Services"
          required
        >
        <p class="text-xs text-gray-500 mt-1">Group name should describe the theme of keywords</p>
      </div>
    `;

    container.insertAdjacentHTML('beforeend', adGroupHTML);

    // Add remove functionality to new ad group
    const newAdGroup = container.lastElementChild;
    newAdGroup.querySelector('.remove-ad-group').addEventListener('click', function() {
      if (confirm('Remove this ad group?')) {
        newAdGroup.remove();
      }
    });
  }

  function updateKeywordsSection() {
    const container = document.getElementById('keywords_container');
    container.innerHTML = '';

    const adGroups = document.querySelectorAll('.ad-group-item');

    adGroups.forEach((group, index) => {
      const groupName = group.querySelector('input').value || `Ad Group ${index + 1}`;

      const keywordsHTML = `
        <div class="bg-white border border-gray-200 rounded-lg p-6 mb-4">
          <h3 class="font-bold text-gray-900 mb-4">${groupName}</h3>

          <div class="space-y-3">
            <div>
              <label class="block text-sm font-medium text-gray-700 mb-2">Keywords (one per line)</label>
              <textarea
                name="ad_groups[${index}][keywords]"
                rows="5"
                class="w-full px-4 py-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-indigo-500 focus:border-transparent font-mono text-sm"
                placeholder="emergency plumbing&#10;plumber near me&#10;24 hour plumber&#10;pipe repair service&#10;water heater installation"
                required
              ></textarea>
              <p class="text-xs text-gray-500 mt-1">Enter 5-15 keywords. Start with specific, high-intent keywords.</p>
            </div>

            <div>
              <label class="block text-sm font-medium text-gray-700 mb-2">Default Match Type</label>
              <select
                name="ad_groups[${index}][match_type]"
                class="w-full px-4 py-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
              >
                <option value="PHRASE">Phrase Match (Recommended)</option>
                <option value="EXACT">Exact Match</option>
                <option value="BROAD">Broad Match</option>
              </select>
            </div>

            <div>
              <label class="block text-sm font-medium text-gray-700 mb-2">Negative Keywords (optional)</label>
              <input
                type="text"
                name="ad_groups[${index}][negative_keywords]"
                class="w-full px-4 py-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
                placeholder="free, cheap, diy, jobs, careers"
              >
              <p class="text-xs text-gray-500 mt-1">Comma-separated. Prevents ads from showing for these terms.</p>
            </div>
          </div>
        </div>
      `;

      container.insertAdjacentHTML('beforeend', keywordsHTML);
    });
  }

  function updateAdsSection() {
    const container = document.getElementById('ads_container');
    container.innerHTML = '';

    const adGroups = document.querySelectorAll('.ad-group-item');

    adGroups.forEach((group, index) => {
      const groupName = group.querySelector('input').value || `Ad Group ${index + 1}`;

      const adsHTML = `
        <div class="bg-white border border-gray-200 rounded-lg p-6 mb-4">
          <h3 class="font-bold text-gray-900 mb-4">${groupName} - Responsive Search Ad</h3>

          <div class="space-y-4">
            <div>
              <label class="block text-sm font-medium text-gray-700 mb-2">
                Headlines (3-15 required) <span class="text-red-500">*</span>
              </label>
              <p class="text-xs text-gray-600 mb-2">Google will test different combinations. Max 30 characters each.</p>
              ${[1, 2, 3, 4, 5].map(num => `
                <input
                  type="text"
                  name="ad_groups[${index}][headlines][${num - 1}]"
                  maxlength="30"
                  class="w-full px-4 py-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-indigo-500 focus:border-transparent mb-2"
                  placeholder="Headline ${num} (e.g., 24/7 Emergency Plumbing)"
                  ${num <= 3 ? 'required' : ''}
                >
              `).join('')}
            </div>

            <div>
              <label class="block text-sm font-medium text-gray-700 mb-2">
                Descriptions (2-4 required) <span class="text-red-500">*</span>
              </label>
              <p class="text-xs text-gray-600 mb-2">Max 90 characters each. Include benefits and call-to-action.</p>
              ${[1, 2, 3].map(num => `
                <textarea
                  name="ad_groups[${index}][descriptions][${num - 1}]"
                  maxlength="90"
                  rows="2"
                  class="w-full px-4 py-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-indigo-500 focus:border-transparent mb-2"
                  placeholder="Description ${num} (e.g., Licensed & insured plumbers. Fast response times. Call now for free quote!)"
                  ${num <= 2 ? 'required' : ''}
                ></textarea>
              `).join('')}
            </div>

            <div>
              <label class="block text-sm font-medium text-gray-700 mb-2">
                Final URL (Landing Page) <span class="text-red-500">*</span>
              </label>
              <input
                type="url"
                name="ad_groups[${index}][final_url]"
                class="w-full px-4 py-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
                placeholder="https://example.com/services"
                required
              >
              <p class="text-xs text-gray-500 mt-1">Where should clicks go? Can be different from main website URL.</p>
            </div>
          </div>
        </div>
      `;

      container.insertAdjacentHTML('beforeend', adsHTML);
    });
  }

  function populateReviewStep() {
    const reviewContainer = document.getElementById('review_content');

    // Get form data
    const campaignName = document.querySelector('[name="campaign_name"]').value;
    const campaignType = document.querySelector('[name="campaign_type"]:checked').value;
    const websiteUrl = document.querySelector('[name="website_url"]').value;
    const targetLocations = document.querySelector('[name="target_locations"]').value;
    const dailyBudget = document.querySelector('[name="daily_budget"]').value;
    const biddingStrategy = document.querySelector('[name="bidding_strategy"]').value;
    const biddingStrategyText = document.querySelector('[name="bidding_strategy"] option:checked').textContent;

    const adGroups = document.querySelectorAll('.ad-group-item');
    let adGroupsSummary = '';

    adGroups.forEach((group, index) => {
      const groupName = group.querySelector('input').value;
      const keywords = document.querySelector(`[name="ad_groups[${index}][keywords]"]`)?.value || '';
      const keywordCount = keywords.split('\n').filter(k => k.trim()).length;

      adGroupsSummary += `
        <div class="bg-gray-50 border border-gray-200 rounded-lg p-3 mb-2">
          <div class="font-medium text-gray-900">${groupName}</div>
          <div class="text-sm text-gray-600 mt-1">${keywordCount} keywords</div>
        </div>
      `;
    });

    const reviewHTML = `
      <div class="bg-gradient-to-r from-indigo-50 to-purple-50 border-2 border-indigo-200 rounded-xl p-6">
        <h3 class="text-lg font-bold text-gray-900 mb-4">Campaign Summary</h3>

        <div class="grid md:grid-cols-2 gap-4 mb-4">
          <div>
            <div class="text-sm text-gray-600">Campaign Name</div>
            <div class="font-medium text-gray-900">${campaignName}</div>
          </div>
          <div>
            <div class="text-sm text-gray-600">Type</div>
            <div class="font-medium text-gray-900">${campaignType}</div>
          </div>
          <div>
            <div class="text-sm text-gray-600">Daily Budget</div>
            <div class="font-medium text-gray-900">$${dailyBudget}</div>
          </div>
          <div>
            <div class="text-sm text-gray-600">Bidding Strategy</div>
            <div class="font-medium text-gray-900">${biddingStrategyText}</div>
          </div>
          <div>
            <div class="text-sm text-gray-600">Website</div>
            <div class="font-medium text-gray-900 truncate">${websiteUrl}</div>
          </div>
          <div>
            <div class="text-sm text-gray-600">Target Locations</div>
            <div class="font-medium text-gray-900">${targetLocations}</div>
          </div>
        </div>

        <div class="mt-4">
          <div class="text-sm text-gray-600 mb-2">Ad Groups (${adGroups.length})</div>
          ${adGroupsSummary}
        </div>
      </div>

      <div class="bg-blue-50 border border-blue-200 rounded-lg p-4 mt-4">
        <h4 class="font-bold text-blue-900 mb-2">📋 What Happens Next:</h4>
        <ol class="text-sm text-blue-800 space-y-2">
          <li>1. Campaign will be created in your Google Ads account</li>
          <li>2. All ad groups, keywords, and ads will be set up</li>
          <li>3. Campaign will start <strong>paused</strong> for your review</li>
          <li>4. You can enable it from your Google Ads dashboard</li>
        </ol>
      </div>
    `;

    reviewContainer.innerHTML = reviewHTML;
  }

  function handleBiddingStrategyChange(e) {
    const enhancedSection = document.getElementById('enhanced_cpc_section');
    if (e.target.value === 'MANUAL_CPC') {
      enhancedSection.style.display = 'block';
    } else {
      enhancedSection.style.display = 'none';
    }
  }

  function handleSubmit(e) {
    e.preventDefault();

    if (!validateCurrentStep()) {
      return;
    }

    const submitBtn = document.getElementById('submit_button');
    const originalText = submitBtn.innerHTML;

    submitBtn.disabled = true;
    submitBtn.innerHTML = '<i class="fa-solid fa-spinner fa-spin mr-2"></i>Creating Campaign...';

    // Collect form data
    const formData = new FormData(e.target);
    const data = {};

    // Convert FormData to JSON
    formData.forEach((value, key) => {
      // Handle array fields
      if (key.includes('[')) {
        const matches = key.match(/^(.+?)\[(\d+)\]\[(.+?)\]$/);
        if (matches) {
          const [, fieldName, index, subField] = matches;
          if (!data[fieldName]) data[fieldName] = [];
          if (!data[fieldName][index]) data[fieldName][index] = {};

          // Handle nested arrays (like headlines and descriptions)
          if (subField.includes('[')) {
            const subMatches = subField.match(/^(.+?)\[(\d+)\]$/);
            if (subMatches) {
              const [, subFieldName, subIndex] = subMatches;
              if (!data[fieldName][index][subFieldName]) {
                data[fieldName][index][subFieldName] = [];
              }
              data[fieldName][index][subFieldName][subIndex] = value;
            }
          } else {
            data[fieldName][index][subField] = value;
          }
        }
      } else {
        data[key] = value;
      }
    });

    // Submit to backend
    fetch('/account/google/ads/campaign/create', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': document.querySelector('meta[name="csrf-token"]')?.content || ''
      },
      body: JSON.stringify(data)
    })
    .then(response => response.json())
    .then(result => {
      if (result.success) {
        showSuccessMessage(result.campaign_name || campaignName);
      } else {
        throw new Error(result.error || 'Failed to create campaign');
      }
    })
    .catch(error => {
      console.error('Error creating campaign:', error);
      alert('Error creating campaign: ' + error.message);
      submitBtn.disabled = false;
      submitBtn.innerHTML = originalText;
    });
  }

  function showSuccessMessage(campaignName) {
    const successHTML = `
      <div class="fixed inset-0 bg-black bg-opacity-50 z-50 flex items-center justify-center p-4">
        <div class="bg-white rounded-xl shadow-2xl max-w-md w-full p-8 text-center">
          <div class="mb-4">
            <i class="fa-solid fa-check-circle text-6xl text-green-500"></i>
          </div>
          <h2 class="text-2xl font-bold text-gray-900 mb-2">Campaign Created!</h2>
          <p class="text-gray-600 mb-4">"${campaignName}" has been created successfully.</p>
          <div class="bg-blue-50 border border-blue-200 rounded-lg p-4 mb-4 text-left">
            <p class="text-sm text-blue-800">
              <i class="fa-solid fa-info-circle text-blue-600 mr-2"></i>
              Your campaign is currently <strong>paused</strong>. Review it in Google Ads and enable when ready.
            </p>
          </div>
          <button
            onclick="window.location.href='/account/google/ads'"
            class="w-full px-6 py-3 bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 font-bold"
          >
            Back to Opportunities
          </button>
        </div>
      </div>
    `;

    document.body.insertAdjacentHTML('beforeend', successHTML);
  }

})();
