"""Import smoke-test — prints all registered routes."""
from app.main import app
for r in app.routes:
    print(getattr(r, "methods", ""), getattr(r, "path", r))
print("OK")
