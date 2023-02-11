import tomllib
with open("pyproject.toml", mode="rb") as f:
    print(tomllib.load(f)["project"]["version"])
