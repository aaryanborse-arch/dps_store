from app import create_app, db
from app.models import Product

app = create_app()
app.app_context().push()

corrections = {
    1036: {'name': 'Chart Paper - Blue', 'group': 'Chart Paper'},
    1040: {'name': 'Fluorescent Paper (Mix Color) - Blue', 'group': 'Fluorescent Paper'},
    1039: {'name': 'Fluorescent Paper (Mix Color) - Green', 'group': 'Fluorescent Paper'},
    1045: {'name': 'Chart Paper - Red', 'group': 'Chart Paper'},
    1042: {'name': 'Chart Paper pcs (4 Color) - Red', 'group': 'Chart Paper'},
    1041: {'name': 'Fluorescent Paper (Mix Color) - Red', 'group': 'Fluorescent Paper'},
    1043: {'name': 'Fluorescent Paper (Mix Color) - Red', 'group': 'Fluorescent Paper'},
    1037: {'name': 'Chart Paper - Green', 'group': 'Chart Paper'},
    1038: {'name': 'Chart Paper pcs (4 Color) - Green', 'group': 'Chart Paper'},
    1035: {'name': 'Chart Paper - Red', 'group': 'Chart Paper'},
}

for pid, values in corrections.items():
    p = Product.query.get(pid)
    if p:
        print(f"Fixing #{pid}: name '{p.name}' -> '{values['name']}', group '{p.group_name}' -> '{values['group']}'")
        p.name = values['name']
        p.group_name = values['group']
    else:
        print(f"#{pid} not found — skipping")

db.session.commit()
print("Done")