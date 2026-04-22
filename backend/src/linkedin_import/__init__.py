"""LinkedIn Job Applications import — data source for the analytics snapshot.

Imports the ``Job Applications.csv`` export from LinkedIn (user-downloaded via
``Get a copy of your data``) into a dedicated table. The data is then surfaced
inside the canonical ``AnalyticsRun`` snapshot by ``analytics_page.service`` —
this module has no dedicated HTTP surface on purpose, so there is exactly one
place (the snapshot) where LinkedIn + JobAnalysis metrics are combined.

The table is populated out-of-band (by an operator running
``scripts/import_linkedin_export.py``); the code here never writes to
``linkedin_applications`` at request time.
"""
