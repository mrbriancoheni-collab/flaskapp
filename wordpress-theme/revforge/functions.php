<?php
/**
 * RevForge theme functions
 */

if ( ! defined( 'ABSPATH' ) ) exit;

// ── SEO / AEO / GEO ───────────────────────────────────────────────────────────
require_once get_template_directory() . '/inc/seo.php';

// ── Theme setup ───────────────────────────────────────────────────────────────
function revforge_setup() {
    load_theme_textdomain( 'revforge', get_template_directory() . '/languages' );

    add_theme_support( 'title-tag' );
    add_theme_support( 'post-thumbnails' );
    add_image_size( 'revforge-hero',   1440, 600, true );
    add_image_size( 'revforge-card',    800, 450, true );
    add_image_size( 'revforge-thumb',   400, 225, true );
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
    add_theme_support( 'responsive-embeds' );
    add_theme_support( 'wp-block-styles' );

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
    // Google Fonts — also preconnected in header.php
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
        '1.1.0'
    );
    wp_enqueue_script(
        'revforge-main',
        get_template_directory_uri() . '/assets/js/main.js',
        [],
        '1.1.0',
        true
    );
    // Pass app URL to JS (used by dynamic CTAs)
    wp_localize_script( 'revforge-main', 'RevForge', [
        'appUrl' => esc_url( revforge_app_url() ),
        'ajaxUrl' => esc_url( admin_url( 'admin-ajax.php' ) ),
        'nonce'  => wp_create_nonce( 'revforge_ajax' ),
    ] );
}
add_action( 'wp_enqueue_scripts', 'revforge_enqueue_assets' );

// ── Font preload ──────────────────────────────────────────────────────────────
function revforge_preload_fonts() {
    // Preconnect declared in header.php; no additional preload tags needed here
}
add_action( 'wp_head', 'revforge_preload_fonts', 0 );

// ── App URL helper ────────────────────────────────────────────────────────────
function revforge_app_url() {
    // Default: /app/ (subdirectory). Override via Customizer or filter for subdomain.
    $url = get_theme_mod( 'revforge_app_url', '/app/' );
    $url = apply_filters( 'revforge_app_url', $url );
    return esc_url( trailingslashit( $url ) );
}

// ── Customizer ────────────────────────────────────────────────────────────────
function revforge_customizer( $wp_customize ) {
    $wp_customize->add_section( 'revforge_app', [
        'title'    => __( 'App Settings', 'revforge' ),
        'priority' => 160,
    ] );
    $wp_customize->add_setting( 'revforge_app_url', [
        'default'           => '/app/',
        'sanitize_callback' => 'esc_url_raw',
        'transport'         => 'refresh',
    ] );
    $wp_customize->add_control( 'revforge_app_url', [
        'label'       => __( 'App Base URL', 'revforge' ),
        'description' => __( 'e.g. /app/ for subdirectory or https://app.yourdomain.com/ for subdomain', 'revforge' ),
        'section'     => 'revforge_app',
        'type'        => 'url',
    ] );

    // Social links
    $wp_customize->add_section( 'revforge_social', [
        'title'    => __( 'Social Links', 'revforge' ),
        'priority' => 161,
    ] );
    foreach ( [ 'twitter' => 'Twitter / X URL', 'linkedin' => 'LinkedIn URL', 'facebook' => 'Facebook URL' ] as $key => $label ) {
        $wp_customize->add_setting( 'revforge_social_' . $key, [
            'default'           => '',
            'sanitize_callback' => 'esc_url_raw',
        ] );
        $wp_customize->add_control( 'revforge_social_' . $key, [
            'label'   => __( $label, 'revforge' ),
            'section' => 'revforge_social',
            'type'    => 'url',
        ] );
    }
}
add_action( 'customize_register', 'revforge_customizer' );

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

// Reading time estimate
if ( ! function_exists( 'get_the_reading_time_estimate' ) ) {
    function get_the_reading_time_estimate() {
        $words = str_word_count( strip_tags( get_the_content() ) );
        $mins  = max( 1, (int) ceil( $words / 200 ) );
        return $mins . ' min read';
    }
}
