// static/js/gsc_insights.js
// Google Search Console SEO Insights Modal - Progressive Loading & Interaction

/**
 * Main entry point - called when user clicks "Optimize" or "Generate SEO Insights" button
 */
async function generateGSCInsights(siteUrl) {
  // Open modal
  const modal = document.getElementById('gscInsightsModal');
  modal.classList.remove('hidden');

  // Show loading state
  document.getElementById('gscInsightsLoading').classList.remove('hidden');
  document.getElementById('gscInsightsResults').classList.add('hidden');

  // Start progressive loading animation
  const loadingPromise = simulateGSCLoadingSteps();

  try {
    // Fetch insights from API
    const response = await fetch('/account/google/gsc/insights.json', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        site_url: siteUrl,
        regenerate: true
      })
    });

    if (!response.ok) {
      throw new Error(`HTTP ${response.status}: ${response.statusText}`);
    }

    const data = await response.json();

    // Wait for loading animation to complete
    await loadingPromise;

    // Hide loading, show results
    document.getElementById('gscInsightsLoading').classList.add('hidden');
    document.getElementById('gscInsightsResults').classList.remove('hidden');

    // Display insights
    displayGSCInsights(data);

  } catch (error) {
    console.error('Error generating GSC insights:', error);
    await loadingPromise; // Wait for animation
    showGSCError(error.message || 'Failed to generate SEO insights. Please try again.');
  }
}

/**
 * Simulate progressive loading steps with animations
 */
async function simulateGSCLoadingSteps() {
  const steps = ['gscStep1', 'gscStep2', 'gscStep3', 'gscStep4'];
  const messages = [
    'Reviewing search rankings...',
    'Analyzing click-through rates...',
    'Finding SEO opportunities...',
    'Generating recommendations...'
  ];

  for (let i = 0; i < steps.length; i++) {
    await new Promise(resolve => setTimeout(resolve, 800));

    // Mark current step as complete
    const stepEl = document.getElementById(steps[i]);
    stepEl.innerHTML = `<i class="fa-solid fa-check-circle text-green-600"></i> <span>${messages[i].replace('...', '')}</span>`;
    stepEl.classList.remove('text-gray-400');
    stepEl.classList.add('text-green-600');

    // Start next step (if exists)
    if (i < steps.length - 1) {
      const nextStep = document.getElementById(steps[i + 1]);
      nextStep.innerHTML = `<i class="fa-solid fa-spinner fa-spin text-emerald-600"></i> <span>${messages[i + 1]}</span>`;
      nextStep.classList.remove('text-gray-400');
      nextStep.classList.add('text-gray-500');
    }

    // Update loading message
    document.getElementById('gscLoadingMessage').textContent = messages[i];
  }

  // Final pause before showing results
  await new Promise(resolve => setTimeout(resolve, 300));
}

/**
 * Display insights in categorized sections
 */
function displayGSCInsights(data) {
  // Set summary
  document.getElementById('gscInsightsSummary').textContent = data.summary || 'SEO analysis complete.';

  // Get recommendations
  const recommendations = data.recommendations || [];

  if (recommendations.length === 0) {
    document.getElementById('gscNoRecommendations').classList.remove('hidden');
    return;
  }

  // Categorize recommendations by severity
  const categories = {
    critical: [],
    highImpact: [],
    quickWins: [],
    longTerm: []
  };

  recommendations.forEach(rec => {
    const severity = rec.severity || 5;
    if (severity === 1) {
      categories.critical.push(rec);
    } else if (severity === 2) {
      categories.highImpact.push(rec);
    } else if (severity === 3) {
      categories.quickWins.push(rec);
    } else {
      categories.longTerm.push(rec);
    }
  });

  // Display each category
  displayGSCCategory('gscCritical', categories.critical, {
    icon: 'fa-exclamation-triangle',
    color: 'red'
  });

  displayGSCCategory('gscHighImpact', categories.highImpact, {
    icon: 'fa-rocket',
    color: 'orange'
  });

  displayGSCCategory('gscQuickWins', categories.quickWins, {
    icon: 'fa-bolt',
    color: 'green'
  });

  displayGSCCategory('gscLongTerm', categories.longTerm, {
    icon: 'fa-chess',
    color: 'blue'
  });
}

/**
 * Display a category of recommendations
 */
function displayGSCCategory(categoryName, recommendations, options) {
  if (recommendations.length === 0) return;

  const section = document.getElementById(`${categoryName}Section`);
  const cards = document.getElementById(`${categoryName}Cards`);
  const count = document.getElementById(`${categoryName}Count`);

  // Show section
  section.classList.remove('hidden');
  count.textContent = `(${recommendations.length})`;

  // Clear existing cards
  cards.innerHTML = '';

  // Add cards
  recommendations.forEach(rec => {
    const card = createGSCInsightCard(rec, options);
    cards.appendChild(card);
  });

  // Auto-expand critical and high-impact sections
  if (categoryName === 'gscCritical' || categoryName === 'gscHighImpact') {
    cards.classList.remove('hidden');
  }
}

