import os, sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from db.lookup_queries import fetch_user_by_username

username = "kogutama"  # try without domain prefix first
row = fetch_user_by_username(username)

if row is None:
    print("User NOT found. Try with domain prefix or different casing.")
else:
    print("User found!")
    # Print every field except password
    for k, v in row.items():
        if "PASS" not in k.upper():
            print(f"  {k}: {repr(v)}")
    print(f"  ACTIVE type: {type(row.get('ACTIVE'))} = {repr(row.get('ACTIVE'))}")
    print(f"  PASSWORDISRESET type: {type(row.get('PASSWORDISRESET'))} = {repr(row.get('PASSWORDISRESET'))}")
    print(f"  ACCESSLEVEL: {repr(row.get('ACCESSLEVEL'))}")