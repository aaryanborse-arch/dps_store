from app import create_app, db
from app.models import City

app = create_app()
app.app_context().push()

for c in City.query.all():
    print(f"{c.name}: prefix={c.invoice_prefix!r}, next_number={c.next_invoice_number!r}")