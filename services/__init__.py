"""NeuroLady application services (architecture.md §3 / §6.3).

The first vertical slice (feature F-001, onboarding) lives in `services.bot`. Heavy model
runners (`chat/`, `image/`, `video/`) stay isolated with their own environments (§6.2c) and
are not imported from here.
"""
