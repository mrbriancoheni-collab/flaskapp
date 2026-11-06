<?php
/**
 * Template Name: Features Page
 */

// HowTo schema steps for JSON-LD (picked up by inc/seo.php)
add_filter( 'revforge_howto_schema_steps', function() {
    return [
        [
            'name' => 'Connect your Google Ads account',
            'text' => 'Sign up for RevForge and connect your Google Ads account via secure OAuth. RevForge imports your campaigns, ad groups, and keywords automatically.',
        ],
        [
            'name' => 'Review AI recommendations in the Action Queue',
            'text' => 'RevForge\'s AI analyzes your account and surfaces bid adjustments, negative keywords, and budget optimizations. Approve actions with one click.',
        ],
        [
            'name' => 'Generate high-quality ad copy with the RSA Generator',
            'text' => 'Enter your trade, city, and selling points. RevForge generates Google-compliant headlines and descriptions in seconds, with quality scoring tips.',
        ],
        [
            'name' => 'Optionally plan billboard campaigns',
            'text' => 'Use the Billboard Ads module to browse 28,000+ digital screen locations by city, estimate reach and CPM, and generate AI billboard copy to complement your Google Ads.',
        ],
        [
            'name' => 'Monitor leads and cost-per-lead',
            'text' => 'The Lead Tracking dashboard shows exactly which keywords, ads, and campaigns generate phone calls and form submissions, so you know your true cost per job booked.',
        ],
    ];
} );

get_header(); ?>

