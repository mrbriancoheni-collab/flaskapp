# RevForge: WordPress + Flask App Split Guide

This document covers every configuration needed to run the WordPress marketing site
and the Flask app side-by-side — first as `/app/` (subdirectory), then migrated to
`app.yourdomain.com` (subdomain).

---

## 1. Architecture overview

```
yourdomain.com/          → WordPress (marketing, blog, pricing, features)
yourdomain.com/app/      → Flask app  (Phase 1 — subdirectory)

app.yourdomain.com/      → Flask app  (Phase 2 — subdomain migration)
```

Both phases use the same Flask codebase; only the web-server routing changes.

---

## 2. Phase 1 — Subdirectory `/app/` on Apache

### 2a. WordPress `htaccess` (root `.htaccess`)

Replace the default WordPress block with the version below.
The key addition is the `RewriteCond` that skips WP's routing for anything
under `/app/`.

```apache
# BEGIN WordPress — with /app/ exclusion
<IfModule mod_rewrite.c>
RewriteEngine On
RewriteBase /

# Do NOT let WordPress intercept the Flask app
RewriteRule ^app(/.*)?$ - [L]

# Standard WordPress rules
RewriteRule ^index\.php$ - [L]
RewriteCond %{REQUEST_FILENAME} !-f
RewriteCond %{REQUEST_FILENAME} !-d
RewriteRule . /index.php [L]
</IfModule>
# END WordPress
```

### 2b. Flask / Passenger in `/app/`

Create a `passenger_wsgi.py` inside the directory the web root maps `/app/` to
(e.g. `public_html/app/passenger_wsgi.py`):

```python
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from flaskapp import create_app
application = create_app()
```

Add a `.htaccess` inside `public_html/app/`:

```apache
PassengerEnabled On
PassengerAppRoot /home/<user>/flaskapp/flaskapp
PassengerAppType wsgi
PassengerStartupFile passenger_wsgi.py
Options -MultiViews
```

### 2c. WordPress Customizer — App URL

1. WP Admin → Appearance → Customizer → **App Settings**
2. Set **App Base URL** to `/app/`
3. Save & Publish

This configures `revforge_app_url()` without editing any PHP.

---

## 3. Phase 2 — Subdomain `app.yourdomain.com`

### 3a. DNS

Add an A record (or CNAME to the host's server) for `app` pointing to the same
server IP. Most shared hosts create this in cPanel → Zone Editor.

### 3b. Apache VirtualHost for the subdomain

```apache
<VirtualHost *:443>
    ServerName app.yourdomain.com
    DocumentRoot /home/<user>/flaskapp/flaskapp/public

    <Directory /home/<user>/flaskapp/flaskapp/public>
        PassengerEnabled On
        PassengerAppRoot /home/<user>/flaskapp/flaskapp
        PassengerAppType wsgi
        PassengerStartupFile passenger_wsgi.py
        Options -MultiViews
        AllowOverride All
        Require all granted
    </Directory>

    SSLEngine On
    SSLCertificateFile    /etc/letsencrypt/live/app.yourdomain.com/fullchain.pem
    SSLCertificateKeyFile /etc/letsencrypt/live/app.yourdomain.com/privkey.pem
</VirtualHost>
```

For Nginx:

```nginx
server {
    listen 443 ssl http2;
    server_name app.yourdomain.com;

    ssl_certificate     /etc/letsencrypt/live/app.yourdomain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/app.yourdomain.com/privkey.pem;

    location / {
        proxy_pass         http://127.0.0.1:5000;
        proxy_set_header   Host $host;
        proxy_set_header   X-Real-IP $remote_addr;
        proxy_set_header   X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto $scheme;
    }
}
```

### 3b. SSL — Let's Encrypt

```bash
certbot --apache -d app.yourdomain.com
# or for Nginx:
certbot --nginx -d app.yourdomain.com
```

### 3c. Remove /app/ exclusion rule from WordPress `.htaccess`

Once traffic routes directly to the subdomain, the Flask exclusion rule in
WordPress's `.htaccess` is no longer needed (WordPress never sees those requests).
Remove lines 5-7 from the block in §2a.

### 3d. Update Customizer — App URL

1. WP Admin → Appearance → Customizer → **App Settings**
2. Change **App Base URL** to `https://app.yourdomain.com/`
3. Save & Publish

All `revforge_app_url()` calls on the marketing site (CTAs, nav buttons) will
automatically point to the subdomain — **no template edits required**.

---

## 4. Flask SESSION / CSRF cookies across origins

When migrating to a subdomain, Flask's session cookie domain must match.
In `config.py` / environment:

```python
# Phase 1 (subdirectory — same origin, no change needed)
SESSION_COOKIE_DOMAIN = None   # default

# Phase 2 (subdomain)
SESSION_COOKIE_DOMAIN = ".yourdomain.com"   # leading dot = all subdomains
SESSION_COOKIE_SECURE  = True
SESSION_COOKIE_SAMESITE = "Lax"
```

CSRF tokens in `WTForms` / `Flask-WTF` work across origins automatically
as long as the token is embedded in the form (default behaviour).

---

## 5. WordPress SEO: tell crawlers `/app/` is the app

Add to `robots.txt` (WP → Settings → Reading, or Yoast/RankMath):

```
User-agent: *
Disallow: /app/
Disallow: /app/login
Disallow: /app/register
Disallow: /app/account/
```

After migrating to a subdomain, the Flask app gets its own `robots.txt` at
`app.yourdomain.com/robots.txt` and WordPress's disallow rules can be removed.

---

## 6. Cross-domain redirects (post-migration)

Add these redirects in the Flask app to send old `/app/…` URLs to the new subdomain:

```python
# In a Blueprint or before_request hook
@app.before_request
def redirect_legacy_app_paths():
    # Only needed if old subdirectory links exist in the wild
    pass
```

Or via Apache rewrite in the WordPress root `.htaccess`:

```apache
RewriteRule ^app/(.*)$ https://app.yourdomain.com/$1 [R=301,L]
```

---

## 7. Quick checklist

| Step | Phase 1 | Phase 2 |
|------|---------|---------|
| Flask runs | ✅ `/app/` via Passenger | ✅ `app.subdomain` via Passenger/Gunicorn |
| WP intercepts `/app/` | Excluded via `.htaccess` | N/A — separate vhost |
| SSL on app | Shared cert | Dedicated cert (Let's Encrypt) |
| App URL in WP theme | `/app/` via Customizer | `https://app.yourdomain.com/` via Customizer |
| Session cookie domain | default | `.yourdomain.com` |
| robots.txt | Disallow `/app/` | Separate file on subdomain |
| DNS change | None | A record for `app` subdomain |
