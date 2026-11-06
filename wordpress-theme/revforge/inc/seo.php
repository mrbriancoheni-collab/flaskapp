<?php
/**
 * SEO / AEO / GEO: meta tags, JSON-LD schema, breadcrumbs, pagination, speakable markup
 */

if ( ! defined( 'ABSPATH' ) ) exit;

// ── Meta: description, canonical, OG, Twitter Card ─────────────────────────
function revforge_seo_head() {
    global $post;

    // Description
    $description = '';
    if ( is_singular() && $post ) {
        $description = $post->post_excerpt
            ? wp_strip_all_tags( $post->post_excerpt )
            : wp_trim_words( wp_strip_all_tags( $post->post_content ), 25, '' );
    } elseif ( is_home() || is_front_page() ) {
        $description = get_bloginfo( 'description' );
    } elseif ( is_category() || is_tag() ) {
        $description = wp_strip_all_tags( term_description() );
    } elseif ( is_author() ) {
        $description = wp_strip_all_tags( get_the_author_meta( 'description' ) );
    }
    if ( ! $description ) {
        $description = get_bloginfo( 'description' );
    }

    // Canonical
    if ( is_singular() ) {
        $canonical = get_permalink();
    } elseif ( is_home() || is_front_page() ) {
        $canonical = home_url( '/' );
    } else {
        $canonical = get_pagenum_link();
    }

    // OG image
    $og_image = '';
    if ( is_singular() && has_post_thumbnail() ) {
        $img = wp_get_attachment_image_src( get_post_thumbnail_id(), 'large' );
        $og_image = $img ? $img[0] : '';
    }
    if ( ! $og_image ) {
        $og_image = get_template_directory_uri() . '/assets/img/og-default.png';
    }

    // Title for OG (falls back to WP-generated)
    $og_title = wp_get_document_title();

    // Type
    $og_type = is_singular( 'post' ) ? 'article' : 'website';

    echo "\n";
    // Description
    echo '<meta name="description" content="' . esc_attr( $description ) . '">' . "\n";
    // Robots — noindex on paginated archives past page 1 and search results
    if ( is_search() || ( is_paged() && ( is_category() || is_tag() || is_author() ) ) ) {
        echo '<meta name="robots" content="noindex, follow">' . "\n";
    }
    // Canonical
    echo '<link rel="canonical" href="' . esc_url( $canonical ) . '">' . "\n";

    // Open Graph
    echo '<meta property="og:site_name" content="' . esc_attr( get_bloginfo( 'name' ) ) . '">' . "\n";
    echo '<meta property="og:type" content="' . esc_attr( $og_type ) . '">' . "\n";
    echo '<meta property="og:title" content="' . esc_attr( $og_title ) . '">' . "\n";
    echo '<meta property="og:description" content="' . esc_attr( $description ) . '">' . "\n";
    echo '<meta property="og:url" content="' . esc_url( $canonical ) . '">' . "\n";
    echo '<meta property="og:image" content="' . esc_url( $og_image ) . '">' . "\n";
    echo '<meta property="og:image:width" content="1200">' . "\n";
    echo '<meta property="og:image:height" content="630">' . "\n";
    if ( is_singular( 'post' ) ) {
        echo '<meta property="article:published_time" content="' . esc_attr( get_the_date( 'c' ) ) . '">' . "\n";
        echo '<meta property="article:modified_time" content="' . esc_attr( get_the_modified_date( 'c' ) ) . '">' . "\n";
        $cats = get_the_category();
        if ( $cats ) {
            echo '<meta property="article:section" content="' . esc_attr( $cats[0]->name ) . '">' . "\n";
        }
    }

    // Twitter Card
    echo '<meta name="twitter:card" content="summary_large_image">' . "\n";
    echo '<meta name="twitter:title" content="' . esc_attr( $og_title ) . '">' . "\n";
    echo '<meta name="twitter:description" content="' . esc_attr( $description ) . '">' . "\n";
    echo '<meta name="twitter:image" content="' . esc_url( $og_image ) . '">' . "\n";
    echo "\n";
}
add_action( 'wp_head', 'revforge_seo_head', 1 );

