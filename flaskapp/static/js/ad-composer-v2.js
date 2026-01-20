/**
 * Ad Composer V2 - Enterprise UI/UX
 * Toast notifications, progressive loading, cost estimation, platform previews
 */

class AdComposerV2 {
    constructor() {
        this.currentCreativeId = null;
        this.currentStep = 0;
        this.totalSteps = 4;
        this.estimatedTime = 20; // seconds
        this.startTime = null;

        this.steps = [
            { id: 'context', label: 'Analyzing business context...', progress: 0 },
            { id: 'copy', label: 'Generating ad copy...', progress: 25 },
            { id: 'images', label: 'Creating images...', progress: 50 },
            { id: 'finalize', label: 'Finalizing creative...', progress: 90 }
        ];

        this.init();
    }

    init() {
        // Initialize generation mode
        this.setGenerationMode('website');

        // Listen for input changes to update cost estimate
        ['image-variations', 'platform', 'image-size'].forEach(id => {
            const el = document.getElementById(id);
            if (el) {
                el.addEventListener('change', () => this.updateCostEstimate());
            }
        });

        // Initial cost calculation
        this.updateCostEstimate();
    }

    // ==================== TOAST NOTIFICATIONS ====================

    showToast(message, type = 'success', duration = 4000) {
        const toast = document.createElement('div');
        toast.className = `fixed top-4 right-4 px-6 py-4 rounded-lg shadow-2xl z-50 transform transition-all duration-300 translate-x-0 ${
            type === 'success' ? 'bg-green-500' :
            type === 'error' ? 'bg-red-500' :
            type === 'warning' ? 'bg-amber-500' :
            type === 'info' ? 'bg-blue-500' : 'bg-gray-500'
        } text-white max-w-md`;

        const icons = {
            success: '<path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z"/>',
            error: '<path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z"/>',
            warning: '<path fill-rule="evenodd" d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z"/>',
            info: '<path fill-rule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7-4a1 1 0 11-2 0 1 1 0 012 0zM9 9a1 1 0 000 2v3a1 1 0 001 1h1a1 1 0 100-2v-3a1 1 0 00-1-1H9z"/>'
        };

        toast.innerHTML = `
            <div class="flex items-center gap-3">
                <svg class="w-6 h-6 flex-shrink-0" fill="currentColor" viewBox="0 0 20 20">
                    ${icons[type] || icons.info}
                </svg>
                <div class="flex-1">
                    <p class="font-medium">${message}</p>
                </div>
                <button onclick="this.parentElement.parentElement.remove()" class="ml-2 opacity-70 hover:opacity-100">
                    <svg class="w-5 h-5" fill="currentColor" viewBox="0 0 20 20">
                        <path fill-rule="evenodd" d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z"/>
                    </svg>
                </button>
            </div>
        `;

        document.body.appendChild(toast);

        // Slide in
        requestAnimationFrame(() => {
            toast.style.transform = 'translateX(0)';
        });

        // Auto dismiss
        setTimeout(() => {
            toast.style.transform = 'translateX(400px)';
            toast.style.opacity = '0';
            setTimeout(() => toast.remove(), 300);
        }, duration);
    }

    // ==================== COST ESTIMATION ====================

    updateCostEstimate() {
        const variations = parseInt(document.getElementById('image-variations')?.value || 1);

        // DALL-E 3 HD pricing
        const imageCost = 0.08; // per image
        const copyCost = 0.01; // Claude Sonnet estimate

        const totalImageCost = variations * imageCost;
        const totalCost = totalImageCost + copyCost;

        // Update UI
        const costEl = document.getElementById('generation-cost');
        const variationCostEl = document.getElementById('variation-cost');
        const totalCostEl = document.getElementById('total-cost');

        if (costEl) costEl.textContent = `$${imageCost.toFixed(2)}`;
        if (variationCostEl) variationCostEl.textContent = variations > 1 ? `+$${((variations - 1) * imageCost).toFixed(2)} per variation` : 'No variations';
        if (totalCostEl) totalCostEl.textContent = `$${totalCost.toFixed(2)}`;

        return { imageCost: totalImageCost, copyCost, totalCost };
    }

