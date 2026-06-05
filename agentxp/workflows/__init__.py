"""Skill-callable Python helpers for the lean-agentic v3 surface.

Each module in this package corresponds to one slash command / verb:

  - workflows.design     → /design skill helper functions
  - workflows.analyze    → /analyze skill helper functions
  - workflows.audit      → /audit skill helper functions
  - workflows.readouts   → /readouts skill helper functions
  - workflows.resume     → first-turn behavior helpers (NOT a slash command;
                            /resume is reserved by Claude Code)
  - workflows.connect    → /connect-data skill helper (interactive wizard)

Skills import these directly. There is no CLI. See agentxp/INDEX.md for
the public function catalog.
"""