// ── JSON-LD schema output ────────────────────────────────────────────────────
function revforge_schema_jsonld() {
    $schemas = [];

    // WebSite (always) — enables Sitelinks Searchbox
    $schemas[] = [
        '@context' => 'https://schema.org',
        '@type'    => 'WebSite',
        'name'     => get_bloginfo( 'name' ),
        'url'      => home_url( '/' ),
        'potentialAction' => [
            '@type'       => 'SearchAction',
            'target'      => [
                '@type'       => 'EntryPoint',
                'urlTemplate' => home_url( '/?s={search_term_string}' ),
            ],
            'query-input' => 'required name=search_term_string',
        ],
    ];

    // Organization (always)
    $logo_url = '';
    if ( has_custom_logo() ) {
        $logo_id  = get_theme_mod( 'custom_logo' );
        $logo_img = wp_get_attachment_image_src( $logo_id, 'full' );
        $logo_url = $logo_img ? $logo_img[0] : '';
    }
    if ( ! $logo_url ) {
        $logo_url = get_template_directory_uri() . '/assets/img/revforge-logo.png';
    }
    $schemas[] = [
        '@context'      => 'https://schema.org',
        '@type'         => 'Organization',
        '@id'           => home_url( '/#organization' ),
        'name'          => 'RevForge',
        'url'           => home_url( '/' ),
        'logo'          => [
            '@type' => 'ImageObject',
            'url'   => $logo_url,
        ],
        'sameAs'        => apply_filters( 'revforge_schema_sameas', [] ),
        'contactPoint'  => [
            '@type'             => 'ContactPoint',
            'contactType'       => 'customer support',
            'availableLanguage' => 'English',
        ],
    ];

    // BreadcrumbList — all non-home pages
    $breadcrumbs = revforge_get_breadcrumbs_data();
    if ( count( $breadcrumbs ) > 1 ) {
        $items = [];
        foreach ( $breadcrumbs as $pos => $crumb ) {
            $items[] = [
                '@type'    => 'ListItem',
                'position' => $pos + 1,
                'name'     => $crumb['label'],
                'item'     => $crumb['url'],
            ];
        }
        $schemas[] = [
            '@context'        => 'https://schema.org',
            '@type'           => 'BreadcrumbList',
            'itemListElement' => $items,
        ];
    }

    // Article schema for single posts
    if ( is_singular( 'post' ) ) {
        $post        = get_post();
        $author_name = get_the_author_meta( 'display_name', $post->post_author );
        $schemas[]   = [
            '@context'        => 'https://schema.org',
            '@type'           => 'Article',
            'headline'        => wp_strip_all_tags( get_the_title() ),
            'description'     => wp_trim_words( wp_strip_all_tags( $post->post_excerpt ?: $post->post_content ), 25, '' ),
            'datePublished'   => get_the_date( 'c' ),
            'dateModified'    => get_the_modified_date( 'c' ),
            'author'          => [ '@type' => 'Person', 'name' => $author_name ],
            'publisher'       => [
                '@type' => 'Organization',
                '@id'   => home_url( '/#organization' ),
                'name'  => 'RevForge',
                'logo'  => [ '@type' => 'ImageObject', 'url' => $logo_url ],
            ],
            'mainEntityOfPage' => [ '@type' => 'WebPage', '@id' => get_permalink() ],
            'speakable' => [
                '@type'            => 'SpeakableSpecification',
                'cssSelector'      => [ '.single-post__title', '.single-post__body > p:first-of-type' ],
            ],
        ];
    }

    // FAQPage schema — added via filter on pricing/faq pages
    $faq_items = apply_filters( 'revforge_faq_schema_items', [] );
    if ( $faq_items ) {
        $main_entity = [];
        foreach ( $faq_items as $faq ) {
            $main_entity[] = [
                '@type'          => 'Question',
                'name'           => wp_strip_all_tags( $faq['question'] ),
                'acceptedAnswer' => [
                    '@type' => 'Answer',
                    'text'  => wp_strip_all_tags( $faq['answer'] ),
                ],
            ];
        }
        $schemas[] = [
            '@context'   => 'https://schema.org',
            '@type'      => 'FAQPage',
            'mainEntity' => $main_entity,
        ];
    }

    // HowTo schema — added via filter on features page
    $howto_steps = apply_filters( 'revforge_howto_schema_steps', [] );
    if ( $howto_steps ) {
        $steps = [];
        foreach ( $howto_steps as $step ) {
            $steps[] = [
                '@type' => 'HowToStep',
                'name'  => wp_strip_all_tags( $step['name'] ),
                'text'  => wp_strip_all_tags( $step['text'] ),
            ];
        }
        $schemas[] = [
            '@context' => 'https://schema.org',
            '@type'    => 'HowTo',
            'name'     => 'How to set up RevForge for your Google Ads',
            'step'     => $steps,
        ];
    }

    // SoftwareApplication schema (homepage / front page)
    if ( is_front_page() ) {
        $schemas[] = [
            '@context'            => 'https://schema.org',
            '@type'               => 'SoftwareApplication',
            'name'                => 'RevForge',
            'applicationCategory' => 'BusinessApplication',
            'operatingSystem'     => 'Web',
            'offers'              => [
                '@type'    => 'Offer',
                'price'    => '49',
                'priceCurrency' => 'USD',
                'priceValidUntil' => gmdate( 'Y-12-31' ),
            ],
            'aggregateRating' => [
                '@type'       => 'AggregateRating',
                'ratingValue' => '4.8',
                'reviewCount' => '127',
            ],
        ];
    }

    foreach ( $schemas as $schema ) {
        echo '<script type="application/ld+json">' . wp_json_encode( $schema, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE | JSON_PRETTY_PRINT ) . '</script>' . "\n";
    }
}
add_action( 'wp_head', 'revforge_schema_jsonld', 2 );

