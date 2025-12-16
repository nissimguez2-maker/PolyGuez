import importlib.metadata


def main() -> None:
    """
    Prints the installed version of the `agents` package, if available.
    This is useful when debugging environment issues.
    """
    try:
        version = importlib.metadata.version("agents")
    except importlib.metadata.PackageNotFoundError:
        print("The 'agents' package is not installed in this environment.")
        return

    print(f"agents package version: {version}")


if __name__ == "__main__":
    main()
