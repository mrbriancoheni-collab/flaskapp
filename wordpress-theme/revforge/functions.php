<?php
/**
 * RevForge theme functions
 */

if ( ! defined( 'ABSPATH' ) ) exit;

// ── Theme setup ───────────────────────────────────────────────────────────────
function revforge_setup() {
    add_theme_support( 'title-tag' );
    add_theme_support( 'post-thumbnails' );
    add_theme_support( 'custom-logo', [
        'height'      => 40,
        'width'       => 160,
        'flex-height' => true,
        'flex-width'  => true,
    ] );
    add_theme_support( 'html5', [
        'search-form', 'comment-form', 'comment-list', 'gallery', 'caption', 'style', 'script',
    ] );
    add_theme_support( 'automatic-feed-links' );
    add_theme_support( 'align-wide' );

    register_nav_menus( [
        'primary' => __( 'Primary Navigation', 'revforge' ),
        'footer'  => __( 'Footer Navigation', 'revforge' ),
    ] );
}
add_action( 'after_setup_theme', 'revforge_setup' );

// ── Widgets / Sidebars ────────────────────────────────────────────────────────
function revforge_widgets_init() {
    register_sidebar( [
        'name'          => __( 'Blog Sidebar', 'revforge' ),
        'id'            => 'blog-sidebar',
        'description'   => __( 'Widgets in this area will be shown on blog posts.', 'revforge' ),
        'before_widget' => '<div class="widget %2$s">',
        'after_widget'  => '</div>',
        'before_title'  => '<h3 class="widget-title">',
        'after_title'   => '</h3>',
    ] );
}
add_action( 'widgets_init', 'revforge_widgets_init' );

// ── Enqueue assets ────────────────────────────────────────────────────────────
function revforge_enqueue_assets() {
    wp_enqueue_style(
        'revforge-fonts',
        'https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap',
        [],
        null
    );
    wp_enqueue_style(
        'revforge-main',
        get_template_directory_uri() . '/assets/css/main.css',
        [ 'revforge-fonts' ],
        '1.0.0'
    );
    wp_enqueue_script(
        'revforge-main',
        get_template_directory_uri() . '/assets/js/main.js',
        [],
        '1.0.0',
        true
    );
}
add_action( 'wp_enqueue_scripts', 'revforge_enqueue_assets' );

// ── App URL helper ────────────────────────────────────────────────────────────
function revforge_app_url() {
    $url = apply_filters( 'revforge_app_url', '/app/' );
    return esc_url( $url );
}

// ── Excerpt length ────────────────────────────────────────────────────────────
function revforge_excerpt_length( $length ) {
    return 20;
}
add_filter( 'excerpt_length', 'revforge_excerpt_length', 999 );

function revforge_excerpt_more( $more ) {
    return '&hellip;';
}
add_filter( 'excerpt_more', 'revforge_excerpt_more' );

// ── Body classes ──────────────────────────────────────────────────────────────
function revforge_body_classes( $classes ) {
    if ( ! is_singular() ) {
        $classes[] = 'hfeed';
    }
    return $classes;
}
add_filter( 'body_class', 'revforge_body_classes' );
