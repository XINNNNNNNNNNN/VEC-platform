"""Dash page modules.

Importing each ``stepN`` module is what triggers Dash callback registration
against ``vec_platform.runtime.dash_app``. main.py imports the modules at
startup so the callbacks exist before the first request.
"""
