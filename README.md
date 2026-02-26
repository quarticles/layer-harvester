# Layer Harvester

Fetches WMS capabilities from live environments, extracts layers tagged with the `hazardlookup` keyword, and writes an Excel workbook per environment group.

## Table of contents

- [Project structure](#project-structure)
- [Install](#install)
- [Usage](#usage)
  - [Default](#default)
  - [PDF mode](#pdf-mode)
  - [Skip fetch](#skip-fetch)
  - [Specific env file](#specific-env-file)
  - [Multiple env files](#multiple-env-files)
  - [Combine flags](#combine-flags)
- [Credential files](#credential-files-groupenvironmentenv)
- [Flow](#flow)
- [Fetch modes](#fetch-modes)
  - [Auto-scan (default)](#auto-scan-default)
  - [Specific file (--env)](#specific-file---env)
  - [Skip fetch (--no-fetch)](#skip-fetch---no-fetch)
- [Output naming](#output-naming)
- [Manual input (no fetch)](#manual-input-no-fetch)
- [Output columns](#output-columns)
- [Distributable binary](#distributable-binary)

## Project structure

```
harvester/
  __init__.py       — package marker
  __main__.py       — CLI entry point (argparse, rich UI, orchestration)
  core.py           — layer extraction, bbox detection, Excel writing
  fetcher.py        — login → JWT → GetCapabilities → save JSON (stdlib only)
  pdf.py            — PDF V2 column support (--mode pdf)
envs/               — credential files (.<group>.<environment>.env, git-ignored)
input/              — WMS JSON cache (git-ignored)
output/             — Excel workbooks (git-ignored, .gitkeep committed)
requirements.txt
```

## Install

```bash
pip install -r requirements.txt
```

## Usage

### Default
```bash
python -m harvester
```
Auto-scans `envs/` for credential files, fetches WMS capabilities, and writes Excel output.

### PDF mode
```bash
python -m harvester --mode pdf
```
Same as default, but adds a PDF V2 column and per-type breakdown in the summary.

### Skip fetch
```bash
python -m harvester --no-fetch
```
Skips network requests and processes whatever JSON files are already in `input/`.

### Specific env file
```bash
python -m harvester --env /path/to/.quarticle.dev.env
```
Fetches and harvests only the specified environment. Can be repeated for multiple files.

### Multiple env files
```bash
python -m harvester --env /path/.quarticle.dev.env --env /path/.allianz.prod.env
```

### Combine flags
```bash
python -m harvester --env /path/to/.quarticle.dev.env --mode pdf
```

## Credential files (`.<group>.<environment>.env`)

```ini
USERNAME=your_username
PASSWORD=your_password
BASE_URL=https://dev.example.com
LOGIN_URL=https://dev.example.com/graph/api/v1/login
GET_CAPABILITIES_URL=https://dev.example.com/graph/geoserver/wms?service=wms&version=1.3.0&request=GetCapabilities
```

| Key                    | Required | Description                                    |
| ---------------------- | -------- | ---------------------------------------------- |
| `USERNAME`             | yes      | Login username                                 |
| `PASSWORD`             | yes      | Login password                                 |
| `LOGIN_URL`            | yes      | POST endpoint that returns a JWT               |
| `GET_CAPABILITIES_URL` | yes      | WMS GetCapabilities endpoint                   |
| `BASE_URL`             | no       | Used to derive the output folder/filename slug |

The JWT token is auto-detected from the login response by probing common field names (`token`, `access_token`, `accessToken`, `jwt`, `id_token`, `idToken`). `envs/` is git-ignored — credentials are never committed.

## Flow

```
python -m harvester [--mode pdf] [--env FILE …] [--no-fetch]
          │
          ├─ --env FILE given?
          │       Yes ──► fetch specified file(s) ──► harvest ──► output/
          │
          No (auto-detect)
          │
          ▼
     --no-fetch flag?
          │       Yes ──► skip to input/ scan (see below)
          │
          No
          │
          ▼
     scan envs/ for .<group>.<environment>.env
          │
          ├─ files found? ──► fetch all ──► harvest ──► output/
          │
          not found
          │
          ▼  (notify: "No env files found — falling back to input/")
     scan input/ for *.json
          │
          ├─ files found? ──► harvest (no fetch) ──► output/
          │
          not found
          │
          ▼
     ✗  warn: "Nothing to do: no env files and no JSON files in input/"


--mode pdf  applies on top of whichever path is taken above
            (same logic, adds PDF V2 column + breakdown to output)
```

## Fetch modes

### Auto-scan (default)

Place credential files directly in `envs/` using the `.<group>.<environment>.env` pattern:

```
envs/
  .quarticle.dev.env
  .quarticle.prod.env
  .allianz.dev.env
```

The harvester logs in, fetches capabilities, saves them to `input/<group>/<env>.json`, then runs extraction for all groups.

### Specific file (`--env`)

Point at any `.<group>.<environment>.env` file on disk — useful when credential files live outside the project or you only want to refresh one environment:

```bash
python -m harvester --env ~/secrets/.quarticle.dev.env
python -m harvester --env ~/secrets/.quarticle.dev.env --env ~/secrets/.allianz.prod.env
```

The group name is derived from the filename (`.<group>.<environment>.env`). When `--env` is used, only the specified environments are fetched and harvested (no other `input/` files are processed).

### Skip fetch (`--no-fetch`)

Use whatever JSON files are already in `input/` without making any network requests. Output is still named using the hostname slug from any env files that are present.

## Output naming

Output workbooks are named using the hostname from `BASE_URL` (or `LOGIN_URL` as fallback):

```
output/
  dev.example.com/
    20240101_120000_dev.example.com_layers.xlsx
    20240101_120000_dev.example.com_pdf_layers.xlsx   ← --mode pdf
  prod.example.com/
    20240101_120000_prod.example.com_layers.xlsx
```

When no env files are present (manual input mode), the group directory name is used instead.

## Manual input (no fetch)

Drop WMS JSON files directly into `input/` and run with `--no-fetch`:

```
input/
  dev.json                       → output/base/<timestamp>_base_layers.xlsx
  quarticle/
    dev.json                     → output/quarticle/<timestamp>_quarticle_layers.xlsx
```

## Output columns

| Column                            | Description                                                                      |
| --------------------------------- | -------------------------------------------------------------------------------- |
| Layer Name                        | WMS layer identifier                                                             |
| Title                             | Human-readable title                                                             |
| Abstract                          | Layer description                                                                |
| Queryable                         | `1` = supports GetFeatureInfo; `0` = display-only                                |
| CRS                               | Supported coordinate reference systems                                           |
| West / East / North / South Bound | Bounding box coordinates                                                         |
| Is Global                         | `Yes` if bbox spans ≥ 340° longitude and ≥ 120° latitude — highlighted in yellow |
| PDF V2                            | _(PDF mode only)_ Suffix from `pdf:hazardlookup:<keyword>` in the keyword list   |
| Style Name(s)                     | Associated WMS styles                                                            |
| Keywords                          | Full keyword list                                                                |

## Distributable binary

A self-contained executable can be built with PyInstaller:

```bash
pip install pyinstaller
pyinstaller --onefile --name layer_harvester --collect-all rich harvester/__main__.py
```

The binary is written to `dist/layer_harvester` and supports all flags — [↑ back to table of contents](#table-of-contents).

```bash
./dist/layer_harvester --env /path/to/.quarticle.dev.env --mode pdf
./dist/layer_harvester --no-fetch
```

Run from any directory — it reads `envs/`, `input/`, and writes `output/` relative to the working directory.
