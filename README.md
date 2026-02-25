# Layer Harvester

Parses WMS `capabilities.json` files and extracts layers tagged with the `hazardlookup` keyword into an Excel workbook.

## Install

```bash
pip install -r requirements.txt
```

## Usage

```bash
python -m harvester                 # base output
python -m harvester --usage pdf     # includes PDF V2 column and breakdown
```

Output is written to `output/` — one workbook per group, one sheet per file.

## Input structure

Files placed directly in `input/` are treated as one group.
Files inside a subdirectory (e.g. `input/quarticle/`) produce a separate workbook under `output/quarticle/`.

```
input/
  dev.json                          → output/<timestamp>_base_layers.xlsx
  quarticle/
    dev.json                        → output/quarticle/<timestamp>_base_layers.xlsx
    graph.json
```

## Output columns

| Column                            | Description                                                                      |
| --------------------------------- | -------------------------------------------------------------------------------- |
| Layer Name                        | WMS layer identifier                                                             |
| Title                             | Human-readable title                                                             |
| Abstract                          | Layer description                                                                |
| Queryable                         | Whether the layer supports GetFeatureInfo                                        |
| CRS                               | Supported coordinate reference systems                                           |
| West / East / North / South Bound | Bounding box coordinates                                                         |
| Is Global                         | `Yes` if bbox spans ≥ 340° longitude and ≥ 120° latitude — highlighted in yellow |
| PDF V2                            | *(PDF mode only)* Suffix from `pdf:hazardlookup:<keyword>` in the keyword list   |
| Style Name(s)                     | Associated WMS styles                                                            |
| Keywords                          | Full keyword list                                                                |
