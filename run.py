from app import create_app, db
from flask_migrate import Migrate
from app.models import User, Bug, Battle, Tourmanent, Comment
import os

app = create_app(os.getenv('FLASK_CONFIG') or 'default')
migrate = Migrate(app, db)

@app.shell_context_processor
def make_shell_context():

    return {'db': db, 'User': User, 'Bug': Bug, 'Battle': Battle, 'Tourmanent': Tourmanent, 'Comment': Comment}

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(host='0.0.0.0', port=5000, debug=True)