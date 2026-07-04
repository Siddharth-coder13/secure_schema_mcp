import sqlalchemy as sa


def build_demo_database(db_path: str = "sqlite:///test_schema.db") -> None:
    engine = sa.create_engine(db_path)

    with engine.begin() as connection:
        connection.execute(sa.text("DROP TABLE IF EXISTS order_items"))
        connection.execute(sa.text("DROP TABLE IF EXISTS orders"))
        connection.execute(sa.text("DROP TABLE IF EXISTS products"))
        connection.execute(sa.text("DROP TABLE IF EXISTS users"))

        connection.execute(
            sa.text(
                """
                CREATE TABLE users (
                    user_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL UNIQUE,
                    email TEXT NOT NULL UNIQUE,
                    is_active INTEGER DEFAULT 1
                )
                """
            )
        )
        connection.execute(
            sa.text(
                """
                CREATE TABLE products (
                    product_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    product_name TEXT NOT NULL,
                    price REAL NOT NULL,
                    sku TEXT UNIQUE
                )
                """
            )
        )
        connection.execute(
            sa.text(
                """
                CREATE TABLE orders (
                    order_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    total_amount REAL NOT NULL,
                    order_status TEXT DEFAULT 'pending',
                    FOREIGN KEY (user_id) REFERENCES users(user_id)
                )
                """
            )
        )
        connection.execute(
            sa.text(
                """
                CREATE TABLE order_items (
                    order_id INTEGER NOT NULL,
                    product_id INTEGER NOT NULL,
                    quantity INTEGER NOT NULL,
                    PRIMARY KEY (order_id, product_id),
                    FOREIGN KEY (order_id) REFERENCES orders(order_id),
                    FOREIGN KEY (product_id) REFERENCES products(product_id)
                )
                """
            )
        )

        connection.execute(
            sa.text(
                "INSERT INTO users (username, email) "
                "VALUES ('john_doe', 'john@secretcompany.com')"
            )
        )
        connection.execute(
            sa.text(
                "INSERT INTO users (username, email) "
                "VALUES ('jane_smith', 'jane@leakproof.io')"
            )
        )
        connection.execute(
            sa.text(
                "INSERT INTO products (product_name, price, sku) "
                "VALUES ('Secure Core Terminal', 299.99, 'SEC-001')"
            )
        )
        connection.execute(
            sa.text(
                "INSERT INTO orders (user_id, total_amount) VALUES (1, 299.99)"
            )
        )
        connection.execute(
            sa.text(
                "INSERT INTO order_items (order_id, product_id, quantity) "
                "VALUES (1, 1, 1)"
            )
        )

    engine.dispose()


if __name__ == "__main__":
    build_demo_database()
    print("Created test_schema.db with four related demo tables.")
