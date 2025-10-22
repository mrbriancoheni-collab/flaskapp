// static/js/google_ads_insights.js
// AI Optimization Insights Modal - Progressive Loading & Interaction

/**
 * Main entry point - called when user clicks "AI Optimize" button
 */
async function aiOptimize() {
  // Open modal
  const modal = document.getElementById('insightsModal');
  modal.classList.remove('hidden');

  // Show loading state
  document.getElementById('insightsLoading').classList.remove('hidden');
  document.getElementById('insightsResults').classList.add('hidden');

  // Start progressive loading animation
  const loadingPromise = simulateLoadingSteps();

  try {
    // Fetch insights from API
    const response = await fetch('/account/google/ads/optimize.json', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        scope: 'all',
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
    document.getElementById('insightsLoading').classList.add('hidden');
    document.getElementById('insightsResults').classList.remove('hidden');

    // Display insights
    displayInsights(data);

  } catch (error) {
    console.error('Error generating insights:', error);
    await loadingPromise; // Wait for animation
    showError(error.message || 'Failed to generate insights. Please try again.');
  }
}

/**
 * Simulate progressive loading steps with animations
 */
async function simulateLoadingSteps() {
  const steps = ['step1', 'step2', 'step3', 'step4'];
  const messages = [
    'Reviewing campaign performance...',
    'Analyzing keyword data...',
    'Checking budget efficiency...',
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
      nextStep.innerHTML = `<i class="fa-solid fa-spinner fa-spin text-indigo-600"></i> <span>${messages[i + 1]}</span>`;
      nextStep.classList.remove('text-gray-400');
      nextStep.classList.add('text-gray-500');
    }

    // Update loading message
    document.getElementById('loadingMessage').textContent = messages[i];
  }

  // Final pause before showing results
  await new Promise(resolve => setTimeout(resolve, 300));
}

/**
 * Display insights in categorized sections
 */
function displayInsights(data) {
  // Set summary
  document.getElementById('insightsSummary').textContent = data.summary || 'Analysis complete.';

  // Get recommendations
  const recommendations = data.recommendations || [];

  if (recommendations.length === 0) {
    document.getElementById('noRecommendations').classList.remove('hidden');
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
  displayCategory('critical', categories.critical, {
    icon: 'fa-exclamation-triangle',
    color: 'red'
  });

  displayCategory('highImpact', categories.highImpact, {
    icon: 'fa-rocket',
    color: 'orange'
  });

  displayCategory('quickWins', categories.quickWins, {
    icon: 'fa-bolt',
    color: 'green'
  });

  displayCategory('longTerm', categories.longTerm, {
    icon: 'fa-chess',
    color: 'blue'
  });
}

/**
 * Display a category of recommendations
 */
function displayCategory(categoryName, recommendations, options) {
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
    const card = createInsightCard(rec, options);
    cards.appendChild(card);
  });

  // Auto-expand critical and high-impact sections
  if (categoryName === 'critical' || categoryName === 'highImpact') {
    cards.classList.remove('hidden');
  }
}

/**
 * Create an insight card from template
 */
function createInsightCard(recommendation, options) {
  const template = document.getElementById('insightCardTemplate');
  const clone = template.content.cloneNode(true);
  const card = clone.querySelector('.border');

  // Icon based on category
  const iconMap = {
    'budget': 'fa-dollar-sign',
    'bidding': 'fa-gavel',
    'keywords': 'fa-key',
    'ads': 'fa-ad',
    'targeting': 'fa-bullseye',
    'negatives': 'fa-ban',
    'landing_pages': 'fa-file-alt'
  };

  const iconClass = iconMap[recommendation.category] || options.icon || 'fa-lightbulb';
  clone.querySelector('.insight-icon').className = `insight-icon text-xl fa-solid ${iconClass} text-${options.color}-600`;

  // Content
  clone.querySelector('.insight-title').textContent = recommendation.title || 'Untitled';
  clone.querySelector('.insight-description').textContent = recommendation.description || '';
  clone.querySelector('.insight-impact').textContent = recommendation.expected_impact || 'Impact pending';

  // Confidence
  const confidence = recommendation.confidence || 0.75;
  const confidencePercent = Math.round(confidence * 100);
  clone.querySelector('.insight-confidence').textContent = `${confidencePercent}%`;
  clone.querySelector('.insight-confidence-bar').style.width = `${confidencePercent}%`;

  // Color code confidence
  const confEl = clone.querySelector('.insight-confidence');
  if (confidence >= 0.8) {
    confEl.classList.add('text-green-700');
  } else if (confidence >= 0.6) {
    confEl.classList.add('text-yellow-700');
  } else {
    confEl.classList.add('text-orange-700');
  }

  // Button event handlers
  clone.querySelector('.apply-btn').onclick = () => applyRecommendation(recommendation, card);
  clone.querySelector('.details-btn').onclick = () => showDetails(recommendation);
  clone.querySelector('.dismiss-btn').onclick = () => dismissRecommendation(recommendation, card);

  return clone;
}

