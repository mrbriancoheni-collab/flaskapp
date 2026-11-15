</div><!-- #page-wrap -->

<footer class="site-footer">
    <div class="footer-top">
        <div class="container footer-grid">

            <div class="footer-brand">
                <a href="<?php echo esc_url( home_url( '/' ) ); ?>" class="footer-logo" aria-label="RevForge Home">
                    <svg width="20" height="20" viewBox="0 0 22 22" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
                        <path d="M12.5 2L4 13h7l-1.5 7L18 9h-7l1.5-7z" fill="#34a85a" stroke="#34a85a" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
                    </svg>
                    <span>RevForge</span>
                </a>
                <p class="footer-tagline">Google Ads automation built for trade contractors. Win more local leads, spend less doing it.</p>
                <div class="footer-social">
                    <a href="#" aria-label="Twitter/X" class="social-link">
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-5.214-6.817L4.99 21.75H1.68l7.73-8.835L1.254 2.25H8.08l4.713 6.231zm-1.161 17.52h1.833L7.084 4.126H5.117z"/></svg>
                    </a>
                    <a href="#" aria-label="LinkedIn" class="social-link">
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><path d="M20.447 20.452h-3.554v-5.569c0-1.328-.027-3.037-1.852-3.037-1.853 0-2.136 1.445-2.136 2.939v5.667H9.351V9h3.414v1.561h.046c.477-.9 1.637-1.85 3.37-1.85 3.601 0 4.267 2.37 4.267 5.455v6.286zM5.337 7.433a2.062 2.062 0 01-2.063-2.065 2.064 2.064 0 112.063 2.065zm1.782 13.019H3.555V9h3.564v11.452zM22.225 0H1.771C.792 0 0 .774 0 1.729v20.542C0 23.227.792 24 1.771 24h20.451C23.2 24 24 23.227 24 22.271V1.729C24 .774 23.2 0 22.222 0h.003z"/></svg>
                    </a>
                </div>
            </div>

            <div class="footer-col">
                <h4 class="footer-col-title">Product</h4>
                <ul class="footer-links">
                    <li><a href="<?php echo esc_url( home_url( '/features' ) ); ?>">Features</a></li>
                    <li><a href="<?php echo esc_url( home_url( '/pricing' ) ); ?>">Pricing</a></li>
                    <li><a href="<?php echo revforge_app_url(); ?>register">Free Trial</a></li>
                    <li><a href="<?php echo revforge_app_url(); ?>">App Login</a></li>
                </ul>
            </div>

            <div class="footer-col">
                <h4 class="footer-col-title">Resources</h4>
                <ul class="footer-links">
                    <li><a href="<?php echo esc_url( home_url( '/blog' ) ); ?>">Blog</a></li>
                    <li><a href="<?php echo esc_url( home_url( '/guides' ) ); ?>">Ad Guides</a></li>
                    <li><a href="<?php echo esc_url( home_url( '/tools' ) ); ?>">Free Tools</a></li>
                    <li><a href="<?php echo esc_url( home_url( '/changelog' ) ); ?>">Changelog</a></li>
                </ul>
            </div>

            <div class="footer-col">
                <h4 class="footer-col-title">Company</h4>
                <ul class="footer-links">
                    <li><a href="<?php echo esc_url( home_url( '/about' ) ); ?>">About</a></li>
                    <li><a href="<?php echo esc_url( home_url( '/contact' ) ); ?>">Contact</a></li>
                    <li><a href="<?php echo esc_url( home_url( '/privacy' ) ); ?>">Privacy Policy</a></li>
                    <li><a href="<?php echo esc_url( home_url( '/terms' ) ); ?>">Terms of Service</a></li>
                </ul>
            </div>

        </div>
    </div>

    <div class="footer-bottom">
        <div class="container footer-bottom-inner">
            <p class="footer-copy">&copy; <?php echo date( 'Y' ); ?> RevForge. All rights reserved.</p>
            <a href="<?php echo revforge_app_url(); ?>" class="footer-app-link">App Login &rarr;</a>
        </div>
    </div>
</footer>

<?php wp_footer(); ?>
</body>
</html>
