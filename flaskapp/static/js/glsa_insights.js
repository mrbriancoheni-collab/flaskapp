// static/js/glsa_insights.js
// Google Local Services Ads AI Insights Modal - Progressive Loading & Interaction

/**
 * Main entry point - called when user clicks "Generate Insights" button
 */
async function generateGLSAInsights(profileData) {
  // Open modal
  const modal = document.getElementById('glsaInsightsModal');
  modal.classList.remove('hidden');

  // Show loading state
  document.getElementById('glsaInsightsLoading').classList.remove('hidden');
  document.getElementById('glsaInsightsResults').classList.add('hidden');

  // Start progressive loading animation
  const loadingPromise = simulateGLSALoadingSteps();

  try {
    // Fetch insights from API
    const response = await fetch('/account/glsa/optimize/insights.json', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        profile: profileData,
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
    document.getElementById('glsaInsightsLoading').classList.add('hidden');
    document.getElementById('glsaInsightsResults').classList.remove('hidden');

    // Display insights
    displayGLSAInsights(data);

  } catch (error) {
    console.error('Error generating GLSA insights:', error);
    await loadingPromise; // Wait for animation
    showGLSAError(error.message || 'Failed to generate insights. Please try again.');
  }
}

/**
 * Simulate progressive loading steps with animations
 */
async function simulateGLSALoadingSteps() {
  const steps = ['glsaStep1', 'glsaStep2', 'glsaStep3', 'glsaStep4'];
  const messages = [
    'Reviewing categories and service areas...',
    'Analyzing reviews and reputation...',
    'Checking budget and lead goals...',
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
      nextStep.innerHTML = `<i class="fa-solid fa-spinner fa-spin text-purple-600"></i> <span>${messages[i + 1]}</span>`;
      nextStep.classList.remove('text-gray-400');
      nextStep.classList.add('text-gray-500');
    }

    // Update loading message
    document.getElementById('glsaLoadingMessage').textContent = messages[i];
  }

  // Final pause before showing results
  await new Promise(resolve => setTimeout(resolve, 300));
}

/**
 * Display insights in categorized sections
 */
function displayGLSAInsights(data) {
  // Set summary
  document.getElementById('glsaInsightsSummary').textContent = data.summary || 'Analysis complete.';

  // Get recommendations
  const recommendations = data.recommendations || [];

  if (recommendations.length === 0) {
    document.getElementById('glsaNoRecommendations').classList.remove('hidden');
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
  displayGLSACategory('glsaCritical', categories.critical, {
    icon: 'fa-exclamation-triangle',
    color: 'red'
  });

  displayGLSACategory('glsaHighImpact', categories.highImpact, {
    icon: 'fa-rocket',
    color: 'orange'
  });

  displayGLSACategory('glsaQuickWins', categories.quickWins, {
    icon: 'fa-bolt',
    color: 'green'
  });

  displayGLSACategory('glsaLongTerm', categories.longTerm, {
    icon: 'fa-chess',
    color: 'blue'
  });
}

/**
 * Display a category of recommendations
 */
function displayGLSACategory(categoryName, recommendations, options) {
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
    const card = createGLSAInsightCard(rec, options);
    cards.appendChild(card);
  });

  // Auto-expand critical and high-impact sections
  if (categoryName === 'glsaCritical' || categoryName === 'glsaHighImpact') {
    cards.classList.remove('hidden');
  }
}

/**
 * Create an insight card from template
 */
function createGLSAInsightCard(recommendation, options) {
  const template = document.getElementById('glsaInsightCardTemplate');
  const clone = template.content.cloneNode(true);
  const card = clone.querySelector('.border');

  // Icon based on category
  const iconMap = {
    'categories': 'fa-tags',
    'service_areas': 'fa-map-marked-alt',
    'reviews': 'fa-star',
    'budget': 'fa-dollar-sign',
    'profile': 'fa-user-circle',
    'responsiveness': 'fa-clock'
  };

  const iconClass = iconMap[recommendation.category] || options.icon || 'fa-wrench';
  clone.querySelector('.glsa-insight-icon').className = `glsa-insight-icon text-xl fa-solid ${iconClass} text-${options.color}-600`;

  // Content
  clone.querySelector('.glsa-insight-title').textContent = recommendation.title || 'Untitled';
  clone.querySelector('.glsa-insight-description').textContent = recommendation.description || '';
  clone.querySelector('.glsa-insight-impact').textContent = recommendation.expected_impact || 'Impact pending';

  // Confidence
  const confidence = recommendation.confidence || 0.75;
  const confidencePercent = Math.round(confidence * 100);
  clone.querySelector('.glsa-insight-confidence').textContent = `${confidencePercent}%`;
  clone.querySelector('.glsa-insight-confidence-bar').style.width = `${confidencePercent}%`;

  // Color code confidence
  const confEl = clone.querySelector('.glsa-insight-confidence');
  if (confidence >= 0.8) {
    confEl.classList.add('text-green-700');
  } else if (confidence >= 0.6) {
    confEl.classList.add('text-yellow-700');
  } else {
    confEl.classList.add('text-orange-700');
  }

  // Button event handlers
  clone.querySelector('.apply-btn').onclick = () => applyGLSARecommendation(recommendation, card);
  clone.querySelector('.details-btn').onclick = () => showGLSADetails(recommendation);
  clone.querySelector('.dismiss-btn').onclick = () => dismissGLSARecommendation(recommendation, card);

  return clone;
}

