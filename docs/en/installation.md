# Install the signed beta

[Home](../../README.md) · [Русский](../ru/installation.md)

Native installation for macOS, Linux and Windows (without Docker): [complete setup package](../setup/README.md). It includes SQLite, AgentMemory/iii, Neo4j/Graphiti, Zvec, Serena, Mirage and observability. Follow its native runtime configuration before enabling Foundation.

Use a new profile. The package does not replace a running Hermes or configure your credentials. The tested Hermes base is 0.21.3 at commit `2034126e0d1f397b4612782156097243dbbdc819`. Foundation includes a separate Telegram callback-authorization patch; compatibility must be checked before applying it to another revision. Internal plugin IDs remain `ultra-deep-research` and `hermes-foundation-bridge`.

Python ≥3.11 is required; Python 3.13, macOS and Linux arm64 were tested. PDF extraction needs Poppler or `pdfplumber==0.11.9`. Hermes does not automatically install plugin dependencies. Configure service connections, API/OAuth and model selection in your profile. Foundation additionally needs Beads 1.1.0, Dolt 2.2.1, its declared dependencies and the services pinned in bridge-lock.json.

## Verify the distribution

The trusted public key SHA-256 is `2295aaab3cb418c4f81a867a701a8187e8cdd0f73105a1f318c1faf981dfdb1a`. Establish that fingerprint through an independent trusted channel, including the predecessor publication. Downloading a key beside an archive alone does not establish trust. GitHub CLI, Minisign and unzip are needed.
```sh
export HERMES_HOME="$HOME/.hermes-udr-beta"
export HERMES_FOUNDATION_ROOT="$HERMES_HOME/foundation"
mkdir hermes-udr-download
cd hermes-udr-download
gh release download v0.44.0-beta.2 --repo olegeklepikov-collab/hermes-udr
minisign -Vm SHA256SUMS -p release-signing.pub
shasum -a 256 -c SHA256SUMS
minisign -Vm hermes-research-report-0.44.0b2.zip -p release-signing.pub
minisign -Vm hermes-foundation-bridge-0.14.0b1.zip -p release-signing.pub
unzip -n hermes-research-report-0.44.0b2.zip -d research-source
unzip -n hermes-foundation-bridge-0.14.0b1.zip -d foundation-source
```

## Install the verified bytes

Configure a local Git author name and email first. The local installation commit differs from the development source commit; the archive manifest defines its exact contents.
```sh
python3 - <<'PYCODE'
import json, subprocess
from pathlib import Path
for folder in ("research-source", "foundation-source"):
    root = Path(folder).resolve()
    manifest = json.loads((root / "bundle-manifest.json").read_text(encoding="utf-8"))
    files = [row["path"] for row in manifest["files"]] + ["bundle-manifest.json"]
    subprocess.run(["git", "-C", str(root), "init", "-b", "release"], check=True)
    subprocess.run(["git", "-C", str(root), "config", "core.autocrlf", "false"], check=True)
    subprocess.run(["git", "-C", str(root), "add", "--", *files], check=True)
    subprocess.run(["git", "-C", str(root), "commit", "-m", "Verified Hermes UDR beta package"], check=True)
PYCODE
UDR_REF="$(git -C research-source rev-parse HEAD)"
FOUNDATION_REF="$(git -C foundation-source rev-parse HEAD)"
hermes plugins install "file://$PWD/research-source" --ref "$UDR_REF" --no-enable --force
hermes plugins install "file://$PWD/foundation-source" --ref "$FOUNDATION_REF" --no-enable
hermes plugins doctor ultra-deep-research --ci
hermes plugins doctor hermes-foundation-bridge --ci
hermes plugins enable ultra-deep-research --no-allow-tool-override
```

Standalone Research only needs the first plugin: configure a model class and run `python "$HERMES_HOME/plugins/ultra-deep-research/skills/research/scripts/run_research.py" --question "Your question" --mode research`. Foundation is optional for that route.


The signed Research archive triggers Hermes community-source heuristics for a forbidden-file list, environment-reference parsing, subprocess use and binary file signatures. Review these findings before accepting the exact verified archive with `--force`; scanning and the catalog kill list remain enabled. This is not advice to force-install arbitrary plugins.

## Managed operation

Before enabling Foundation, provision its services using `components/foundation/README.md` and `DOLT_SQL.md`. Keep both complete plugin directories. Add their `src` directories to the host Python session's PYTHONPATH. Set `research.integration_mode: foundation` and an absolute `research.workspace_root` in the chosen profile. Configure allowed provider operations with `research.web_provider_allowlist`; an empty mapping disables the generic provider selector, not extension by new services.

The existing host creates ResearchWorkContractV1, claims work/acquires a lease and calls `run_in_host` on its own AIAgent. The model cannot grant its own admission. See [Foundation APIs](../reference/foundation.md). Plugin Python runs in the Hermes process: in foundation mode, an approved isolated parser processes acquired raw files.

Signing does not provision services or activate an instance. Place the Foundation ZIP, its .minisig and the public key under `$HERMES_FOUNDATION_ROOT/releases/hermes-foundation-bridge-0.14.0b1/`, then call `foundation_release_verify` with version 0.14.0b1 and the source commit from the package manifest. Production activation remains an instance-owner decision.
