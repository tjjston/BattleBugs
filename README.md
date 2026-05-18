# Battle Bugs - Insect Gladiator Tournament

Welcome to Bug Arena! A web application where you and your friends can submit bugs you find in the wild and watch them battle in AI-generated gladiator matches.

## Features

- **Bug Submission**: Upload photos of bugs you find with custom names
- **AI Battle Narratives**: Watch epic battles powered by Claude AI
- **Tournament System**: Monthly tournaments with brackets
- **Hall of Fame**: Track the top performing bugs
- **Community Features**: Add lore, comment on bugs, upvote favorites
- **User Profiles**: Track your bug collection and stats

## Quick Start

### Prerequisites

- Python 3.10 or higher (only needed for non-Docker setups)
- Docker + Docker Compose (optional, for containerized deployment)
- At least one LLM provider:
  - **Ollama** (default — local, no API key needed; set `OLLAMA_API_URL` to your host)
  - **Anthropic**, **OpenAI**, or **DeepSeek** (set the corresponding `*_API_KEY`)

### Local Development Setup

1. **Clone the repository and `cd` into it**

2. **Install dependencies** — pick one of the following:

   **Option A — virtual environment (recommended):**

   ```bash
   python -m venv .venv
   # Activate it:
   source .venv/bin/activate          # Mac/Linux
   .venv\Scripts\activate             # Windows
   pip install -r requirements.txt
   ```

   **Option B — user install (no venv):**

   ```bash
   pip install --user -r requirements.txt
   ```

   **Option C — system install on PEP 668 distros (Arch, Debian 12+, Ubuntu 23.04+):**

   ```bash
   pip install --break-system-packages -r requirements.txt
   ```

   **Option D — skip Python entirely and use Docker** (see next section).

3. **Set up environment variables**

   ```bash
   cp .env.example .env
   ```

   Edit `.env` — at minimum set `SECRET_KEY` and configure one LLM provider. Defaults
   point at Ollama (`LLM_DEFAULT_PROVIDER=ollama`, `OLLAMA_API_URL=...`). For hosted
   providers, fill in the matching API key (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, or
   `DEEPSEEK_API_KEY`).

4. **Initialize / migrate the database**

   ```bash
   flask db upgrade
   ```

5. **Run the application**

   ```bash
   python run.py
   ```

   Visit `http://localhost:5000` in your browser.

### Docker Setup

1. **Create your `.env` file** (same as step 3 above — `docker-compose.yml` reads it).

2. **Build and start the container**

   ```bash
   docker compose up -d --build
   ```

3. **Apply migrations** (required after pulling new code that changes models):

   ```bash
   docker compose exec web flask db upgrade
   ```

4. **Access the app**

   Visit `http://localhost:5000` (or `http://your-server-ip:5000`).

5. **View logs**

   ```bash
   docker compose logs -f
   ```

6. **Stop the container**

   ```bash
   docker compose down
   ```

## Project Structure

```
bug-arena/
├── app/
│   ├── routes/          # URL routes and views
│   ├── services/        # Business logic (battle engine, LLM)
│   ├── static/          # CSS, JS, images
│   ├── templates/       # HTML templates
│   ├── __init__.py      # App factory
│   └── models.py        # Database models
├── uploads/             # User-uploaded bug images
├── database/            # SQLite database
├── config.py            # Configuration
├── run.py               # Application entry point
├── requirements.txt     # Python dependencies
├── Dockerfile           # Docker configuration
└── docker-compose.yml   # Docker Compose setup
```

## Usage Guide

### Submitting Your First Bug

1. Register an account
2. Click "Submit Bug"
3. Upload a photo of a bug you found
4. Give it a cool name (e.g., "Thunder Beetle")
5. Add a description (optional)
6. Submit!

Approved submissions and performance accolades award **Accolade Points**. Players spend
Accolade Points to apply stat regeneration, while moderator/admin maintenance edits do not
spend player currency.

### Creating Battles

1. Click "New Battle"
2. Select two bugs
3. Watch the AI generate an epic battle narrative!
4. The winner is determined by stats + some randomness

### Running Tournaments

1. Click "Tournaments"
2. Create a new tournament
3. Set a start date
4. Start the tournament when ready
5. Battles will be generated automatically

## Configuration

Edit `config.py` or set environment variables:

- `SECRET_KEY`: Flask secret key for sessions
- `ANTHROPIC_API_KEY`: Your Claude API key
- `DATABASE_URL`: Database connection (default: SQLite)
- `MAX_CONTENT_LENGTH`: Max upload size (default: 16MB)

## Database Schema

- **User**: username, email, password
- **Bug**: name, species, image, stats (attack, defense, speed)
- **Battle**: bug matchups, winner, AI narrative
- **Tournament**: tournament info, brackets, winners
- **Comment**: user comments on bugs
- **BugLore**: community-created lore

## Customization

### Changing Stats Calculation

Edit `app/services/battle_engine.py`:
```python
def determine_winner(bug1, bug2):
    # Modify this function to change battle logic
```

