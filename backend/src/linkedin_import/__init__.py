"""LinkedIn Job Applications import and analytics.

Imports the ``Job Applications.csv`` export from LinkedIn (user-downloaded via
``Get a copy of your data``) into a dedicated table, then exposes aggregate
stats as a companion widget to the main analytics page.

The table is populated out-of-band (by an operator running the import script)
and the FastAPI surface is read-only — this module never writes to
``linkedin_applications`` at request time.
"""
