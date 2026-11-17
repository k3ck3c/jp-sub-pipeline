"""Point d'entrée historique : `python main.py --input URL` fonctionne toujours.

Le code vit désormais dans le package `jpsub` (voir `python -m jpsub --help`).
"""

import sys

from jpsub.cli import main

if __name__ == "__main__":
    sys.exit(main())
