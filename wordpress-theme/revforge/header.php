<!DOCTYPE html>
<html <?php language_attributes(); ?>>
<head>
    <meta charset="<?php bloginfo( 'charset' ); ?>">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <link rel="profile" href="https://gmpg.org/xfn/11">
    <?php wp_head(); ?>
</head>
<body <?php body_class(); ?>>
<?php wp_body_open(); ?>

<header class="site-header" id="site-header">
    <div class="header-inner container">

        <a href="<?php echo esc_url( home_url( '/' ) ); ?>" class="site-logo" aria-label="RevForge Home">
            <svg class="logo-icon" width="22" height="22" viewBox="0 0 22 22" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
                <path d="M12.5 2L4 13h7l-1.5 7L18 9h-7l1.5-7z" fill="#1A5C35" stroke="#1A5C35" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
            </svg>
            <span class="logo-text">RevForge</span>
        </a>

        <?php
        wp_nav_menu( [
            'theme_location' => 'primary',
            'menu_class'     => 'primary-nav',
            'container'      => 'nav',
            'container_class'=> 'primary-nav-wrap',
            'container_id'   => 'primary-nav',
            'fallback_cb'    => function() {
                echo '<nav class="primary-nav-wrap" id="primary-nav"><ul class="primary-nav">';
                echo '<li><a href="' . esc_url( home_url( '/' ) ) . '">Home</a></li>';
                echo '<li><a href="' . esc_url( home_url( '/features' ) ) . '">Features</a></li>';
                echo '<li><a href="' . esc_url( home_url( '/pricing' ) ) . '">Pricing</a></li>';
                echo '<li><a href="' . esc_url( home_url( '/blog' ) ) . '">Blog</a></li>';
                echo '</ul></nav>';
            },
        ] );
        ?>

        <div class="header-actions">
            <a href="<?php echo revforge_app_url(); ?>login" class="btn-link">Log in</a>
            <a href="<?php echo revforge_app_url(); ?>register" class="btn btn-primary btn-sm">Get Started Free</a>
        </div>

        <button class="hamburger" id="hamburger" aria-label="Toggle menu" aria-expanded="false">
            <span></span>
            <span></span>
            <span></span>
        </button>

    </div>

    <div class="mobile-nav" id="mobile-nav" aria-hidden="true">
        <ul class="mobile-nav-list">
            <li><a href="<?php echo esc_url( home_url( '/' ) ); ?>">Home</a></li>
            <li><a href="<?php echo esc_url( home_url( '/features' ) ); ?>">Features</a></li>
            <li><a href="<?php echo esc_url( home_url( '/pricing' ) ); ?>">Pricing</a></li>
            <li><a href="<?php echo esc_url( home_url( '/blog' ) ); ?>">Blog</a></li>
        </ul>
        <div class="mobile-nav-cta">
            <a href="<?php echo revforge_app_url(); ?>login" class="btn btn-outline btn-block">Log in</a>
            <a href="<?php echo revforge_app_url(); ?>register" class="btn btn-primary btn-block">Get Started Free</a>
        </div>
    </div>
</header>

<div id="page-wrap">
