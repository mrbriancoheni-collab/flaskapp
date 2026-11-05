<?php
/**
 * Blog sidebar
 */
if ( ! is_active_sidebar( 'blog-sidebar' ) ) return;
?>
<aside class="blog-sidebar">
    <?php dynamic_sidebar( 'blog-sidebar' ); ?>
</aside>
