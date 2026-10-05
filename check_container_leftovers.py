from app import create_app
from app.models import Product

app = create_app()
app.app_context().push()

city_id = 1  # <-- change this if Nashik isn't city_id=1

all_products = Product.query.filter_by(city_id=city_id, is_active=True).all()
group_names = set(p.group_name for p in all_products if p.group_name)

print("Checking for standalone products whose NAME exactly matches a Group name (likely leftover containers)...\n")
found_any = False
for p in all_products:
    if p.name.strip() in group_names and not p.group_name:
        print(f"#{p.id} — '{p.name}' (no group set, but matches group '{p.name}') — Price: {p.price}, HSN: {p.hsn_number}, Stock: {p.stock_quantity}")
        found_any = True

if not found_any:
    print("None found — no leftover standalone container products detected.")