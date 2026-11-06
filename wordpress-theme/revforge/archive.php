<?php
/**
 * Archive template (categories, tags, date archives)
 */
get_header(); ?>

<main id="main">

    <section class="page-hero page-hero--simple page-hero--light">
        <div class="container">
            <?php the_archive_title( '<h1 class="page-hero__title">', '</h1>' ); ?>
            <?php the_archive_description( '<p class="page-hero__sub">', '</p>' ); ?>
        </div>
    </section>

    <div class="container blog-layout">
        <div class="blog-main">
            <?php if ( have_posts() ) : ?>
                <div class="posts-grid">
                    <?php while ( have_posts() ) : the_post();
                        get_template_part( 'template-parts/post-card' );
                    endwhile; ?>
                </div>
                <div class="pagination-wrap">
                    <?php the_posts_pagination( [
                        'prev_text' => '&larr; Previous',
                        'next_text' => 'Next &rarr;',
                    ] ); ?>
                </div>
            <?php else : ?>
                <div class="no-results">
                    <h2>Nothing found</h2>
                    <p>Try browsing the <a href="<?php echo esc_url( home_url( '/blog' ) ); ?>">full blog</a>.</p>
                </div>
            <?php endif; ?>
        </div>

        <aside class="blog-sidebar">
            <?php if ( is_active_sidebar( 'blog-sidebar' ) ) :
                dynamic_sidebar( 'blog-sidebar' );
            else : ?>
                <div class="sidebar-cta">
                    <h3>Grow your trade business</h3>
                    <p>RevForge automates your Google Ads so you can focus on the job.</p>
                    <a href="<?php echo revforge_app_url(); ?>register" class="btn btn-primary btn-block">Try Free for 14 Days</a>
                </div>
            <?php endif; ?>
        </aside>
    </div>

</main>

<?php get_footer();