    // ==================== PROGRESSIVE LOADING ====================

    showProgressiveLoading() {
        document.getElementById('initial-state')?.classList.add('hidden');
        document.getElementById('preview-editor')?.classList.add('hidden');
        document.getElementById('loading-state')?.classList.add('hidden');
        document.getElementById('generation-progress')?.classList.remove('hidden');

        this.currentStep = 0;
        this.startTime = Date.now();
        this.updateProgressStep(0);

        // Simulate realistic timing
        this.progressInterval = setInterval(() => {
            if (this.currentStep < this.totalSteps - 1) {
                this.updateProgressStep(this.currentStep + 1);
            }
        }, this.estimatedTime * 250); // Spread across estimated time
    }

    updateProgressStep(stepIndex) {
        this.currentStep = stepIndex;
        const step = this.steps[stepIndex];

        // Update progress bar
        const progressBar = document.getElementById('progress-bar');
        const progressPercent = document.getElementById('progress-percent');

        if (progressBar) progressBar.style.width = `${step.progress}%`;
        if (progressPercent) progressPercent.textContent = `${step.progress}%`;

        // Update step indicators
        this.steps.forEach((s, i) => {
            const el = document.getElementById(`step-${i + 1}`);
            if (!el) return;

            el.classList.remove('opacity-50', 'opacity-100');

            if (i < stepIndex) {
                // Completed
                el.classList.add('opacity-100');
                el.querySelector('.w-6').classList.add('bg-primary-600', 'border-primary-600');
                el.querySelector('.w-2')?.classList.remove('hidden');
            } else if (i === stepIndex) {
                // Current
                el.classList.add('opacity-100');
                el.querySelector('.w-6').classList.add('border-primary-600', 'animate-pulse');
            } else {
                // Pending
                el.classList.add('opacity-50');
            }
        });

        // Update estimated time
        const elapsed = (Date.now() - this.startTime) / 1000;
        const remaining = Math.max(0, this.estimatedTime - elapsed);
        const estimatedTimeEl = document.getElementById('estimated-time');
        if (estimatedTimeEl) {
            estimatedTimeEl.textContent = `${Math.ceil(remaining)} seconds remaining`;
        }
    }

    completeProgress() {
        clearInterval(this.progressInterval);
        this.updateProgressStep(this.totalSteps - 1);

        setTimeout(() => {
            document.getElementById('generation-progress')?.classList.add('hidden');
        }, 500);
    }

    // ==================== GENERATION MODE ====================

    setGenerationMode(mode) {
        // Update button states
        document.querySelectorAll('.generation-mode-btn').forEach(btn => {
            btn.classList.remove('active', 'border-primary-500', 'bg-primary-50');
            btn.classList.add('border-gray-200');
        });

        const activeBtn = document.querySelector(`[data-mode="${mode}"]`);
        if (activeBtn) {
            activeBtn.classList.add('active', 'border-primary-500', 'bg-primary-50');
            activeBtn.classList.remove('border-gray-200');
        }

        // Show/hide input panels
        const websitePanel = document.getElementById('website-input-panel');
        const manualPanel = document.getElementById('manual-input-panel');

        if (mode === 'website') {
            websitePanel?.classList.remove('hidden');
            manualPanel?.classList.add('hidden');
        } else {
            websitePanel?.classList.add('hidden');
            manualPanel?.classList.remove('hidden');
        }
    }

    // ==================== AD GENERATION ====================

