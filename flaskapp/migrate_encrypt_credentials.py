#!/usr/bin/env python3
"""
Migration script to encrypt existing plaintext credentials.

This script:
1. Finds GoogleOAuthToken records with plaintext credentials_json
2. Finds GoogleAdsAuth records with plaintext refresh_token
3. Encrypts them using the new crypto_utils system
4. Updates the database

Usage:
    python migrate_encrypt_credentials.py [--dry-run]

Options:
    --dry-run    Show what would be encrypted without making changes
"""

import sys
import argparse
from flask import Flask
from app import create_app
from app.models import GoogleAdsAuth
from app.models_google import GoogleOAuthToken
from app.crypto_utils import is_encrypted, encrypt_string, encrypt_json_credentials
from app import db


def migrate_google_oauth_tokens(dry_run=False):
    """Encrypt plaintext GoogleOAuthToken credentials."""
    print("\n=== Migrating GoogleOAuthToken records ===")

    tokens = GoogleOAuthToken.query.all()
    migrated_count = 0
    already_encrypted_count = 0
    error_count = 0

    for token in tokens:
        if not token.credentials_json:
            print(f"  Token {token.id}: Empty credentials, skipping")
            continue

        if is_encrypted(token.credentials_json):
            already_encrypted_count += 1
            print(f"  Token {token.id}: Already encrypted (product={token.product})")
            continue

        # Found plaintext credentials
        print(f"  Token {token.id}: Found plaintext credentials (product={token.product})")

        if dry_run:
            print(f"  Token {token.id}: [DRY RUN] Would encrypt credentials")
            migrated_count += 1
        else:
            try:
                # Get plaintext credentials, then re-save using setter which encrypts
                plaintext_creds = token.get_credentials()
                if plaintext_creds:
                    token.set_credentials(plaintext_creds)
                    db.session.add(token)
                    migrated_count += 1
                    print(f"  Token {token.id}: ✓ Encrypted successfully")
                else:
                    error_count += 1
                    print(f"  Token {token.id}: ✗ Could not parse credentials")
            except Exception as e:
                error_count += 1
                print(f"  Token {token.id}: ✗ Error encrypting: {e}")

    if not dry_run and migrated_count > 0:
        db.session.commit()
        print(f"\n✓ Committed {migrated_count} GoogleOAuthToken updates")

    print(f"\nGoogleOAuthToken Summary:")
    print(f"  Already encrypted: {already_encrypted_count}")
    print(f"  Newly encrypted: {migrated_count}")
    print(f"  Errors: {error_count}")

    return migrated_count, error_count


def migrate_google_ads_auth(dry_run=False):
    """Encrypt plaintext GoogleAdsAuth refresh tokens."""
    print("\n=== Migrating GoogleAdsAuth records ===")

    auths = GoogleAdsAuth.query.all()
    migrated_count = 0
    already_encrypted_count = 0
    error_count = 0

    for auth in auths:
        if not auth.refresh_token:
            print(f"  Auth {auth.id}: Empty refresh_token, skipping")
            continue

        if is_encrypted(auth.refresh_token):
            already_encrypted_count += 1
            print(f"  Auth {auth.id}: Already encrypted (customer={auth.customer_id})")
            continue

        # Found plaintext token
        print(f"  Auth {auth.id}: Found plaintext refresh_token (customer={auth.customer_id})")

        if dry_run:
            print(f"  Auth {auth.id}: [DRY RUN] Would encrypt refresh_token")
            migrated_count += 1
        else:
            try:
                # Get plaintext token, then re-save using setter which encrypts
                plaintext_token = auth.refresh_token
                auth.set_refresh_token(plaintext_token)
                db.session.add(auth)
                migrated_count += 1
                print(f"  Auth {auth.id}: ✓ Encrypted successfully")
            except Exception as e:
                error_count += 1
                print(f"  Auth {auth.id}: ✗ Error encrypting: {e}")

    if not dry_run and migrated_count > 0:
        db.session.commit()
        print(f"\n✓ Committed {migrated_count} GoogleAdsAuth updates")

    print(f"\nGoogleAdsAuth Summary:")
    print(f"  Already encrypted: {already_encrypted_count}")
    print(f"  Newly encrypted: {migrated_count}")
    print(f"  Errors: {error_count}")

    return migrated_count, error_count


def main():
    parser = argparse.ArgumentParser(description='Encrypt existing plaintext credentials')
    parser.add_argument('--dry-run', action='store_true',
                        help='Show what would be encrypted without making changes')
    args = parser.parse_args()

    print("=" * 60)
    print("Credential Encryption Migration Script")
    print("=" * 60)

    if args.dry_run:
        print("\n*** DRY RUN MODE - No changes will be made ***\n")

    # Create Flask app context
    app = create_app()

    with app.app_context():
        # Check if encryption key is configured
        fernet_key = app.config.get("APP_FERNET_KEY")
        if not fernet_key:
            print("\n✗ ERROR: APP_FERNET_KEY is not configured!")
            print("  Generate a key with:")
            print("    python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'")
            print("  Then set it in your environment or .env file")
            sys.exit(1)

        print(f"\n✓ Encryption key configured")

        # Run migrations
        oauth_migrated, oauth_errors = migrate_google_oauth_tokens(args.dry_run)
        ads_migrated, ads_errors = migrate_google_ads_auth(args.dry_run)

        # Final summary
        print("\n" + "=" * 60)
        print("Migration Complete")
        print("=" * 60)

        total_migrated = oauth_migrated + ads_migrated
        total_errors = oauth_errors + ads_errors

        if args.dry_run:
            print(f"\n[DRY RUN] Would encrypt {total_migrated} credentials")
            print(f"Run without --dry-run to apply changes")
        else:
            print(f"\n✓ Successfully encrypted {total_migrated} credentials")
            if total_errors > 0:
                print(f"✗ {total_errors} errors occurred - check logs above")
                sys.exit(1)

        print("\nDone!")


if __name__ == "__main__":
    main()