/**
 * Apply a recommendation
 */
async function applyRecommendation(recommendation, cardElement) {
  const confirmMsg = `Apply this recommendation?\n\n${recommendation.title}\n\nExpected Impact: ${recommendation.expected_impact}`;

  if (!confirm(confirmMsg)) {
    return;
  }

  const applyBtn = cardElement.querySelector('.apply-btn');
  const originalText = applyBtn.innerHTML;
  applyBtn.innerHTML = '<i class="fa-solid fa-spinner fa-spin mr-1"></i> Applying...';
  applyBtn.disabled = true;

  try {
    const response = await fetch('/account/google/ads/apply-recommendation', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        recommendation_id: recommendation.id,
        action: recommendation.action
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
        showSuccessMessage('✓ Recommendation applied successfully!');
      }, 300);

    } else {
      throw new Error(data.error || 'Failed to apply recommendation');
    }

  } catch (error) {
    console.error('Error applying recommendation:', error);
    applyBtn.innerHTML = originalText;
    applyBtn.disabled = false;
    alert(`Failed to apply recommendation: ${error.message}`);
  }
}

/**
 * Show recommendation details
 */
function showDetails(recommendation) {
  const detailsMsg = `
RECOMMENDATION DETAILS

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
async function dismissRecommendation(recommendation, cardElement) {
  const reason = prompt('Why are you dismissing this recommendation? (optional)');

  if (reason === null) return; // User cancelled

  const dismissBtn = cardElement.querySelector('.dismiss-btn');
  dismissBtn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i>';
  dismissBtn.disabled = true;

  try {
    const response = await fetch('/account/google/ads/dismiss-recommendation', {
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
    console.error('Error dismissing recommendation:', error);
    dismissBtn.innerHTML = '<i class="fa-solid fa-times"></i>';
    dismissBtn.disabled = false;
    alert(`Failed to dismiss recommendation: ${error.message}`);
  }
}

/**
 * Toggle section expand/collapse
 */
function toggleSection(sectionName) {
  const cards = document.getElementById(`${sectionName}Cards`);
  const chevron = document.getElementById(`${sectionName}Chevron`);

  cards.classList.toggle('hidden');
  chevron.classList.toggle('rotate-180');
}

/**
 * Close the insights modal
 */
function closeInsightsModal() {
  const modal = document.getElementById('insightsModal');
  modal.classList.add('hidden');

  // Reset state for next open
  setTimeout(() => {
    document.getElementById('insightsLoading').classList.remove('hidden');
    document.getElementById('insightsResults').classList.add('hidden');

    // Reset loading steps
    ['step1', 'step2', 'step3', 'step4'].forEach((stepId, i) => {
      const step = document.getElementById(stepId);
      step.className = 'flex items-center gap-3 text-sm text-gray-400 transition-all duration-300';
      const messages = [
        'Reviewing campaign performance...',
        'Analyzing keyword data...',
        'Checking budget efficiency...',
        'Generating recommendations...'
      ];
      step.innerHTML = `<i class="fa-regular fa-circle"></i> <span>${messages[i]}</span>`;
    });

    // Clear all categories
    ['critical', 'highImpact', 'quickWins', 'longTerm'].forEach(cat => {
      document.getElementById(`${cat}Section`).classList.add('hidden');
      document.getElementById(`${cat}Cards`).innerHTML = '';
    });

    document.getElementById('noRecommendations').classList.add('hidden');
  }, 300);
}

/**
 * Show error message
 */
function showError(message) {
  document.getElementById('insightsLoading').classList.add('hidden');
  document.getElementById('insightsResults').classList.remove('hidden');

  const resultsContainer = document.getElementById('insightsResults');
  resultsContainer.innerHTML = `
    <div class="p-12 text-center">
      <i class="fa-solid fa-exclamation-circle text-5xl text-red-600 mb-4"></i>
      <h3 class="text-lg font-semibold text-gray-900 mb-2">Unable to Generate Insights</h3>
      <p class="text-gray-600 mb-4">${message}</p>
      <button onclick="closeInsightsModal()" class="px-6 py-2 bg-indigo-600 text-white rounded-lg hover:bg-indigo-700">
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
function exportInsights() {
  alert('Export functionality coming soon!');
}

/**
 * Schedule review (placeholder)
 */
function scheduleReview() {
  alert('Schedule review functionality coming soon!');
}

// Close modal on escape key
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') {
    const modal = document.getElementById('insightsModal');
    if (modal && !modal.classList.contains('hidden')) {
      closeInsightsModal();
    }
  }
});

// Close modal on background click
document.addEventListener('click', (e) => {
  if (e.target.id === 'insightsModal') {
    closeInsightsModal();
  }
});