    async generateAd() {
        const mode = document.querySelector('.generation-mode-btn.active')?.dataset.mode || 'website';
        const platform = document.getElementById('platform')?.value || 'facebook';
        const objective = document.getElementById('objective')?.value || 'leads';
        const industry = document.getElementById('industry')?.value || '';
        const style = document.getElementById('image-style')?.value || 'professional';
        const imageSize = document.getElementById('image-size')?.value || 'square';
        const imageVariations = parseInt(document.getElementById('image-variations')?.value || 1);

        let requestData = {
            platform,
            objective,
            industry,
            style,
            image_size: imageSize,
            image_variations: imageVariations
        };

        // Validate and get inputs based on mode
        if (mode === 'website') {
            const websiteUrl = document.getElementById('website-url')?.value?.trim();
            if (!websiteUrl) {
                this.showToast('Please enter a website URL', 'error');
                return;
            }
            requestData.website_url = websiteUrl;
        } else {
            const businessName = document.getElementById('business-name')?.value?.trim();
            const services = document.getElementById('services')?.value?.trim();
            if (!businessName) {
                this.showToast('Please enter a business name', 'error');
                return;
            }
            requestData.business_name = businessName;
            requestData.services = services.split(',').map(s => s.trim()).filter(Boolean);
        }

        // Show progressive loading
        this.showProgressiveLoading();

        try {
            const endpoint = mode === 'website' ? '/social/api/generate-from-website' : '/social/api/generate-from-manual';

            const response = await fetch(endpoint, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': document.querySelector('meta[name="csrf-token"]')?.content || ''
                },
                body: JSON.stringify(requestData)
            });

            const data = await response.json();

            this.completeProgress();

