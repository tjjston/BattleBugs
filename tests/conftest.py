import pytest

from app import create_app, db
from app.models import Bug, User


class TestConfig:
    TESTING = True
    SECRET_KEY = 'test-secret'
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    WTF_CSRF_ENABLED = False
    ENABLE_BACKGROUND_JOBS = False
    ENABLE_DB_EXPLORER = False
    DB_EXPLORER_ALLOW_WRITES = False
    UPLOAD_FOLDER = '/tmp/battlebugs-test-uploads'
    ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
    BUGS_PER_PAGE = 20
    BATTLES_PER_PAGE = 10


@pytest.fixture()
def app():
    app = create_app(TestConfig)
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def user(app):
    return create_user('user', 'user@example.com')


@pytest.fixture()
def other_user(app):
    return create_user('other', 'other@example.com')


@pytest.fixture()
def moderator(app):
    return create_user('mod', 'mod@example.com', role='MODERATOR')


@pytest.fixture()
def admin(app):
    return create_user('admin', 'admin@example.com', role='ADMIN')


def create_user(username, email, role='USER'):
    user = User(username=username, email=email, role=role)
    user.set_password('password')
    db.session.add(user)
    db.session.commit()
    return user


def create_bug(owner, nickname='Test Bug', **kwargs):
    bug = Bug(
        nickname=nickname,
        image_path='test.jpg',
        user_id=owner.id,
        attack=kwargs.pop('attack', 10),
        defense=kwargs.pop('defense', 10),
        speed=kwargs.pop('speed', 10),
        stats_generated=kwargs.pop('stats_generated', True),
        **kwargs,
    )
    db.session.add(bug)
    db.session.commit()
    return bug


def login(client, username, password='password'):
    return client.post('/login', data={'username': username, 'password': password}, follow_redirects=False)
