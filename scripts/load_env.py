"""
Environment loader for scripts - works with or without python-dotenv.

This module ensures environment variables are loaded before importing the Flask app.
"""
import os
import sys


def load_environment(project_root=None):
    """
    Load environment variables from .env file or environment.

    Args:
        project_root: Path to project root. Auto-detected if not provided.

    Returns:
        bool: True if environment was loaded successfully
    """
    if project_root is None:
        # Auto-detect project root
        script_dir = os.path.dirname(os.path.abspath(__file__))
        project_root = os.path.dirname(script_dir)

    # Change to project root
    os.chdir(project_root)

    # Add to Python path
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

    # Check multiple possible .env file locations
    env_paths = [
        os.path.join(project_root, '.env'),           # /home/fieldsprout/flaskapp/.env
        os.path.join(os.path.dirname(project_root), '.env'),  # /home/fieldsprout/.env
        os.path.expanduser('~/.env'),                  # /home/fieldsprout/.env (home directory)
    ]

    # Try to load .env file using python-dotenv
    env_loaded = False
    try:
        from dotenv import load_dotenv
        for env_path in env_paths:
            if os.path.exists(env_path):
                load_dotenv(env_path)
                print(f"✓ Loaded environment from {env_path}")
                env_loaded = True
                break

        if not env_loaded:
            print(f"ℹ No .env file found at any of: {', '.join(env_paths)}")
    except ImportError:
        print("ℹ python-dotenv not available, using manual loader")

    # Manual .env loader (fallback if python-dotenv not installed or failed)
    if not env_loaded:
        for env_path in env_paths:
            if os.path.exists(env_path):
                loaded_count = 0
                with open(env_path, 'r') as f:
                    for line in f:
                        line = line.strip()
                        # Skip comments and empty lines
                        if not line or line.startswith('#'):
                            continue

                        # Parse KEY=VALUE
                        if '=' in line:
                            key, value = line.split('=', 1)
                            key = key.strip()
                            value = value.strip()

                            # Remove quotes if present
                            if value.startswith('"') and value.endswith('"'):
                                value = value[1:-1]
                            elif value.startswith("'") and value.endswith("'"):
                                value = value[1:-1]

                            # Only set if not already in environment
                            if key not in os.environ:
                                os.environ[key] = value
                                loaded_count += 1

                print(f"✓ Manually loaded {loaded_count} variables from {env_path}")
                env_loaded = True
                break

    # Check if critical environment variables are already set
    critical_vars = ['SQLALCHEMY_DATABASE_URI']
    missing = [var for var in critical_vars if not os.environ.get(var)]

    if missing:
        print(f"⚠ Warning: Missing environment variables: {', '.join(missing)}")
        print(f"⚠ Searched for .env at:")
        for path in env_paths:
            exists = "✓" if os.path.exists(path) else "✗"
            print(f"   {exists} {path}")
        print(f"⚠ Please ensure environment variables are set or create a .env file")
        return False
    else:
        if env_loaded:
            print(f"✓ Environment loaded successfully")
        else:
            print(f"✓ Using existing environment variables")
        return True


def ensure_app_can_initialize():
    """
    Ensure the Flask app can be initialized by checking for required environment variables.

    Raises:
        RuntimeError: If critical environment variables are missing
    """
    if not os.environ.get('SQLALCHEMY_DATABASE_URI'):
        raise RuntimeError(
            "SQLALCHEMY_DATABASE_URI environment variable is not set.\n"
            "Please either:\n"
            "  1. Create a .env file in the project root with SQLALCHEMY_DATABASE_URI=...\n"
            "  2. Set the environment variable before running this script\n"
            "  3. Install python-dotenv: pip install python-dotenv"
        )
