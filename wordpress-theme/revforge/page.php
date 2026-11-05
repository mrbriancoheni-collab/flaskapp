<?php
/**
 * Generic page template
 */
get_header(); ?>

<main class="site-main" id="main">
    <div class="page-hero page-hero--simple">
        <div class="container">
            <?php while ( have_posts() ) : the_post(); ?>
                <h1 class="page-hero__title"><?php the_title(); ?></h1>
            <?php endwhile; ?>
        </div>
    </div>

    <div class="container page-content">
        <?php while ( have_posts() ) : the_post();
            the_content();
        endwhile; ?>
    </div>
</main>

<?php get_footer();
