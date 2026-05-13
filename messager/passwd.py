import secrets
db_password = secrets.token_urlsafe(32)

print(db_password)