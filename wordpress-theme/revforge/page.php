<?php
/**
 * Generic page template
 */
get_header(); ?>

<main class="site-main" id="main">
    <?php while ( have_posts() ) : the_post(); ?>
    <div class="page-hero page-hero--simple">
        <div class="container">
            <?php revforge_breadcrumbs(); ?>
            <h1 class="page-hero__title"><?php echo esc_html( get_the_title() ); ?></h1>
        </div>
    </div>

    <div class="container page-content">
        <?php the_content(); ?>
    </div>
    <?php endwhile; ?>
</main>

<?php get_footer();
