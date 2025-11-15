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

- Python 3.10 or higher
- Docker Desktop (optional, for containerized deployment)
- Anthropic API key (for AI battle narratives)

### Local Development Setup

1. **Clone or download this repository**

```bash
cd bug-arena
```

2. **Create a virtual environment**

```bash
python -m venv .venv

# Activate it:
# Mac/Linux:
source .venv/bin/activate
# Windows:
.venv\Scripts\activate
```

3. **Install dependencies**

```bash
pip install -r requirements.txt
```

4. **Set up environment variables**

```bash
cp .env.example .env
```

Edit `.env` and add your Anthropic API key:
```
SECRET_KEY=your-secret-key-here
ANTHROPIC_API_KEY=your-anthropic-api-key
```

Get an Anthropic API key at: https://console.anthropic.com/

5. **Run the application**

```bash
python run.py
```

Visit `http://localhost:5000` in your browser

1. **Build and start the container**

```bash
docker-compose up -d --build
```

2. **Access the app**

Visit `http://your-server-ip:5000`

3. **View logs**

```bash
docker-compose logs -f
```

4. **Stop the container**

```bash
docker-compose down
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

Edit `app/services/llm_service.py`:
```python
def generate_battle_narrative(bug1, bug2, winner):
    # Modify the prompt here
```

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

```bash
# Create all tables
python -c "from app import create_app, db; app = create_app(); app.app_context().push(); db.create_all()"

# Drop all tables (careful!)
python -c "from app import create_app, db; app = create_app(); app.app_context().push(); db.drop_all()"
```

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

**Issue**: Database errors
- Delete `database/bug_arena.db` and restart
- Run database creation commands

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



