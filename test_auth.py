from auth import sign_in_user

email = "trevell.pruitt@gmail.com"
password = "Rakwywij02!"

response = sign_in_user(email, password)

print("USER:")
print(response.user)

print("\nSESSION:")
print(response.session)