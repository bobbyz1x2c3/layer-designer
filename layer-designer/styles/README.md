# Style Library

Workspace-level reusable design styles for the Layer Designer workflow.

Each subdirectory under `styles/` is one style. A style is consumed by the
workflow via `--style <name>` (resolved against this directory) or
`--style-from <path>` (explicit absolute / relative path).

## Layout

```
styles/
├── README.md              (this file)
├── saas-blue/             (one style folder)
│   ├── style.json         (required — schema v1.0)
│   ├── button.png         (optional reference image)
│   ├── sidebar.png
│   └── card.png
└── retro-arcade/
    ├── style.json
    └── neon-frame.png
```

A style folder must contain `style.json`. Reference images are optional
(0–N; soft cap ≈ 3, `generate_image.py edit` enforces a hard cap of 5
images per call).

## Reference docs

- **Consumption** — how `--style` affects each phase, prompt construction
  rules, compatibility matrix:
  `references/style-library.md`

- **Generation** — how to create a new style via
  `export_style.py from-project` / `manual` / `add-reference`, reference
  image selection guidance, naming conventions:
  `references/style-generation.md`

## Quick start

Use an existing style:

```bash
python scripts/generate_image.py edit --config config.json \
  --style saas-blue --control-type button \
  --image preview.png --prompt "Extract the submit button" \
  --output button.png --size 256x64 --quality low --phase layer
```

Export a style from a finished project:

```bash
python scripts/export_style.py from-project \
  --config config.json --project my-app --name saas-blue \
  --description "Internal SaaS dashboard"
```

Create a blank style template:

```bash
python scripts/export_style.py manual --name retro-arcade \
  --description "80s neon arcade"
```

Styles are workspace-scoped — commit them to git when you want them
shared across the team.
