# BattleBugs Sample Data

Use `scripts/seed_sample_data.py` to load a local demo arena from the images in
`test bugs/`.

```bash
flask db upgrade
python scripts/seed_sample_data.py
```

For a disposable database:

```bash
DATABASE_URL=sqlite:////tmp/battlebugs-sample.db \
UPLOAD_FOLDER=/tmp/battlebugs-sample-uploads \
python scripts/seed_sample_data.py --create-schema
```

## Sample Accounts

All sample users use password `battlebugs`.

| Username | Role | Purpose |
| --- | --- | --- |
| `owner_ivy` | OWNER | Full admin and owner workflows |
| `mod_mason` | MODERATOR | Moderation and review workflows |
| `collector_nova` | USER | Strong collection with multiple bugs |
| `field_scout_rin` | USER | Tournament-ready scout profile |
| `arena_jo` | USER | Regular player with comments and lore |

## Image Inputs

- Positive examples are read from `test bugs/`.
- Negative examples are read from `test bugs/negative tests/`.
- The script writes `sample_data/submission_image_manifest.json` listing both sets.

The negative images are not inserted as bugs. They are reference inputs for
submission rejection checks such as cartoons, diagrams, non-bugs, and noisy
search-result images.
