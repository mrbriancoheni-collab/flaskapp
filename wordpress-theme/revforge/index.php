<?php
/**
 * Fallback template — WordPress requires this file.
 * Specific templates (front-page.php, home.php, single.php) take precedence.
 */
get_header(); ?>

<main class="site-main container" id="main">
    <?php if ( have_posts() ) : ?>
        <div class="posts-grid">
            <?php while ( have_posts() ) : the_post();
                get_template_part( 'template-parts/post-card' );
            endwhile; ?>
        </div>
        <?php the_posts_pagination( [
            'prev_text' => '&larr; Previous',
            'next_text' => 'Next &rarr;',
        ] ); ?>
    <?php else : ?>
        <div class="no-results">
            <h2>Nothing found</h2>
            <p>Try a different search, or browse the <a href="<?php echo esc_url( home_url( '/' ) ); ?>">homepage</a>.</p>
        </div>
    <?php endif; ?>
</main>

<?php get_footer();
