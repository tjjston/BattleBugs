import os
from dotenv import load_dotenv

basedir = os.path.abspath(os.path.dirname(__file__))
load_dotenv()

class Config:
    # Flask
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'dev-secret-key-change-in-production'
    
    # Database
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or \
        'sqlite:///' + os.path.join(basedir, 'database', 'bug_arena.db')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    
    # File uploads
    UPLOAD_FOLDER = os.environ.get('UPLOAD_FOLDER') or 'uploads'
    MAX_CONTENT_LENGTH = int(os.environ.get('MAX_CONTENT_LENGTH', 16 * 1024 * 1024))  # 16MB
    ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
    
    # Anthropic API
    ANTHROPIC_API_KEY = os.environ.get('ANTHROPIC_API_KEY')

    # OpenAI API
    OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY')

    # Ollama API
    OLLAMA_API_URL = os.environ.get('OLLAMA_API_URL', 'http://192.168.0.99:11434')
    
    # Pagination
    BUGS_PER_PAGE = int(os.environ.get('BUGS_PER_PAGE', 20))
    BATTLES_PER_PAGE = int(os.environ.get('BATTLES_PER_PAGE', 10))
