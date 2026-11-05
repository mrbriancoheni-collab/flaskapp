<?php
$colors = ['#e8f3ed','#dbeafe','#fef3c7','#fee2e2','#f3f4f6'];
$color  = $colors[ get_the_ID() % count($colors) ];
$cats   = get_the_category();
$cat    = $cats ? $cats[0]->name : 'General';
?>
<article id="post-<?php the_ID(); ?>" <?php post_class('post-card'); ?>>
    <div class="post-thumb" style="background:<?php echo $color; ?>;">
        <?php if ( has_post_thumbnail() ) : the_post_thumbnail('medium',['style'=>'width:100%;height:100%;object-fit:cover;']);
        else: echo '📰'; endif; ?>
    </div>
    <div class="post-body">
        <p class="post-category"><?php echo esc_html($cat); ?></p>
        <h2 class="post-title" style="font-size:16px;margin-bottom:8px;">
            <a href="<?php the_permalink(); ?>"><?php the_title(); ?></a>
        </h2>
        <p class="post-excerpt"><?php echo wp_trim_words( get_the_excerpt(), 18 ); ?></p>
        <div class="post-meta"><span><?php echo get_the_date(); ?></span></div>
        <a href="<?php the_permalink(); ?>" class="read-more" style="display:inline-block;margin-top:12px;">Read More &rarr;</a>
    </div>
</article>
