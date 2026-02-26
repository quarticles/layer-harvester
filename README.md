# Layer Harvester

Log in to WMS environments, fetch GetCapabilities, extract layers tagged with the `hazardlookup` keyword, and export results to an Excel workbook per environment group.

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
- [Environment variables](#environment-variables)
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

# Optional — see Environment variables below
SSL_VERIFY=false
FULL_LAYER_DETAILS=false
```

| Key                    | Required | Description                                                   |
| ---------------------- | -------- | ------------------------------------------------------------- |
| `USERNAME`             | yes      | Login username                                                |
| `PASSWORD`             | yes      | Login password                                                |
| `LOGIN_URL`            | yes      | POST endpoint that returns a JWT                              |
| `GET_CAPABILITIES_URL` | yes      | WMS GetCapabilities endpoint                                  |
| `BASE_URL`             | no       | Used to derive the output folder/filename slug                |
| `SSL_VERIFY`           | no       | Set to `false` to skip SSL certificate verification           |
| `FULL_LAYER_DETAILS`   | no       | Set to `false` to export layer names only (no other columns)  |

The JWT token is auto-detected from the login response by probing common field names (`token`, `access_token`, `accessToken`, `jwt`, `id_token`, `idToken`). `envs/` is git-ignored — credentials are never committed.

## Environment variables

Both options can be set in the `.env` credential file (per-environment) or as OS environment variables (global fallback). The `.env` file takes precedence.

### `SSL_VERIFY`

Disables SSL certificate verification. Useful when the target server uses a self-signed or internally-issued certificate.

```bash
# In .env file (per-environment)
SSL_VERIFY=false

# Or as OS env var (applies to all environments)
SSL_VERIFY=false python -m harvester
```

### `FULL_LAYER_DETAILS`

Controls how many columns are written to the Excel output.

| Value              | Columns exported                          |
| ------------------ | ----------------------------------------- |
| `true` (default)   | All columns (name, title, bbox, CRS, …)   |
| `false`            | Layer name only                           |

```bash
# In .env file (per-environment)
FULL_LAYER_DETAILS=false

# Or as OS env var
FULL_LAYER_DETAILS=false python -m harvester
```

Applies to all modes including `--mode pdf`.

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

The data source is printed before processing starts:
```
Source: live fetch from 2 credential file(s) in envs/
Source: cached JSON files in input/  (--no-fetch)
Source: cached JSON files in input/
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

Output filenames encode the source, detail level, and mode:

```
output/
  dev.example.com/
    20240101_120000_dev.example.com_live_layers.xlsx
    20240101_120000_dev.example.com_live_pdf_layers.xlsx      ← --mode pdf
    20240101_120000_dev.example.com_live_names_layers.xlsx    ← FULL_LAYER_DETAILS=false
    20240101_120000_dev.example.com_cached_layers.xlsx        ← --no-fetch
    20240101_120000_dev.example.com_cached_names_layers.xlsx  ← --no-fetch + names only
```

| Segment   | Meaning                                  |
| --------- | ---------------------------------------- |
| `live`    | Data fetched live from an env credential |
| `cached`  | Data read from existing `input/` JSON    |
| `names`   | `FULL_LAYER_DETAILS=false` — name only   |
| `pdf`     | `--mode pdf` — includes PDF V2 column    |

When no env files are present (manual input mode), the group directory name is used as the slug.

## Manual input (no fetch)

Drop WMS JSON files directly into `input/` and run with `--no-fetch`:

```
input/
  dev.json                       → output/base/<timestamp>_base_cached_layers.xlsx
  quarticle/
    dev.json                     → output/quarticle/<timestamp>_quarticle_cached_layers.xlsx
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

When `FULL_LAYER_DETAILS=false`, only the **Layer Name** column is written.

## Distributable binary

PyInstaller produces a self-contained binary. **Binaries are platform-specific** — a binary built on macOS will not run on Linux and vice versa.

### Build for the current platform

```bash
pip install pyinstaller
pyinstaller layer_harvester.spec
./dist/layer_harvester
```

### Build for Linux from macOS (via Docker)

```bash
docker run --rm \
  -v "$(pwd)":/src \
  -w /src \
  python:3.11-slim \
  bash -c "pip install pyinstaller rich openpyxl && pyinstaller layer_harvester.spec"
```

Then copy `dist/layer_harvester` to the Linux server — no Python or source code needed.

```bash
scp dist/layer_harvester user@server:~/layer-harvester/layer_harvester
```

> Check the server architecture first (`uname -m`). Add `--platform linux/arm64` to the Docker command for `aarch64` servers.

### Running the binary

```bash
./dist/layer_harvester --env /path/to/.quarticle.dev.env --mode pdf
./dist/layer_harvester --no-fetch
SSL_VERIFY=false FULL_LAYER_DETAILS=false ./dist/layer_harvester
```

The binary reads `envs/`, `input/`, and writes `output/` relative to its own location — [↑ back to table of contents](#table-of-contents).
