import os
import sys

from hpn_cli.cli import main

try:
    main()
except KeyboardInterrupt:
    sys.exit(130)
except BrokenPipeError:
    os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
    sys.exit(1)
