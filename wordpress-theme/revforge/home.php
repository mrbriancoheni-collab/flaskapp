<?php
/**
 * Blog index template
 */
get_header(); ?>

<main id="main">

    <section class="page-hero page-hero--simple page-hero--light">
        <div class="container">
            <h1 class="page-hero__title">RevForge Blog</h1>
            <p class="page-hero__sub">Google Ads strategies, trade industry insights, and product updates for contractors.</p>
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
                        'class'     => 'pagination',
                    ] ); ?>
                </div>
            <?php else : ?>
                <div class="no-results">
                    <h2>No posts yet</h2>
                    <p>Check back soon — we publish weekly guides on Google Ads for trade contractors.</p>
                </div>
            <?php endif; ?>
        </div>

        <aside class="blog-sidebar">
            <?php if ( is_active_sidebar( 'blog-sidebar' ) ) : ?>
                <?php dynamic_sidebar( 'blog-sidebar' ); ?>
            <?php else : ?>
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