/**
 * Create an insight card from template
 */
function createGSCInsightCard(recommendation, options) {
  const template = document.getElementById('gscInsightCardTemplate');
  const clone = template.content.cloneNode(true);
  const card = clone.querySelector('.border');

  // Icon based on category
  const iconMap = {
    'keywords': 'fa-key',
    'content': 'fa-file-alt',
    'technical_seo': 'fa-cog',
    'ctr_optimization': 'fa-chart-line',
    'rankings': 'fa-trophy',
    'schema': 'fa-code',
    'mobile': 'fa-mobile'
  };

  const iconClass = iconMap[recommendation.category] || options.icon || 'fa-search';
  clone.querySelector('.gsc-insight-icon').className = `gsc-insight-icon text-xl fa-solid ${iconClass} text-${options.color}-600`;

  // Content
  clone.querySelector('.gsc-insight-title').textContent = recommendation.title || 'Untitled';
  clone.querySelector('.gsc-insight-description').textContent = recommendation.description || '';
  clone.querySelector('.gsc-insight-impact').textContent = recommendation.expected_impact || 'Impact pending';

  // Confidence
  const confidence = recommendation.confidence || 0.75;
  const confidencePercent = Math.round(confidence * 100);
  clone.querySelector('.gsc-insight-confidence').textContent = `${confidencePercent}%`;
  clone.querySelector('.gsc-insight-confidence-bar').style.width = `${confidencePercent}%`;

  // Color code confidence
  const confEl = clone.querySelector('.gsc-insight-confidence');
  if (confidence >= 0.8) {
    confEl.classList.add('text-green-700');
  } else if (confidence >= 0.6) {
    confEl.classList.add('text-yellow-700');
  } else {
    confEl.classList.add('text-orange-700');
  }

  // Button event handlers
  clone.querySelector('.apply-btn').onclick = () => applyGSCRecommendation(recommendation, card);
  clone.querySelector('.details-btn').onclick = () => showGSCDetails(recommendation);
  clone.querySelector('.dismiss-btn').onclick = () => dismissGSCRecommendation(recommendation, card);

  return clone;
}

/**
 * Apply a recommendation
 */
async function applyGSCRecommendation(recommendation, cardElement) {
  const confirmMsg = `Apply this SEO recommendation?\n\n${recommendation.title}\n\nExpected Impact: ${recommendation.expected_impact}`;

  if (!confirm(confirmMsg)) {
    return;
  }

  const applyBtn = cardElement.querySelector('.apply-btn');
  const originalText = applyBtn.innerHTML;
  applyBtn.innerHTML = '<i class="fa-solid fa-spinner fa-spin mr-1"></i> Applying...';
  applyBtn.disabled = true;

  try {
    const response = await fetch('/account/google/gsc/apply-recommendation', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        recommendation_id: recommendation.id
      })
    });

    const data = await response.json();

    if (response.ok && data.ok) {
      // Success - animate card removal
      cardElement.style.transition = 'all 0.3s ease';
      cardElement.style.opacity = '0';
      cardElement.style.transform = 'translateX(20px)';

      setTimeout(() => {
        cardElement.remove();
        showSuccessMessage('✓ SEO recommendation applied successfully!');
      }, 300);

    } else {
      throw new Error(data.error || 'Failed to apply recommendation');
    }

  } catch (error) {
    console.error('Error applying GSC recommendation:', error);
    applyBtn.innerHTML = originalText;
    applyBtn.disabled = false;
    alert(`Failed to apply recommendation: ${error.message}`);
  }
}

/**
 * Show recommendation details
 */
function showGSCDetails(recommendation) {
  const detailsMsg = `
SEO RECOMMENDATION DETAILS

Title: ${recommendation.title}

Description: ${recommendation.description}

Expected Impact: ${recommendation.expected_impact}

Confidence: ${Math.round((recommendation.confidence || 0.75) * 100)}%

Category: ${recommendation.category}

${recommendation.data_points ? '\nKey Metrics:\n' + recommendation.data_points.join('\n') : ''}

${recommendation.action ? '\nAction: ' + JSON.stringify(recommendation.action, null, 2) : ''}
  `.trim();

  alert(detailsMsg);
}

/**
 * Dismiss a recommendation
 */
