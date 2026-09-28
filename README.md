# Browser Workflow Agent

The Browser Workflow Agent converts a natural language goal into a json file that the replay agent can reuse for a workflow. It currently uses the ParaBank website to transfer funds from one account to another. The agent does not automate certain functions like credential entry; therefore, the operator must create a profile and a new financial account per focused run.

## Requirements

- Windows 10 or 11 (the default-browser launcher reads the Windows registry).
- Python 3.11 (Python 3.9 or later is required by the source).
- Chrome, Microsoft Edge, or Firefox installed as the Windows default browser. Selenium Manager may download the matching driver the first time it runs.
- Internet access to the ParaBank demo site for the live workflow.
- An OpenAI API key for discovery only. Replay does not call the OpenAI API.

## Setup

Run these commands from the repository root in PowerShell:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
$env:OPENAI_API_KEY = "<your OpenAI API key>"
# Optional; defaults to gpt-4.1-mini.
$env:OPENAI_MODEL = "gpt-4.1-mini"
```

The programs read `OPENAI_API_KEY` and `OPENAI_MODEL` from the process environment. They do not load `.env` automatically. Do not commit API keys, passwords, account numbers, or generated run reports. ParaBank credentials are entered manually in the browser and not stored by this project for safety purposes.

## Live Demo

Discover a transfer workflow and save it under a predictable run ID:

```powershell
python scripts/run_discovery.py --workflow transfer --run-id demo-transfer
```

The script will prompt the operator for a transfer amount and source/destination accounts. After validating the existence of these variables, it will open the operator's default browser and run the discovery agent against the Parabank website. For login and the final transfer, it will always prompt the user to confirm with a **Complete** button in the Chatbot. On success, the command prints the artifact path:

```text
reports/run_demo-transfer.artifact.json
```

Replay that artifact in a fresh browser session:

```powershell
python scripts/replay_artifact.py reports/run_demo-transfer.artifact.json
```

Replay prompts for the artifact's declared inputs and prints a JSON result. `success` exits with code 0, a known `business_outcome` exits with code 2, and `failure` exits with code 1. Replay records a JSONL run log under `reports/` and masks editable controls and likely financial DOM content before saving a failure screenshot. Masking is heuristic, so review and protect screenshots as potentially sensitive. Use a different `--run-id` for each discovery run; reusing an ID appends to its log and replaces its artifact.

## Inputs to `main.py`

`main.py` takes a required positional `mode` and a required `--goal`. The mode is either `discover` or `replay`. Replay also requires `--artifact-path`. In PowerShell, single quotes preserve `$` in a transfer amount:

```powershell
python main.py discover --goal 'Please transfer $100 from 20559 to 20670'
python main.py replay --goal 'Please transfer $100 from 20559 to 20670' --artifact-path 'evidence\run_successful_discovery.artifact.json'
```

Discovery uses the goal to select the workflow and extract its input values. Replay uses the goal for the run's parameters and the artifact path to load the recorded steps.

## Offline Checks

From the repository root in PowerShell, activate the project environment and run the full unit-test suite without opening a browser, contacting ParaBank, or requiring an API key:

```powershell
.\.venv\Scripts\Activate.ps1
python -m unittest discover -s tests -v
```

The suite covers parser repeatability, artifact redaction, replay success and output extraction, declared business outcomes, bounded transient retry, validation failures, and unexpected dialogs. This is an offline test path, not an end-to-end simulator of the live website or language model.

The command-line interfaces can also be inspected without starting services:

```powershell
python scripts/run_discovery.py --help
python scripts/replay_artifact.py --help
```

## Evidence

The [evidence bundle](evidence/README.md) includes a simulated transfer artifact and logs for successful discovery, successful replay, and replay with an incorrect synthetic destination account. It never moves real funds. Regenerate a fresh set without live services using:

```powershell
python scripts/generate_evidence.py --run-prefix transfer-demo-2
```

## Configuration and Results

- `config/inputs.json` declares supported workflows, expected input types, and success checks. The CLI currently exposes the configured `transfer` workflow.
- `config/paths.json` identifies the Windows registry location used to select the default browser.
- Newly generated version `1.1` artifacts are written as `reports/run_<run-id>.artifact.json`.
- Replay returns `success` with declared outputs, `business_outcome` for a known non-success result, or `failure` with step, expected/observed state, and evidence.
- Generated reports and local environment files are excluded from Git.