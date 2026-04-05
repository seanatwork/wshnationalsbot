from flask import Flask, jsonify
from config import HEALTHCHECK_HOST, HEALTHCHECK_PORT

app = Flask(__name__)


@app.route('/health')
def health():
    return jsonify({"status": "healthy"}), 200


def start_healthcheck() -> None:
    """Start the Flask healthcheck server."""
    app.run(host=HEALTHCHECK_HOST, port=HEALTHCHECK_PORT)


if __name__ == '__main__':
    start_healthcheck()
