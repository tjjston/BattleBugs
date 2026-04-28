import os
from dotenv import load_dotenv

basedir = os.path.abspath(os.path.dirname(__file__))
load_dotenv()

class Config:
    # Flask
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'dev-secret-key-change-in-production'
    
    # Database — resolve relative sqlite paths against the project root so the
    # app works regardless of the working directory it is launched from.
    _db_url = os.environ.get('DATABASE_URL') or \
        'sqlite:///' + os.path.join(basedir, 'database', 'bug_arena.db')
    if _db_url.startswith('sqlite:///') and not _db_url.startswith('sqlite:////'):
        _rel = _db_url[len('sqlite:///'):]
        if not os.path.isabs(_rel):
            _db_url = 'sqlite:///' + os.path.join(basedir, _rel)
    SQLALCHEMY_DATABASE_URI = _db_url
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    
    # File uploads (use absolute path inside project to avoid cwd issues)
    UPLOAD_FOLDER = os.environ.get('UPLOAD_FOLDER') or os.path.join(basedir, 'uploads')
    MAX_CONTENT_LENGTH = int(os.environ.get('MAX_CONTENT_LENGTH', 16 * 1024 * 1024))  # 16MB
    ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp', 'heic', 'heif', 'tiff', 'tif', 'bmp'}
    
    # Anthropic API
    ANTHROPIC_API_KEY = os.environ.get('ANTHROPIC_API_KEY')

    # OpenAI API
    OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY')

    # Ollama API
    OLLAMA_API_URL = os.environ.get('OLLAMA_API_URL', 'http://192.168.0.99:11434')
    LLM_DEFAULT_PROVIDER = os.environ.get('LLM_DEFAULT_PROVIDER', 'ollama')
    LLM_MODEL_VISION_ANALYSIS = os.environ.get('LLM_MODEL_VISION_ANALYSIS', 'QWEN36_35B')
    LLM_MODEL_STAT_GENERATION = os.environ.get('LLM_MODEL_STAT_GENERATION', 'QWEN36_35B')
    LLM_MODEL_BATTLE_NARRATIVE = os.environ.get('LLM_MODEL_BATTLE_NARRATIVE', 'QWEN36_35B')
    LLM_MODEL_SPECIES_IDENTIFICATION = os.environ.get('LLM_MODEL_SPECIES_IDENTIFICATION', 'QWEN36_35B')
    LLM_MODEL_QUICK_TASKS = os.environ.get('LLM_MODEL_QUICK_TASKS', 'QWEN36_35B')

    # Bug classifier REST API
    BUG_CLASSIFIER_URL = os.environ.get('BUG_CLASSIFIER_URL', 'http://192.168.0.99:8082')
    HF_BUG_CLASSIFIER_ENABLED = os.environ.get('HF_BUG_CLASSIFIER_ENABLED', 'true').lower() == 'true'
    HF_BUG_CLASSIFIER_REQUIRED = os.environ.get('HF_BUG_CLASSIFIER_REQUIRED', 'false').lower() == 'true'
    HF_BUG_CLASSIFIER_MIN_CONFIDENCE = float(os.environ.get('HF_BUG_CLASSIFIER_MIN_CONFIDENCE', 0.45))
    
    # Pagination
    BUGS_PER_PAGE = int(os.environ.get('BUGS_PER_PAGE', 20))
    BATTLES_PER_PAGE = int(os.environ.get('BATTLES_PER_PAGE', 10))

    # Operational safety
    ENABLE_DB_EXPLORER = os.environ.get('ENABLE_DB_EXPLORER', 'false').lower() == 'true'
    DB_EXPLORER_ALLOW_WRITES = os.environ.get('DB_EXPLORER_ALLOW_WRITES', 'false').lower() == 'true'

    # Background jobs
    ENABLE_BACKGROUND_JOBS = os.environ.get('ENABLE_BACKGROUND_JOBS', 'true').lower() == 'true'
    JOB_POLL_INTERVAL_SECONDS = int(os.environ.get('JOB_POLL_INTERVAL_SECONDS', 15))
