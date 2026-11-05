<form class="search-form" role="search" method="get" action="<?php echo esc_url( home_url( '/' ) ); ?>">
    <div class="search-form__inner">
        <input
            type="search"
            class="search-form__input"
            placeholder="<?php echo esc_attr_x( 'Search articles&hellip;', 'placeholder', 'revforge' ); ?>"
            value="<?php echo get_search_query(); ?>"
            name="s"
            aria-label="<?php esc_attr_e( 'Search for:', 'revforge' ); ?>"
        >
        <button type="submit" class="search-form__btn" aria-label="<?php esc_attr_e( 'Search', 'revforge' ); ?>">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" aria-hidden="true">
                <circle cx="11" cy="11" r="8"/><path d="M21 21l-4.35-4.35"/>
            </svg>
        </button>
    </div>
</form>
