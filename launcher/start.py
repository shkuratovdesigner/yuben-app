"""Start the prebuilt distribution with its already-provisioned Python."""
import argparse
from pathlib import Path
import sys

root = Path(__file__).resolve().parents[1] / "app"
sys.path.insert(0, str(root))
import yuben

parser = argparse.ArgumentParser(description="Start packaged YuBen")
parser.add_argument("--no-browser", action="store_true")
args = parser.parse_args()
try:
    yuben.serve(Path(sys.executable), no_browser=args.no_browser)
except yuben.LauncherError as exc:
    print(f"yuben: {exc}", file=sys.stderr)
    sys.exit(1)
except KeyboardInterrupt:
    sys.exit(130)