// ── Breadcrumbs data helper (returns array) ───────────────────────────────
function revforge_get_breadcrumbs_data() {
    $crumbs = [];
    $crumbs[] = [ 'label' => __( 'Home', 'revforge' ), 'url' => home_url( '/' ) ];

    if ( is_singular( 'post' ) ) {
        $cats = get_the_category();
        if ( $cats ) {
            $crumbs[] = [ 'label' => esc_html( $cats[0]->name ), 'url' => esc_url( get_category_link( $cats[0]->term_id ) ) ];
        }
        $crumbs[] = [ 'label' => esc_html( get_the_title() ), 'url' => esc_url( get_permalink() ) ];
    } elseif ( is_page() ) {
        $ancestors = array_reverse( get_post_ancestors( get_the_ID() ) );
        foreach ( $ancestors as $ancestor_id ) {
            $crumbs[] = [ 'label' => esc_html( get_the_title( $ancestor_id ) ), 'url' => esc_url( get_permalink( $ancestor_id ) ) ];
        }
        $crumbs[] = [ 'label' => esc_html( get_the_title() ), 'url' => esc_url( get_permalink() ) ];
    } elseif ( is_category() ) {
        $crumbs[] = [ 'label' => esc_html( single_cat_title( '', false ) ), 'url' => esc_url( get_category_link( get_queried_object_id() ) ) ];
    } elseif ( is_tag() ) {
        $crumbs[] = [ 'label' => esc_html( single_tag_title( '', false ) ), 'url' => esc_url( get_tag_link( get_queried_object_id() ) ) ];
    } elseif ( is_author() ) {
        $crumbs[] = [ 'label' => esc_html( get_the_author() ), 'url' => '' ];
    } elseif ( is_search() ) {
        $crumbs[] = [ 'label' => sprintf( __( 'Search: %s', 'revforge' ), esc_html( get_search_query() ) ), 'url' => '' ];
    } elseif ( is_404() ) {
        $crumbs[] = [ 'label' => __( 'Page not found', 'revforge' ), 'url' => '' ];
    }

    return $crumbs;
}