async function dismissGSCRecommendation(recommendation, cardElement) {
  const reason = prompt('Why are you dismissing this SEO recommendation? (optional)');

  if (reason === null) return; // User cancelled

  const dismissBtn = cardElement.querySelector('.dismiss-btn');
  dismissBtn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i>';
  dismissBtn.disabled = true;

  try {
    const response = await fetch('/account/google/gsc/dismiss-recommendation', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        recommendation_id: recommendation.id,
        reason: reason
      })
    });

    const data = await response.json();

    if (response.ok && data.ok) {
      // Success - fade out card
      cardElement.style.transition = 'all 0.3s ease';
      cardElement.style.opacity = '0.5';
      cardElement.style.filter = 'grayscale(100%)';

      setTimeout(() => {
        cardElement.remove();
      }, 300);

    } else {
      throw new Error(data.error || 'Failed to dismiss recommendation');
    }

  } catch (error) {
    console.error('Error dismissing GSC recommendation:', error);
    dismissBtn.innerHTML = '<i class="fa-solid fa-times"></i>';
    dismissBtn.disabled = false;
    alert(`Failed to dismiss recommendation: ${error.message}`);
  }
}

/**
 * Toggle section expand/collapse
 */
function toggleGSCSection(sectionName) {
  const cards = document.getElementById(`${sectionName}Cards`);
  const chevron = document.getElementById(`${sectionName}Chevron`);

  cards.classList.toggle('hidden');
  chevron.classList.toggle('rotate-180');
}

/**
 * Close the insights modal
 */
function closeGSCInsightsModal() {
  const modal = document.getElementById('gscInsightsModal');
  modal.classList.add('hidden');

  // Reset state for next open
  setTimeout(() => {
    document.getElementById('gscInsightsLoading').classList.remove('hidden');
    document.getElementById('gscInsightsResults').classList.add('hidden');

    // Reset loading steps
    ['gscStep1', 'gscStep2', 'gscStep3', 'gscStep4'].forEach((stepId, i) => {
      const step = document.getElementById(stepId);
      step.className = 'flex items-center gap-3 text-sm text-gray-400 transition-all duration-300';
      const messages = [
        'Reviewing search rankings...',
        'Analyzing click-through rates...',
        'Finding SEO opportunities...',
        'Generating recommendations...'
      ];
      step.innerHTML = `<i class="fa-regular fa-circle"></i> <span>${messages[i]}</span>`;
    });

    // Clear all categories
    ['gscCritical', 'gscHighImpact', 'gscQuickWins', 'gscLongTerm'].forEach(cat => {
      document.getElementById(`${cat}Section`).classList.add('hidden');
      document.getElementById(`${cat}Cards`).innerHTML = '';
    });

    document.getElementById('gscNoRecommendations').classList.add('hidden');
  }, 300);
}

/**
 * Show error message
 */
function showGSCError(message) {
  document.getElementById('gscInsightsLoading').classList.add('hidden');
  document.getElementById('gscInsightsResults').classList.remove('hidden');

  const resultsContainer = document.getElementById('gscInsightsResults');
  resultsContainer.innerHTML = `
    <div class="p-12 text-center">
      <i class="fa-solid fa-exclamation-circle text-5xl text-red-600 mb-4"></i>
      <h3 class="text-lg font-semibold text-gray-900 mb-2">Unable to Generate SEO Insights</h3>
      <p class="text-gray-600 mb-4">${message}</p>
      <button onclick="closeGSCInsightsModal()" class="px-6 py-2 bg-emerald-600 text-white rounded-lg hover:bg-emerald-700">
        Close
      </button>
    </div>
  `;
}

/**
 * Show success message (toast notification)
 */
function showSuccessMessage(message) {
  const toast = document.createElement('div');
  toast.className = 'fixed top-4 right-4 bg-green-600 text-white px-6 py-3 rounded-lg shadow-lg z-50 animate-slideIn';
  toast.innerHTML = `<i class="fa-solid fa-check-circle mr-2"></i> ${message}`;
  document.body.appendChild(toast);

  setTimeout(() => {
    toast.style.opacity = '0';
    toast.style.transform = 'translateY(-20px)';
    setTimeout(() => toast.remove(), 300);
  }, 3000);
}

/**
 * Export insights as PDF/CSV (placeholder)
 */
function exportGSCInsights() {
  alert('Export functionality coming soon!');
}

// Close modal on escape key
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') {
    const modal = document.getElementById('gscInsightsModal');
    if (modal && !modal.classList.contains('hidden')) {
      closeGSCInsightsModal();
    }
  }
});

// Close modal on background click
document.addEventListener('click', (e) => {
  if (e.target.id === 'gscInsightsModal') {
    closeGSCInsightsModal();
  }
});
