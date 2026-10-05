from app import create_app
from app.models import Product

app = create_app()
app.app_context().push()

city_id = 1  # <-- change this if Nashik isn't city_id=1

products = Product.query.filter_by(city_id=city_id).filter(Product.group_name.isnot(None)).order_by(Product.group_name, Product.name).all()

print(f"{'ID':<6}{'Name':<40}{'Group':<25}{'Class':<15}")
print("-" * 90)
for p in products:
    print(f"{p.id:<6}{p.name[:38]:<40}{p.group_name[:23]:<25}{(p.applicable_class or 'common'):<15}")