<main id="main">

    <section class="page-hero page-hero--green">
        <div class="container page-hero__inner">
            <div class="page-hero__badge">Platform Features</div>
            <h1 class="page-hero__title">Everything you need to dominate local Google Ads</h1>
            <p class="page-hero__sub">RevForge combines AI automation, smart budgeting, and OOH planning into one platform built exclusively for trade contractors.</p>
            <div class="page-hero__actions">
                <a href="<?php echo revforge_app_url(); ?>register" class="btn btn-white">Start Free Trial</a>
                <a href="<?php echo esc_url( home_url( '/pricing' ) ); ?>" class="btn btn-outline-white">See Pricing</a>
            </div>
        </div>
    </section>

    <section class="features-detail">
        <div class="container">

            <div class="feature-row">
                <div class="feature-row__content">
                    <div class="feature-row__icon feature-row__icon--green">
                        <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z"/></svg>
                    </div>
                    <h2 class="feature-row__title">Google Ads AI Autopilot</h2>
                    <p class="feature-row__desc">RevForge's AI monitors your campaigns around the clock — adjusting bids, pausing underperformers, and surfacing opportunities before your budget evaporates on bad clicks.</p>
                    <ul class="feature-row__benefits">
                        <li>Automatic bid adjustments based on time-of-day and device performance</li>
                        <li>Anomaly detection flags unusual spend spikes within hours, not days</li>
                        <li>Weekly AI-generated action queue with one-click approvals</li>
                    </ul>
                </div>
                <div class="feature-row__visual feature-row__visual--green">
                    <div class="mock-screen">
                        <div class="mock-screen__header">AI Action Queue</div>
                        <div class="mock-screen__body">
                            <div class="mock-action mock-action--save">↓ Reduce bid on "emergency plumber" +12% &nbsp;<span>Save $340/mo</span></div>
                            <div class="mock-action mock-action--pause">⏸ Pause underperforming ad group &nbsp;<span>+8% CTR</span></div>
                            <div class="mock-action mock-action--add">+ Add 14 negative keywords &nbsp;<span>Save $180/mo</span></div>
                        </div>
                    </div>
                </div>
            </div>

            <div class="feature-row feature-row--reverse">
                <div class="feature-row__content">
                    <div class="feature-row__icon feature-row__icon--blue">
                        <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 20h9"/><path d="M16.5 3.5a2.121 2.121 0 013 3L7 19l-4 1 1-4L16.5 3.5z"/></svg>
                    </div>
                    <h2 class="feature-row__title">RSA Copy Generator</h2>
                    <p class="feature-row__desc">Stop staring at a blank ad form. Enter your trade, city, and a few selling points — RevForge's AI generates 15 Google-compliant headlines and 4 descriptions in seconds.</p>
                    <ul class="feature-row__benefits">
                        <li>Trade-specific language that resonates with homeowners searching now</li>
                        <li>Automatically enforces Google's 30-char headline / 90-char description limits</li>
                        <li>Quality scoring tips explain exactly how to improve each ad</li>
                    </ul>
                </div>
                <div class="feature-row__visual feature-row__visual--blue">
                    <div class="mock-screen">
                        <div class="mock-screen__header">RSA Generator</div>
                        <div class="mock-screen__body">
                            <div class="mock-hl">Phoenix HVAC Experts<span class="mock-char">19</span></div>
                            <div class="mock-hl">Same-Day AC Repair<span class="mock-char">18</span></div>
                            <div class="mock-hl">Licensed &amp; Insured HVAC<span class="mock-char">22</span></div>
                            <div class="mock-hl mock-hl--over">Free Diagnostic + Same Day Service<span class="mock-char mock-char--over">34</span></div>
                        </div>
                    </div>
                </div>
            </div>

            <div class="feature-row">
                <div class="feature-row__content">
                    <div class="feature-row__icon feature-row__icon--amber">
                        <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="2" y="3" width="20" height="14" rx="2"/><path d="M8 21h8M12 17v4"/></svg>
                    </div>
                    <h2 class="feature-row__title">Billboard &amp; OOH Ads</h2>
                    <p class="feature-row__desc">Plan and launch digital out-of-home campaigns without a media buyer. Browse screens by city, estimate reach, generate billboard-ready creative copy, and manage your entire OOH campaign from one dashboard.</p>
                    <ul class="feature-row__benefits">
                        <li>28,000+ digital screen locations with real CPP and impression data</li>
                        <li>AI-generated 7-word billboard copy optimized for your trade and city</li>
                        <li>Budget estimator shows reach, plays per day, and estimated CPM</li>
                    </ul>
                </div>
                <div class="feature-row__visual feature-row__visual--amber">
                    <div class="mock-screen">
                        <div class="mock-screen__header">Billboard Planner — Phoenix, AZ</div>
                        <div class="mock-screen__body">
                            <div class="mock-billboard">
                                <div class="mock-billboard__screen">
                                    <p class="mock-billboard__copy">Phoenix's #1 HVAC.<br>Call Now. Same Day.</p>
                                </div>
                                <div class="mock-billboard__stats">
                                    <span>12,400 plays/day</span>
                                    <span>$0.004 CPP</span>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>

            <div class="feature-row feature-row--reverse">
                <div class="feature-row__content">
                    <div class="feature-row__icon feature-row__icon--green">
                        <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="12" y1="1" x2="12" y2="23"/><path d="M17 5H9.5a3.5 3.5 0 000 7h5a3.5 3.5 0 010 7H6"/></svg>
                    </div>
                    <h2 class="feature-row__title">Smart Budget Optimizer</h2>
                    <p class="feature-row__desc">Stop guessing how much to spend and where. RevForge analyzes your campaign data and automatically reallocates budget from underperforming campaigns to your best-performing ones.</p>
                    <ul class="feature-row__benefits">
                        <li>Seasonal budget recommendations based on your trade's demand curves</li>
                        <li>Campaign-level ROI scoring shows exactly where your money is going</li>
                        <li>One-click reallocation with approval-gated auto-execute option</li>
                    </ul>
                </div>
                <div class="feature-row__visual feature-row__visual--green">
                    <div class="mock-screen">
                        <div class="mock-screen__header">Budget Overview</div>
                        <div class="mock-screen__body mock-chart-wrap">
                            <div class="mock-bar-chart">
                                <div class="mock-bar" style="height:60%"><span>AC Repair</span></div>
                                <div class="mock-bar mock-bar--accent" style="height:90%"><span>Furnace</span></div>
                                <div class="mock-bar" style="height:40%"><span>Tune-Up</span></div>
                                <div class="mock-bar" style="height:70%"><span>Emergency</span></div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>

            <div class="feature-row">
                <div class="feature-row__content">
                    <div class="feature-row__icon feature-row__icon--blue">
                        <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"/><path d="M21 21l-4.35-4.35"/><path d="M11 8v6M8 11h6"/></svg>
                    </div>
                    <h2 class="feature-row__title">Negative Keyword Engine</h2>
                    <p class="feature-row__desc">Every irrelevant click costs you money. RevForge automatically mines your search term reports, identifies wasteful queries, and adds them as negatives — saving hundreds every month.</p>
                    <ul class="feature-row__benefits">
                        <li>Trade-specific negative keyword libraries for 12 contractor types</li>
                        <li>Automatic detection of DIY, competitor, and geographic mismatches</li>
                        <li>Monthly audit reports showing exactly how much you saved</li>
                    </ul>
                </div>
                <div class="feature-row__visual feature-row__visual--blue">
                    <div class="mock-screen">
                        <div class="mock-screen__header">Negative Keywords — HVAC</div>
                        <div class="mock-screen__body">
                            <div class="mock-neg-kw"><span class="neg-kw-pill">how to fix ac yourself</span></div>
                            <div class="mock-neg-kw"><span class="neg-kw-pill">hvac school</span></div>
                            <div class="mock-neg-kw"><span class="neg-kw-pill">free hvac certification</span></div>
                            <div class="mock-neg-kw"><span class="neg-kw-pill">carrier hvac parts</span></div>
                        </div>
                    </div>
                </div>
            </div>

            <div class="feature-row feature-row--reverse">
                <div class="feature-row__content">
                    <div class="feature-row__icon feature-row__icon--amber">
                        <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 16.92v3a2 2 0 01-2.18 2 19.79 19.79 0 01-8.63-3.07A19.5 19.5 0 013.07 9.81a19.79 19.79 0 01-3.07-8.67A2 2 0 012 .84h3a2 2 0 012 1.72c.127.96.361 1.903.7 2.81a2 2 0 01-.45 2.11L6.09 8.91a16 16 0 006 6l1.27-1.27a2 2 0 012.11-.45c.907.339 1.85.573 2.81.7A2 2 0 0122 15.92v1z"/></svg>
                    </div>
                    <h2 class="feature-row__title">Lead Tracking</h2>
                    <p class="feature-row__desc">Know exactly which keywords, ads, and campaigns generate real phone calls and form submissions — not just clicks. Close the loop between your ad spend and actual booked jobs.</p>
                    <ul class="feature-row__benefits">
                        <li>Call tracking integration shows which ad triggered each inbound call</li>
                        <li>Form submission attribution links to the keyword that converted</li>
                        <li>Cost-per-lead dashboard updated daily across all campaigns</li>
                    </ul>
                </div>
                <div class="feature-row__visual feature-row__visual--amber">
                    <div class="mock-screen">
                        <div class="mock-screen__header">Lead Summary — This Month</div>
                        <div class="mock-screen__body">
                            <div class="mock-stat-row"><span class="mock-stat-label">Total Leads</span><span class="mock-stat-val">84</span></div>
                            <div class="mock-stat-row"><span class="mock-stat-label">Cost Per Lead</span><span class="mock-stat-val">$31.20</span></div>
                            <div class="mock-stat-row"><span class="mock-stat-label">Top Keyword</span><span class="mock-stat-val">ac repair phoenix</span></div>
                            <div class="mock-stat-row"><span class="mock-stat-label">Call Conv. Rate</span><span class="mock-stat-val">18.4%</span></div>
                        </div>
                    </div>
                </div>
            </div>

        </div>
    </section>

    <?php get_template_part( 'template-parts/cta-band' ); ?>

</main>

<?php get_footer();
