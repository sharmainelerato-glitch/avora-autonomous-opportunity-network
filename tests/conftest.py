"""Keep all automated test accounts, orders and providers out of the user's live AVORA database."""
import atexit
import os
import shutil
import tempfile
from pathlib import Path

_test_home=Path(tempfile.mkdtemp(prefix='avora_test_isolation_'))
os.environ['LAPENG_DB']=str(_test_home/'avora-test.sqlite3')
atexit.register(lambda:shutil.rmtree(_test_home,ignore_errors=True))
