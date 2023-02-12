import tomllib


def main():
    with open("pyproject.toml", mode="rb") as f:
        print(tomllib.load(f)["project"]["version"])


if __name__ == "__main__":
    main()
