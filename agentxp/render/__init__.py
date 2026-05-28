"""Render-time helpers for AgentXP.

Includes the voice audit (D5 / NDS-3 / M67) that runs at render time and
emits stderr warnings without blocking. See voice_audit.py.

Also exposes the verdict-first experiment-report renderer (§21). See report.py.
"""
