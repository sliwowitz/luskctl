#!/usr/bin/env python3
"""
Setup script for luskctl that preserves git branch information during installation.
"""

import subprocess
import sys

from setuptools import find_packages, setup

# Run our build script first to preserve git branch information
try:
    result = subprocess.run([sys.executable, "build_script.py"], capture_output=True, text=True)
    if result.returncode != 0:
        print(f"Warning: Build script failed: {result.stderr}")
except Exception as e:
    print(f"Warning: Could not run build script: {e}")

# Read the pyproject.toml to get the package metadata
try:
    import tomllib

    with open("pyproject.toml", "rb") as f:
        pyproject_data = tomllib.load(f)

    name = pyproject_data["tool"]["poetry"]["name"]
    version = pyproject_data["tool"]["poetry"]["version"]
    description = pyproject_data["tool"]["poetry"]["description"]
    authors = pyproject_data["tool"]["poetry"]["authors"]
    license_text = pyproject_data["tool"]["poetry"]["license"]

    # Get dependencies
    dependencies = pyproject_data["tool"]["poetry"]["dependencies"]
    install_requires = []
    for dep, version_spec in dependencies.items():
        if dep == "python":
            continue
        if isinstance(version_spec, str):
            install_requires.append(f"{dep}{version_spec}")
        else:
            install_requires.append(dep)

    # Get packages
    packages = find_packages(where="src")
    package_dir = {"": "src"}

    setup(
        name=name,
        version=version,
        description=description,
        author=authors[0] if isinstance(authors, list) else authors,
        license=license_text,
        packages=packages,
        package_dir=package_dir,
        install_requires=install_requires,
        python_requires=">=3.12,<4.0",
        include_package_data=True,
        zip_safe=False,
    )

except Exception as e:
    print(f"Error reading pyproject.toml: {e}")
    sys.exit(1)
