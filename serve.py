from waitress import serve
import sys

# https://iq-inc.com/wp-content/uploads/2021/02/AndyRelativeImports-300x294.jpg
sys.path.append(".")
from app import app
serve(app, host='0.0.0.0', port=8080)