/**
 * Apply a recommendation
 */
async function applyGLSARecommendation(recommendation, cardElement) {
  const confirmMsg = `Apply this Local Services Ads recommendation?\n\n${recommendation.title}\n\nExpected Impact: ${recommendation.expected_impact}`;

  if (!confirm(confirmMsg)) {
    return;
  }

  const applyBtn = cardElement.querySelector('.apply-btn');
  const originalText = applyBtn.innerHTML;
  applyBtn.innerHTML = '<i class="fa-solid fa-spinner fa-spin mr-1"></i> Applying...';
  applyBtn.disabled = true;

  try {
    const response = await fetch('/account/glsa/optimize/apply-recommendation', {
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
        showSuccessMessage('✓ LSA recommendation applied successfully!');
      }, 300);

    } else {
      throw new Error(data.error || 'Failed to apply recommendation');
    }

  } catch (error) {
    console.error('Error applying GLSA recommendation:', error);
    applyBtn.innerHTML = originalText;
    applyBtn.disabled = false;
    alert(`Failed to apply recommendation: ${error.message}`);
  }
}

/**
 * Show recommendation details
 */
function showGLSADetails(recommendation) {
  const detailsMsg = `
LSA RECOMMENDATION DETAILS

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
async function dismissGLSARecommendation(recommendation, cardElement) {
  const reason = prompt('Why are you dismissing this LSA recommendation? (optional)');

  if (reason === null) return; // User cancelled

  const dismissBtn = cardElement.querySelector('.dismiss-btn');
  dismissBtn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i>';
  dismissBtn.disabled = true;

  try {
    const response = await fetch('/account/glsa/optimize/dismiss-recommendation', {
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
    console.error('Error dismissing GLSA recommendation:', error);
    dismissBtn.innerHTML = '<i class="fa-solid fa-times"></i>';
    dismissBtn.disabled = false;
    alert(`Failed to dismiss recommendation: ${error.message}`);
  }
}

/**
 * Toggle section expand/collapse
 */
function toggleGLSASection(sectionName) {
  const cards = document.getElementById(`${sectionName}Cards`);
  const chevron = document.getElementById(`${sectionName}Chevron`);

  cards.classList.toggle('hidden');
  chevron.classList.toggle('rotate-180');
}

/**
 * Close the insights modal
 */
function closeGLSAInsightsModal() {
  const modal = document.getElementById('glsaInsightsModal');
  modal.classList.add('hidden');

  // Reset state for next open
  setTimeout(() => {
    document.getElementById('glsaInsightsLoading').classList.remove('hidden');
    document.getElementById('glsaInsightsResults').classList.add('hidden');

    // Reset loading steps
    ['glsaStep1', 'glsaStep2', 'glsaStep3', 'glsaStep4'].forEach((stepId, i) => {
      const step = document.getElementById(stepId);
      step.className = 'flex items-center gap-3 text-sm text-gray-400 transition-all duration-300';
      const messages = [
        'Reviewing categories and service areas...',
        'Analyzing reviews and reputation...',
        'Checking budget and lead goals...',
        'Generating recommendations...'
      ];
      step.innerHTML = `<i class="fa-regular fa-circle"></i> <span>${messages[i]}</span>`;
    });

    // Clear all categories
    ['glsaCritical', 'glsaHighImpact', 'glsaQuickWins', 'glsaLongTerm'].forEach(cat => {
      document.getElementById(`${cat}Section`).classList.add('hidden');
      document.getElementById(`${cat}Cards`).innerHTML = '';
    });

    document.getElementById('glsaNoRecommendations').classList.add('hidden');
  }, 300);
}

/**
 * Show error message
 */
function showGLSAError(message) {
  document.getElementById('glsaInsightsLoading').classList.add('hidden');
  document.getElementById('glsaInsightsResults').classList.remove('hidden');

  const resultsContainer = document.getElementById('glsaInsightsResults');
  resultsContainer.innerHTML = `
    <div class="p-12 text-center">
      <i class="fa-solid fa-exclamation-circle text-5xl text-red-600 mb-4"></i>
      <h3 class="text-lg font-semibold text-gray-900 mb-2">Unable to Generate LSA Insights</h3>
      <p class="text-gray-600 mb-4">${message}</p>
      <button onclick="closeGLSAInsightsModal()" class="px-6 py-2 bg-purple-600 text-white rounded-lg hover:bg-purple-700">
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
function exportGLSAInsights() {
  alert('Export functionality coming soon!');
}

// Close modal on escape key
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') {
    const modal = document.getElementById('glsaInsightsModal');
    if (modal && !modal.classList.contains('hidden')) {
      closeGLSAInsightsModal();
    }
  }
});

// Close modal on background click
document.addEventListener('click', (e) => {
  if (e.target.id === 'glsaInsightsModal') {
    closeGLSAInsightsModal();
  }
});
