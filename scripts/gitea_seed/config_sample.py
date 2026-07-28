# Synthetic fixture for secrets_scan.py's live verification (doc 05 §5.3
# "secrets scanner blocks 100% of seeded credentials") — every value below
# is fake, generated only to match the *shape* a real credential scanner
# looks for. Never a real secret; this repo is a throwaway local dev Gitea
# instance, not a real codebase.

AWS_ACCESS_KEY_ID = "AKIAIOSFODNN7EXAMPLE"
AWS_SECRET_ACCESS_KEY = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
GITHUB_TOKEN = "ghp_1234567890abcdef1234567890abcdefEXAMPLE"


def connect() -> None:
    """Not a real connection — this file exists only to be scanned."""
    raise NotImplementedError
