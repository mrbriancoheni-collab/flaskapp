<?php
/**
 * Front page template — homepage
 */
get_header(); ?>

<main id="main">
    <?php get_template_part( 'template-parts/hero' ); ?>

    <?php get_template_part( 'template-parts/features-grid' ); ?>

    <section class="trusted-strip">
        <div class="container">
            <p class="trusted-label">Built for trade contractors across every industry</p>
            <div class="trusted-trades">
                <span class="trade-pill">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M3 9l9-7 9 7v11a2 2 0 01-2 2H5a2 2 0 01-2-2z"/><polyline points="9 22 9 12 15 12 15 22"/></svg>
                    HVAC
                </span>
                <span class="trade-pill">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2z"/><path d="M8 12h8M12 8v8"/></svg>
                    Plumbing
                </span>
                <span class="trade-pill">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z"/></svg>
                    Electrical
                </span>
                <span class="trade-pill">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M3 9l9-7 9 7"/><path d="M3 9v6a9 9 0 0018 0V9"/></svg>
                    Roofing
                </span>
                <span class="trade-pill">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><circle cx="12" cy="12" r="3"/><path d="M12 1v4M12 19v4M4.22 4.22l2.83 2.83M16.95 16.95l2.83 2.83M1 12h4M19 12h4M4.22 19.78l2.83-2.83M16.95 7.05l2.83-2.83"/></svg>
                    Pest Control
                </span>
                <span class="trade-pill">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M17 8C8 10 5.9 16.17 3.82 19.98"/><path d="M13 15.5c0 0-5-1.5-7-7"/></svg>
                    Landscaping
                </span>
            </div>
        </div>
    </section>

    <?php get_template_part( 'template-parts/pricing-cards' ); ?>

    <?php get_template_part( 'template-parts/testimonials' ); ?>

    <?php get_template_part( 'template-parts/cta-band' ); ?>
</main>

<?php get_footer();
