FieldSprout Brand (from provided assets) — REBUILD 2

Install (Flask):
Upload 'brand/' to /home/<cpanel_user>/flaskapp/static/brand/

<head> includes:
<link rel="icon" href="{{ url_for('static', filename='brand/favicon.ico') }}" sizes="any">
<link rel="icon" type="image/png" sizes="32x32" href="{{ url_for('static', filename='brand/icons/fieldsprout-icon-32.png') }}">
<link rel="icon" type="image/png" sizes="16x16" href="{{ url_for('static', filename='brand/icons/fieldsprout-icon-16.png') }}">
<link rel="apple-touch-icon" sizes="180x180" href="{{ url_for('static', filename='brand/icons/apple-touch-icon.png') }}">
<link rel="manifest" href="{{ url_for('static', filename='brand/site.webmanifest') }}">
<meta name="theme-color" content="#7c3aed">
