from app import create_app, db
from app.models import User, Role
from getpass import getpass

app = create_app()

def create_superadmin():
    with app.app_context():
        db.create_all()

        username = input("Enter a username for the superadmin: ").strip()
        password = getpass("Enter a secure password for the superadmin: ").strip()

        existing_user = User.query.filter_by(username=username).first()
        if existing_user:
            print(f"User '{username}' already exists.")
            return

        superadmin = User(
            username=username,
            role=Role.SUPERADMIN,
            shop_id=None  # SUPERADMIN doesn't belong to a specific shop
        )
        superadmin.set_password(password)

        db.session.add(superadmin)
        db.session.commit()
        print(f"Superadmin user '{username}' created successfully.")

if __name__ == '__main__':
    create_superadmin()
