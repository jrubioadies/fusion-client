"""Cliente compartido de Oracle Fusion.

Dos módulos con responsabilidades separadas, y la separación es deliberada:

- `bip`: BI Publisher por SOAP. SOLO LEE.
- `ess`: ERP Integration Service. SOLO ACTÚA.

No mezclar. Una lectura nunca debe poder disparar un job, y un job nunca
debe devolverse como si fuera un resultado de consulta.
"""

__version__ = "0.1.0"