// ── Breadcrumbs HTML output ──────────────────────────────────────────────
function revforge_breadcrumbs() {
    $crumbs = revforge_get_breadcrumbs_data();
    if ( count( $crumbs ) <= 1 ) return;

    echo '<nav class="breadcrumbs" aria-label="' . esc_attr__( 'Breadcrumb', 'revforge' ) . '">';
    echo '<ol class="breadcrumbs__list" itemscope itemtype="https://schema.org/BreadcrumbList">';
    $total = count( $crumbs );
    foreach ( $crumbs as $i => $crumb ) {
        $is_last  = ( $i === $total - 1 );
        $position = $i + 1;
        echo '<li class="breadcrumbs__item" itemprop="itemListElement" itemscope itemtype="https://schema.org/ListItem">';
        if ( ! $is_last && $crumb['url'] ) {
            echo '<a href="' . esc_url( $crumb['url'] ) . '" class="breadcrumbs__link" itemprop="item"><span itemprop="name">' . esc_html( $crumb['label'] ) . '</span></a>';
        } else {
            echo '<span class="breadcrumbs__current" itemprop="item"><span itemprop="name">' . esc_html( $crumb['label'] ) . '</span></span>';
        }
        echo '<meta itemprop="position" content="' . esc_attr( $position ) . '">';
        if ( ! $is_last ) {
            echo '<span class="breadcrumbs__sep" aria-hidden="true">›</span>';
        }
        echo '</li>';
    }
    echo '</ol></nav>';
}

// ── Pagination links for archives (prev/next) ────────────────────────────
function revforge_pagination_links() {
    the_posts_pagination( [
        'mid_size'           => 2,
        'prev_text'          => '<span aria-hidden="true">&laquo;</span><span class="screen-reader-text">' . __( 'Previous page', 'revforge' ) . '</span>',
        'next_text'          => '<span class="screen-reader-text">' . __( 'Next page', 'revforge' ) . '</span><span aria-hidden="true">&raquo;</span>',
        'before_page_number' => '<span class="screen-reader-text">' . __( 'Page', 'revforge' ) . ' </span>',
    ] );
}

// ── Prev/Next post links for single.php ─────────────────────────────────
function revforge_post_adjacent_links() {
    $prev = get_previous_post();
    $next = get_next_post();
    if ( ! $prev && ! $next ) return;
    echo '<nav class="post-nav" aria-label="' . esc_attr__( 'Post navigation', 'revforge' ) . '">';
    if ( $prev ) {
        echo '<a href="' . esc_url( get_permalink( $prev ) ) . '" class="post-nav__prev" rel="prev">';
        echo '<span class="post-nav__label">' . esc_html__( 'Previous', 'revforge' ) . '</span>';
        echo '<span class="post-nav__title">' . esc_html( get_the_title( $prev ) ) . '</span>';
        echo '</a>';
    }
    if ( $next ) {
        echo '<a href="' . esc_url( get_permalink( $next ) ) . '" class="post-nav__next" rel="next">';
        echo '<span class="post-nav__label">' . esc_html__( 'Next', 'revforge' ) . '</span>';
        echo '<span class="post-nav__title">' . esc_html( get_the_title( $next ) ) . '</span>';
        echo '</a>';
    }
    echo '</nav>';
}

// ── Remove WP version from head ──────────────────────────────────────────
remove_action( 'wp_head', 'wp_generator' );

// ── Remove unnecessary head links ───────────────────────────────────────
remove_action( 'wp_head', 'rsd_link' );
remove_action( 'wp_head', 'wlwmanifest_link' );
remove_action( 'wp_head', 'wp_shortlink_wp_head' );

// ── Add hreflang for single-language sites (extend later for multilingual) ─
function revforge_hreflang() {
    if ( is_singular() ) {
        echo '<link rel="alternate" hreflang="' . esc_attr( get_bloginfo( 'language' ) ) . '" href="' . esc_url( get_permalink() ) . '">' . "\n";
        echo '<link rel="alternate" hreflang="x-default" href="' . esc_url( get_permalink() ) . '">' . "\n";
    }
}
add_action( 'wp_head', 'revforge_hreflang', 3 );

// ── Title separator ───────────────────────────────────────────────────────
function revforge_title_separator( $sep ) {
    return '|';
}
add_filter( 'document_title_separator', 'revforge_title_separator' );

// ── Sitemap ping after publish ────────────────────────────────────────────
function revforge_ping_sitemap( $post_id ) {
    if ( wp_is_post_revision( $post_id ) ) return;
    // Google is notified automatically via Google Search Console; this pings manually
    $sitemap_url = home_url( '/sitemap.xml' );
    wp_remote_get( 'https://www.google.com/ping?sitemap=' . rawurlencode( $sitemap_url ), [ 'blocking' => false ] );
}
add_action( 'publish_post', 'revforge_ping_sitemap' );
