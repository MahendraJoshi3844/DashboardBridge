"""Services the API layer delegates to.

Thin by design (02-architecture): a route validates, authorises and delegates.
Nothing here knows about HTTP beyond raising `ApiException`, so the same code is
callable from a worker, the CLI, or the desktop shell.
"""
