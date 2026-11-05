<?php
/**
 * Template Name: Pricing Page
 */
get_header(); ?>

<main id="main">

    <section class="pricing-page-hero">
        <div class="container pricing-page-hero__inner">
            <h1 class="pricing-page-hero__title">Simple, honest pricing</h1>
            <p class="pricing-page-hero__sub">No setup fees. No long-term contracts. Cancel anytime. Start with a 14-day free trial — no credit card required.</p>

            <div class="pricing-toggle" id="pricing-toggle">
                <button class="toggle-btn toggle-btn--active" data-period="monthly" id="toggle-monthly">Monthly</button>
                <button class="toggle-btn" data-period="annual" id="toggle-annual">
                    Annual
                    <span class="save-badge" id="save-badge">Save 20%</span>
                </button>
            </div>
        </div>
    </section>

    <section class="pricing-cards-section">
        <div class="container">
            <div class="pricing-grid pricing-grid--full">

                <div class="pricing-card">
                    <div class="pricing-card__header">
                        <h3 class="pricing-card__plan">Starter</h3>
                        <p class="pricing-card__tagline">Perfect for a single-location contractor just starting with Google Ads</p>
                        <div class="pricing-card__price-wrap">
                            <span class="pricing-card__currency">$</span>
                            <span class="pricing-card__amount" data-monthly="49" data-annual="39">49</span>
                            <span class="pricing-card__period">/mo</span>
                        </div>
                        <p class="pricing-card__billing-note" id="starter-billing">Billed monthly</p>
                    </div>
                    <ul class="pricing-card__features">
                        <li><span class="check">✓</span> 1 Google Ads account</li>
                        <li><span class="check">✓</span> AI campaign monitoring</li>
                        <li><span class="check">✓</span> RSA copy generator</li>
                        <li><span class="check">✓</span> Negative keyword engine</li>
                        <li><span class="check">✓</span> Budget planner</li>
                        <li><span class="check">✓</span> Email support</li>
                        <li class="pricing-card__feature--muted"><span class="dash">–</span> Billboard Ads module</li>
                        <li class="pricing-card__feature--muted"><span class="dash">–</span> Multi-account management</li>
                        <li class="pricing-card__feature--muted"><span class="dash">–</span> White-label reports</li>
                    </ul>
                    <a href="<?php echo revforge_app_url(); ?>register?plan=starter" class="btn btn-outline btn-block">Start Free Trial</a>
                </div>

                <div class="pricing-card pricing-card--featured">
                    <div class="pricing-card__popular-badge">Most Popular</div>
                    <div class="pricing-card__header">
                        <h3 class="pricing-card__plan">Growth</h3>
                        <p class="pricing-card__tagline">For growing contractors who want to scale leads and add OOH</p>
                        <div class="pricing-card__price-wrap">
                            <span class="pricing-card__currency">$</span>
                            <span class="pricing-card__amount" data-monthly="99" data-annual="79">99</span>
                            <span class="pricing-card__period">/mo</span>
                        </div>
                        <p class="pricing-card__billing-note" id="growth-billing">Billed monthly</p>
                    </div>
                    <ul class="pricing-card__features">
                        <li><span class="check">✓</span> Up to 3 Google Ads accounts</li>
                        <li><span class="check">✓</span> AI campaign monitoring + autopilot</li>
                        <li><span class="check">✓</span> RSA copy generator</li>
                        <li><span class="check">✓</span> Negative keyword engine</li>
                        <li><span class="check">✓</span> Smart budget optimizer</li>
                        <li><span class="check">✓</span> <strong>Billboard Ads module</strong></li>
                        <li><span class="check">✓</span> Lead tracking dashboard</li>
                        <li><span class="check">✓</span> Priority email + chat support</li>
                        <li class="pricing-card__feature--muted"><span class="dash">–</span> White-label reports</li>
                    </ul>
                    <a href="<?php echo revforge_app_url(); ?>register?plan=growth" class="btn btn-primary btn-block">Start Free Trial</a>
                </div>

                <div class="pricing-card">
                    <div class="pricing-card__header">
                        <h3 class="pricing-card__plan">Agency</h3>
                        <p class="pricing-card__tagline">For agencies and multi-location contractors managing many accounts</p>
                        <div class="pricing-card__price-wrap">
                            <span class="pricing-card__currency">$</span>
                            <span class="pricing-card__amount" data-monthly="199" data-annual="159">199</span>
                            <span class="pricing-card__period">/mo</span>
                        </div>
                        <p class="pricing-card__billing-note" id="agency-billing">Billed monthly</p>
                    </div>
                    <ul class="pricing-card__features">
                        <li><span class="check">✓</span> Unlimited Google Ads accounts</li>
                        <li><span class="check">✓</span> AI campaign monitoring + autopilot</li>
                        <li><span class="check">✓</span> RSA copy generator (bulk)</li>
                        <li><span class="check">✓</span> Negative keyword engine</li>
                        <li><span class="check">✓</span> Smart budget optimizer</li>
                        <li><span class="check">✓</span> <strong>Billboard Ads module</strong></li>
                        <li><span class="check">✓</span> Lead tracking dashboard</li>
                        <li><span class="check">✓</span> <strong>White-label reports</strong></li>
                        <li><span class="check">✓</span> Dedicated account manager</li>
                    </ul>
                    <a href="<?php echo revforge_app_url(); ?>register?plan=agency" class="btn btn-outline btn-block">Start Free Trial</a>
                </div>

            </div>
        </div>
    </section>

    <section class="pricing-faq">
        <div class="container pricing-faq__inner">
            <h2 class="pricing-faq__title">Frequently asked questions</h2>
            <div class="faq-list">

                <details class="faq-item">
                    <summary class="faq-question">Do I need a Google Ads account to get started?</summary>
                    <div class="faq-answer">
                        <p>Yes — RevForge connects to your existing Google Ads account via secure OAuth. If you don't have one yet, you can create a free Google Ads account at ads.google.com and connect it during onboarding. RevForge guides you through the whole setup.</p>
                    </div>
                </details>

                <details class="faq-item">
                    <summary class="faq-question">What happens after my 14-day free trial?</summary>
                    <div class="faq-answer">
                        <p>After 14 days you'll be prompted to choose a plan. We won't charge you automatically — no credit card is required to start. If you decide not to continue, your data is kept for 30 days in case you change your mind.</p>
                    </div>
                </details>

                <details class="faq-item">
                    <summary class="faq-question">Can I manage multiple client accounts as an agency?</summary>
                    <div class="faq-answer">
                        <p>Absolutely. The Agency plan supports unlimited Google Ads accounts, white-label PDF reports with your branding, and a client-facing dashboard you can share read-only access to. It's built for agencies managing multiple trade contractor clients.</p>
                    </div>
                </details>

                <details class="faq-item">
                    <summary class="faq-question">How does the Billboard Ads module work?</summary>
                    <div class="faq-answer">
                        <p>The Billboard Ads module lets you plan, build, and manage digital out-of-home campaigns entirely within RevForge. Browse screens by city, estimate reach and impressions, generate AI billboard copy, upload your creative, and track campaign performance — all without a media buyer or agency.</p>
                    </div>
                </details>

                <details class="faq-item">
                    <summary class="faq-question">Does RevForge actually make changes to my Google Ads campaigns?</summary>
                    <div class="faq-answer">
                        <p>Only with your permission. By default, RevForge surfaces recommendations in an Action Queue for you to approve with one click. If you enable Autopilot for specific action types, high-confidence changes (like adding negative keywords) can execute automatically — but you set the thresholds and can turn it off at any time.</p>
                    </div>
                </details>

            </div>
        </div>
    </section>

    <?php get_template_part( 'template-parts/cta-band' ); ?>

</main>

<?php get_footer();