            if (data.success) {
                this.displayCreative(data.creative || data, data.image_variations);
                this.currentCreativeId = data.creative_id || null;
                this.showToast('Ad creative generated successfully!', 'success');

                // Track analytics
                this.trackGeneration(data);
            } else {
                this.showToast(data.error || 'Generation failed', 'error');
                document.getElementById('initial-state')?.classList.remove('hidden');
            }
        } catch (error) {
            console.error('Generation error:', error);
            this.showToast('An error occurred while generating the ad', 'error');
            this.completeProgress();
            document.getElementById('initial-state')?.classList.remove('hidden');
        }
    }

    // ==================== DISPLAY CREATIVE ====================

    displayCreative(creative, imageVariations) {
        document.getElementById('loading-state')?.classList.add('hidden');
        document.getElementById('generation-progress')?.classList.add('hidden');
        document.getElementById('preview-editor')?.classList.remove('hidden');

        // Update preview
        const previewImage = document.getElementById('preview-image');
        if (previewImage) previewImage.src = creative.image_url || '';

        // Update editable fields
        document.getElementById('edit-headline').value = creative.headline || '';
        document.getElementById('edit-primary').value = creative.primary_text || '';
        document.getElementById('edit-description').value = creative.description || '';
        document.getElementById('edit-cta').value = creative.call_to_action || '';

        // Update platform mockup
        this.updatePlatformMockup(creative);

        // Handle image variations
        this.displayImageVariations(imageVariations);

        // Show performance prediction if available
        if (creative.performance_prediction) {
            this.displayPerformancePrediction(creative.performance_prediction);
        }
    }

    displayImageVariations(variations) {
        const container = document.getElementById('image-variations-container');
        const grid = document.getElementById('image-variations-grid');

        if (!variations || variations.length <= 1) {
            container?.classList.add('hidden');
            return;
        }

        container?.classList.remove('hidden');
        if (grid) grid.innerHTML = '';

        variations.forEach((variation, index) => {
            const varDiv = document.createElement('div');
            varDiv.className = 'relative cursor-pointer border-2 border-gray-200 rounded-lg overflow-hidden hover:border-primary-500 transition-colors';
            varDiv.onclick = () => this.selectImageVariation(variation.image_url, index);

            varDiv.innerHTML = `
                <img src="${variation.image_url}" alt="Variation ${index + 1}" class="w-full h-32 object-cover">
                <div class="absolute bottom-0 left-0 right-0 bg-black bg-opacity-60 text-white text-xs text-center py-1">
                    Variation ${index + 1}
                </div>
                ${index === 0 ? '<div class="absolute top-2 right-2 bg-primary-600 text-white text-xs px-2 py-1 rounded">Selected</div>' : ''}
            `;

            grid?.appendChild(varDiv);
        });
    }

    selectImageVariation(imageUrl, index) {
        const previewImage = document.getElementById('preview-image');
        if (previewImage) previewImage.src = imageUrl;

        // Update selection indicators
        const grid = document.getElementById('image-variations-grid');
        if (grid) {
            grid.querySelectorAll('.bg-primary-600').forEach(el => el.remove());
            const selected = grid.children[index];
            if (selected) {
                const badge = document.createElement('div');
                badge.className = 'absolute top-2 right-2 bg-primary-600 text-white text-xs px-2 py-1 rounded';
                badge.textContent = 'Selected';
                selected.appendChild(badge);
            }
        }

        this.showToast(`Variation ${index + 1} selected`, 'info', 2000);
    }

    // ==================== PLATFORM MOCKUP ====================

    updatePlatformMockup(creative) {
        const platform = document.getElementById('platform')?.value || 'facebook';
        const platformName = document.getElementById('platform-name');
        if (platformName) {
            platformName.textContent = platform.charAt(0).toUpperCase() + platform.slice(1);
        }

        // Update mockup elements if they exist
        document.getElementById('mockup-primary')textContent = creative.primary_text || '';
        document.getElementById('mockup-image')?.setAttribute('src', creative.image_url || '');
        const ctaBtn = document.getElementById('mockup-cta');
        if (ctaBtn) ctaBtn.textContent = creative.call_to_action || 'Learn More';
    }

    // ==================== SAVE & DOWNLOAD ====================

    async saveCreative() {
        const creativeData = {
            id: this.currentCreativeId,
            name: `Ad - ${new Date().toLocaleDateString()}`,
            platform: document.getElementById('platform')?.value,
            headline: document.getElementById('edit-headline')?.value,
            primary_text: document.getElementById('edit-primary')?.value,
            description: document.getElementById('edit-description')?.value,
            call_to_action: document.getElementById('edit-cta')?.value,
            image_url: document.getElementById('preview-image')?.src
        };

        try {
            const response = await fetch('/social/api/save-creative', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': document.querySelector('meta[name="csrf-token"]')?.content || ''
                },
                body: JSON.stringify(creativeData)
            });

            const data = await response.json();

            if (data.success) {
                this.showToast('Creative saved successfully!', 'success');
                this.currentCreativeId = data.creative_id;
                this.trackSave(data.creative_id);
            } else {
                this.showToast(data.error || 'Failed to save', 'error');
            }
        } catch (error) {
            console.error('Save error:', error);
            this.showToast('An error occurred while saving', 'error');
        }
    }

    toggleDownloadMenu() {
        const menu = document.getElementById('download-menu');
        menu?.classList.toggle('hidden');
    }

    async downloadImage(format, quality) {
        const imageUrl = document.getElementById('preview-image')?.src;
        if (!imageUrl) {
            this.showToast('No image to download', 'error');
            return;
        }

        this.showToast(`Downloading ${format.toUpperCase()} (${quality} quality)...`, 'info', 2000);

        try {
            // Download the image
            const response = await fetch(imageUrl);
            const blob = await response.blob();

            const url = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `ad-creative-${Date.now()}.${format}`;
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            window.URL.revokeObjectURL(url);

            this.showToast('Download started!', 'success');
            this.trackDownload(format, quality);
        } catch (error) {
            console.error('Download error:', error);
            this.showToast('Download failed', 'error');
        }
    }

    async downloadAllVariations() {
        this.showToast('Preparing all variations for download...', 'info');
        // Implementation for ZIP download
    }

    // ==================== ANALYTICS ====================

    trackGeneration(data) {
        // Track to Google Analytics
        if (window.gtag) {
            gtag('event', 'ad_generated', {
                platform: data.platform,
                variations: data.image_variations?.length || 1,
                cost: this.updateCostEstimate().totalCost
            });
        }

        // Track to backend
        this.sendAnalyticsEvent('ad_generated', {
            creative_id: data.creative_id,
            platform: data.platform,
            industry: document.getElementById('industry')?.value,
            generation_method: 'website',
            image_count: data.image_variations?.length || 1,
            ai_cost: this.updateCostEstimate().totalCost
        });
    }

    trackSave(creativeId) {
        // Track to Google Analytics
        if (window.gtag) {
            gtag('event', 'creative_saved', {
                creative_id: creativeId
            });
        }

        // Track to backend
        this.sendAnalyticsEvent('creative_saved', {
            creative_id: creativeId
        });
    }

    trackDownload(format, quality) {
        // Track to Google Analytics
        if (window.gtag) {
            gtag('event', 'image_downloaded', {
                format,
                quality
            });
        }

        // Track to backend
        this.sendAnalyticsEvent('image_downloaded', {
            creative_id: this.currentCreativeId,
            event_data: { format, quality }
        });
    }

    async sendAnalyticsEvent(eventType, data = {}) {
        try {
            const response = await fetch('/social/api/analytics/track', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': document.querySelector('meta[name="csrf-token"]')?.content || ''
                },
                body: JSON.stringify({
                    event_type: eventType,
                    ...data
                })
            });

            if (!response.ok) {
                console.warn('Analytics tracking failed:', await response.text());
            }
        } catch (error) {
            // Silently fail - don't disrupt user experience
            console.warn('Analytics tracking error:', error);
        }
    }

    // ==================== PERFORMANCE PREDICTION ====================

    displayPerformancePrediction(prediction) {
        const container = document.getElementById('performance-prediction');
        if (!container) return;

        container.innerHTML = `
            <div class="bg-gradient-to-br from-purple-50 to-blue-50 rounded-lg p-6 border border-purple-200 mt-6">
                <div class="flex items-center gap-3 mb-4">
                    <div class="w-10 h-10 bg-purple-600 rounded-full flex items-center justify-center">
                        <svg class="w-6 h-6 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 7h8m0 0v8m0-8l-8 8-4-4-6 6"/>
                        </svg>
                    </div>
                    <div>
                        <h3 class="font-semibold text-gray-900">Performance Prediction</h3>
                        <p class="text-xs text-gray-600">AI-powered forecast</p>
                    </div>
                </div>

                <div class="grid grid-cols-3 gap-3 mb-4">
                    <div class="bg-white rounded-lg p-3 text-center">
                        <p class="text-xs text-gray-500 mb-1">Est. CTR</p>
                        <p class="text-lg font-bold text-green-600">${(prediction.estimated_ctr * 100).toFixed(1)}%</p>
                        <p class="text-xs text-gray-400">Industry avg: 1.9%</p>
                    </div>
                    <div class="bg-white rounded-lg p-3 text-center">
                        <p class="text-xs text-gray-500 mb-1">Est. Engagement</p>
                        <p class="text-lg font-bold text-blue-600">${(prediction.estimated_engagement * 100).toFixed(1)}%</p>
                        <p class="text-xs text-gray-400">Industry avg: 4.1%</p>
                    </div>
                    <div class="bg-white rounded-lg p-3 text-center">
                        <p class="text-xs text-gray-500 mb-1">Quality Score</p>
                        <p class="text-lg font-bold text-purple-600">${prediction.quality_score}/10</p>
                        <p class="text-xs text-gray-400">Excellent</p>
                    </div>
                </div>

                ${prediction.recommendations ? `
                <div class="bg-white rounded-lg p-3">
                    <p class="text-xs font-medium text-gray-700 mb-2">AI Recommendations:</p>
                    <ul class="space-y-1">
                        ${prediction.recommendations.map(rec => `
                            <li class="text-xs text-gray-600 flex items-start gap-2">
                                <svg class="w-4 h-4 ${rec.type === 'success' ? 'text-green-500' : 'text-amber-500'} flex-shrink-0 mt-0.5" fill="currentColor" viewBox="0 0 20 20">
                                    ${rec.type === 'success' ?
                                        '<path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z"/>' :
                                        '<path fill-rule="evenodd" d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z"/>'
                                    }
                                </svg>
                                <span>${rec.message}</span>
                            </li>
                        `).join('')}
                    </ul>
                </div>
                ` : ''}
            </div>
        `;

        container.classList.remove('hidden');
    }
}

// Initialize on page load
document.addEventListener('DOMContentLoaded', () => {
    window.adComposer = new AdComposerV2();
});

// Export for global access
window.setGenerationMode = (mode) => window.adComposer?.setGenerationMode(mode);
window.generateAd = () => window.adComposer?.generateAd();
window.saveCreative = () => window.adComposer?.saveCreative();
window.toggleDownloadMenu = () => window.adComposer?.toggleDownloadMenu();
window.downloadImage = (format, quality) => window.adComposer?.downloadImage(format, quality);
window.downloadAllVariations = () => window.adComposer?.downloadAllVariations();