### Customizing AI Prompts

Edit `app/services/llm_manager.py`:
```python
def generate_battle_narrative(bug1, bug2, winner):
    # Modify the prompt here
```

### Background Jobs

BattleBugs uses APScheduler for lightweight background enrichment jobs. Visual lore,
taxonomy enrichment, and retryable maintenance work are tracked in the `job` table.

Useful settings:

- `ENABLE_BACKGROUND_JOBS`: run the in-process worker (default: true)
- `JOB_POLL_INTERVAL_SECONDS`: worker polling interval (default: 15)
- `ENABLE_DB_EXPLORER`: enable the admin DB explorer (default: false)
- `DB_EXPLORER_ALLOW_WRITES`: allow non-read SQL in the DB explorer (default: false)

### Bug Classification

Submissions use the local Hugging Face image classifier
`ph0masta/bug_classifier` by default. It predicts insect/spider genera, so
BattleBugs accepts confident predictions and rejects low-confidence images before
falling back to the LLM classifier when configured.

Useful settings:

- `HF_BUG_CLASSIFIER_ENABLED`: enable the Hugging Face classifier (default: true)
- `HF_BUG_CLASSIFIER_REQUIRED`: reject if the classifier cannot run (default: false)
- `HF_BUG_CLASSIFIER_MODEL`: model id (default: `ph0masta/bug_classifier`)
- `HF_BUG_CLASSIFIER_MIN_CONFIDENCE`: approval threshold (default: `0.45`)

### Adding New Features

1. Create new routes in `app/routes/`
2. Add templates in `app/templates/`
3. Update models in `app/models.py` if needed

## Development Tips

### Running Tests

```bash
pytest tests/
```

### Database Migrations

This project uses Alembic via Flask-Migrate. Migrations live in `migrations/versions/`.

```bash
# Apply all pending migrations (run this after every pull that touches models)
flask db upgrade

# Inside the docker container
docker compose exec web flask db upgrade

# Create a new migration after changing a model
flask db migrate -m "describe the change"

# Roll back the most recent migration
flask db downgrade -1
```

If you ever hit `sqlite3.OperationalError: no such column: …`, your DB is behind
the model. Back up `database/bug_arena.db`, then run `flask db upgrade`.

### Backup Database

```bash
cp database/bug_arena.db database/bug_arena_backup.db
```

## Deployment to Home Server

### Port Forwarding (Optional - for friends outside your network)

1. Log into your router
2. Forward port 5000 to your server's local IP
3. Use Dynamic DNS (e.g., DuckDNS) for a domain name

### Security Considerations

- Use strong SECRET_KEY in production
- Consider adding HTTPS (use nginx + Let's Encrypt)
- Limit to friends only (don't expose to internet without security)
- Regular backups of database and uploads

## Future Ideas

- [ ] Email notifications for tournaments
- [ ] More complex tournament brackets
- [ ] Bug trading between users
- [ ] Achievement/badge system
- [ ] Mobile app
- [ ] Video uploads of real bugs
- [ ] Admin panel for managing tournaments
- [ ] Bug power-ups and abilities
- [ ] Team battles (2v2, 3v3)

## Troubleshooting

**Issue**: Images not displaying
- Check that `uploads/` directory exists
- Verify file permissions

**Issue**: AI narratives not generating
- Confirm ANTHROPIC_API_KEY is set correctly
- Check API quota/rate limits

**Issue**: Database errors (e.g. `no such column: …`)
- Almost always means migrations are out of date — run `flask db upgrade`
  (or `docker compose exec web flask db upgrade`)
- Back up `database/bug_arena.db` first if the DB has real data

**Issue**: "Bad Request — The CSRF token has expired"
- Default token lifetime is 8h (configurable via `WTF_CSRF_TIME_LIMIT` in `.env`)
- Refresh the page to get a fresh token
- If it expires immediately, your session cookie isn't surviving a round-trip
  — check for `SESSION_COOKIE_SECURE`/`SESSION_COOKIE_SAMESITE` mismatches if
  you're behind a reverse proxy

**Issue**: Gunicorn `WORKER TIMEOUT` on LLM-bound routes
- The LLM call is taking longer than gunicorn's `--timeout` (1500s by default)
- Verify Ollama (or your provider) is reachable from the container:
  `docker compose exec web python -c "import urllib.request; print(urllib.request.urlopen('http://YOUR_OLLAMA_HOST:11434/api/tags', timeout=10).status)"`
- For models with cold-load times >25 min, raise gunicorn `--timeout` in the
  `Dockerfile` (and keep urllib timeout in `llm_manager.py` below it)

**Issue**: Port 5000 already in use
- Change port in `run.py` and `docker-compose.yml`

## License

This project is for personal/educational use. Have fun!

## Contributing

This is a personal project for you and your friends! Feel free to:
- Add new features
- Improve the battle algorithm
- Create better UI/UX
- Add more bug species data
