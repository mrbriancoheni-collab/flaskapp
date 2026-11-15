<?php
/**
 * 404 error template
 */
get_header(); ?>

<main id="main">
    <section class="error-404">
        <div class="container error-404__inner">
            <div class="error-404__number">404</div>
            <h1 class="error-404__title">Page not found</h1>
            <p class="error-404__desc">The page you're looking for doesn't exist or was moved. Try the homepage or search for what you need.</p>
            <div class="error-404__actions">
                <a href="<?php echo esc_url( home_url( '/' ) ); ?>" class="btn btn-primary">Go to Homepage</a>
                <a href="<?php echo esc_url( home_url( '/blog' ) ); ?>" class="btn btn-outline">Browse the Blog</a>
            </div>
            <div class="error-404__search">
                <?php get_search_form(); ?>
            </div>
        </div>
    </section>
</main>

<?php get_footer();
