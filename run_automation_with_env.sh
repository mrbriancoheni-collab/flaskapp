#!/bin/bash
# Run lead automation with environment variables

# IMPORTANT: Set your actual database credentials below
# Replace these with your production values:
export SQLALCHEMY_DATABASE_URI="mysql+pymysql://username:password@127.0.0.1:3306/fieldspark?charset=utf8mb4"

# Mailgun API credentials (required for email sending)
export MAILGUN_API_KEY="your-mailgun-api-key-here"
export MAILGUN_DOMAIN="mg.fieldsprout.io"
export MAILGUN_FROM_EMAIL="noreply@mg.fieldsprout.io"
export MAILGUN_FROM_NAME="FieldSprout"

# SerpAPI key (required for scraping)
export SERPAPI_API_KEY="your-serpapi-key-here"

# Run the automation
cd /home/user/flaskapp
flask run-lead-automation
