<?php
/**
 * Single post template
 */
get_header(); ?>

<main id="main" class="single-post-wrap">
    <?php while ( have_posts() ) : the_post(); ?>

        <article id="post-<?php the_ID(); ?>" <?php post_class( 'single-post' ); ?>>

            <?php revforge_breadcrumbs(); ?>

            <div class="single-post__hero">
                <?php
                $categories = get_the_category();
                if ( $categories ) : ?>
                    <div class="single-post__cats">
                        <?php foreach ( $categories as $cat ) : ?>
                            <a href="<?php echo esc_url( get_category_link( $cat->term_id ) ); ?>" class="cat-badge">
                                <?php echo esc_html( $cat->name ); ?>
                            </a>
                        <?php endforeach; ?>
                    </div>
                <?php endif; ?>

                <!-- speakable: AEO voice-search signal for the headline -->
                <h1 class="single-post__title speakable"><?php echo esc_html( get_the_title() ); ?></h1>

                <div class="single-post__meta">
                    <span class="single-post__date"><?php echo get_the_date( 'F j, Y' ); ?></span>
                    <span class="single-post__sep">·</span>
                    <span class="single-post__author">By <?php the_author(); ?></span>
                    <span class="single-post__sep">·</span>
                    <span class="single-post__read-time">
                        <?php
                        $content    = get_post_field( 'post_content', get_the_ID() );
                        $word_count = str_word_count( strip_tags( $content ) );
                        $minutes    = max( 1, (int) ceil( $word_count / 200 ) );
                        echo esc_html( $minutes . ' min read' );
                        ?>
                    </span>
                </div>
            </div>

            <?php if ( has_post_thumbnail() ) : ?>
                <div class="single-post__featured-image">
                    <?php the_post_thumbnail( 'large' ); ?>
                </div>
            <?php endif; ?>

            <div class="single-post__body">
                <?php the_content(); ?>
            </div>

            <?php
            $tags = get_the_tags();
            if ( $tags ) : ?>
                <div class="single-post__tags">
                    <span class="tags-label">Tags:</span>
                    <?php foreach ( $tags as $tag ) : ?>
                        <a href="<?php echo esc_url( get_tag_link( $tag->term_id ) ); ?>" class="tag-pill">
                            <?php echo esc_html( $tag->name ); ?>
                        </a>
                    <?php endforeach; ?>
                </div>
            <?php endif; ?>

            <?php revforge_post_adjacent_links(); ?>

            <div class="single-post__nav">
                <a href="<?php echo esc_url( home_url( '/blog' ) ); ?>" class="btn btn-outline">&larr; Back to Blog</a>
            </div>

        </article>

    <?php endwhile; ?>

    <div class="single-post__cta-band">
        <div class="container">
            <div class="inline-cta">
                <div class="inline-cta__icon">
                    <svg width="24" height="24" viewBox="0 0 22 22" fill="none"><path d="M12.5 2L4 13h7l-1.5 7L18 9h-7l1.5-7z" fill="#1A5C35" stroke="#1A5C35" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>
                </div>
                <div class="inline-cta__text">
                    <strong>Ready to put your Google Ads on autopilot?</strong>
                    <span>RevForge handles the optimization — you handle the jobs.</span>
                </div>
                <a href="<?php echo revforge_app_url(); ?>register" class="btn btn-primary">Try RevForge Free</a>
            </div>
        </div>
    </div>

</main>

<?php get_footer();
