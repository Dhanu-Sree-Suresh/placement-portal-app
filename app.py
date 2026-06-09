from config import Config
from flask import Flask


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    @app.route("/")
    def index():
        return "Placement Portal is running!"

    return app


if __name__ == "__main__":
    app = create_app()
    app.run(debug=True)
