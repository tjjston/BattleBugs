from app import create_app, db
from config import Config

app = create_app(Config)

with app.app_context():
    from app.models import User, Bug, Battle, Tournament, Comment

@app.shell_context_processor
def make_shell_context():
    return {'db': db, 'User': User, 'Bug': Bug, 'Battle': Battle, 'Tournament': Tournament, 'Comment': Comment}

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(host='0.0.0.0', port=5000, debug=False)