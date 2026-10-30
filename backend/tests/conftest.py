"""Keep the pre-authentication regression suite in its original local-demo mode.
Dedicated test_auth.py explicitly turns authentication on and tests account isolation.
"""
import os
os.environ.setdefault("AUTH_REQUIRED", "false")
